"""Secrets: device keys, invites and webhook secrets.

Only a SHA-256 hash of a key or invite is stored. A key is shown once, can't be recovered from the
database, and the unique hash column means no two devices ever share one.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "sk_"
INVITE_PREFIX = "inv_"
WEBHOOK_PREFIX = "whsec_"


def new_secret(prefix: str, nbytes: int = 32) -> str:
    return prefix + secrets.token_urlsafe(nbytes)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Webhook signature header value: `t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<body>">`."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify(secret: str, header: str, body: bytes, now: float, tolerance_s: float = 300) -> bool:
    """For receivers (and tests): check a signature and that it isn't older than `tolerance_s`."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(now - timestamp) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), header)
