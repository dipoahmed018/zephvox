"""Job webhooks: a signed POST when a job finishes, retried after 1, 5 and 30 minutes.

Header `Zephvox-Signature: t=<unix>,v1=<hex HMAC-SHA256(account webhook secret, "<t>.<body>")>`;
receivers check it with `keys.verify`. Deliveries are stored, so retries survive a restart.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from .db import Database
from .keys import sign

RETRY_DELAYS_S = (60, 300, 1800)
SIGNATURE_HEADER = "Zephvox-Signature"
TIMEOUT_S = 10.0


class WebhookError(ValueError):
    pass


def check_url(url: str, allow_private: bool, resolve: Callable[[str], list[str]] | None = None) -> None:
    """Refuse URLs that aren't http(s), or (unless allowed) that point at a private address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebhookError("webhook_url must be an http(s) URL")
    if allow_private:
        return
    resolve = resolve or _resolve
    try:
        addresses = resolve(parts.hostname)
    except OSError as e:
        raise WebhookError(f"webhook host {parts.hostname!r} can't be resolved") from e
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise WebhookError(f"webhook_url points at a private address ({ip}); the server admin can allow this")


def _resolve(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


class Deliverer:
    def __init__(self, db: Database, payload: Callable[[str, str], dict[str, Any] | None], secret_for: Callable[[str], str | None],
                 clock: Callable[[], float], allow_private: bool = False,
                 client: httpx.Client | None = None, poll_s: float = 5.0):  # fmt: skip
        self.db = db
        self.payload = payload  # (job_id, event) → body, or None if the job is gone
        self.secret_for = secret_for  # job_id → the account's webhook secret
        self.clock = clock
        self.allow_private = allow_private
        self.client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)
        self.poll_s = poll_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="webhooks", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.client.close()

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_due()
            self._wake.wait(self.poll_s)
            self._wake.clear()

    def run_due(self) -> int:
        """Send every delivery that is due; returns how many were attempted."""
        due = self.db.due_deliveries(self.clock())
        for delivery in due:
            self._send(delivery)
        return len(due)

    def _send(self, delivery: dict[str, Any]) -> None:
        job_id, event, attempts = delivery["job_id"], delivery["event"], delivery["attempts"] + 1
        job = self.db.job(job_id)
        body = self.payload(job_id, event)
        secret = self.secret_for(job_id)
        if job is None or not job.webhook_url or body is None or secret is None:
            self.db.update_delivery(job_id, event, status="dropped", attempts=attempts)
            return
        data = json.dumps(body, ensure_ascii=False).encode()
        now = int(self.clock())
        try:
            check_url(job.webhook_url, self.allow_private)
            response = self.client.post(job.webhook_url, content=data, headers={
                "Content-Type": "application/json", SIGNATURE_HEADER: sign(secret, now, data),
                "Zephvox-Event": event, "Zephvox-Delivery": f"{job_id}:{event}:{attempts}"})  # fmt: skip
            if 200 <= response.status_code < 300:
                self.db.update_delivery(job_id, event, status="delivered", attempts=attempts, last_error=None)
                return
            error = f"HTTP {response.status_code}"
        except (httpx.HTTPError, WebhookError) as e:
            error = str(e) or type(e).__name__
        if attempts > len(RETRY_DELAYS_S):
            self.db.update_delivery(job_id, event, status="failed", attempts=attempts, last_error=error)
        else:
            self.db.update_delivery(job_id, event, attempts=attempts, last_error=error,
                                    next_at=self.clock() + RETRY_DELAYS_S[attempts - 1])  # fmt: skip
