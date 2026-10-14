"""The server's records in SQLite: accounts, devices, invites, jobs and webhook deliveries.

One connection shared by the server's threads (guarded by a lock). WAL mode lets the admin CLI
change things while the server runs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .keys import INVITE_PREFIX, KEY_PREFIX, WEBHOOK_PREFIX, hash_secret, new_id, new_secret

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    limits TEXT NOT NULL DEFAULT '{}',
    webhook_secret TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    last_seen REAL,
    revoked REAL
);
CREATE TABLE IF NOT EXISTS invites (
    code_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    expires REAL NOT NULL,
    used REAL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    expires REAL,
    analyzers TEXT NOT NULL DEFAULT '[]',
    filename TEXT NOT NULL DEFAULT '',
    duration REAL,
    idempotency_key TEXT,
    webhook_url TEXT,
    error TEXT,
    UNIQUE (account_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs (status);
CREATE TABLE IF NOT EXISTS deliveries (
    job_id TEXT NOT NULL,
    event TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    PRIMARY KEY (job_id, event)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

ACTIVE = ("queued", "running")


@dataclass
class Account:
    id: str
    name: str
    created: float
    limits: dict[str, Any] = field(default_factory=dict)  # overrides only
    webhook_secret: str = ""


@dataclass
class Device:
    id: str
    account_id: str
    name: str
    created: float
    last_seen: float | None = None
    revoked: float | None = None


@dataclass
class Job:
    id: str
    account_id: str
    status: str  # queued | running | done | failed | cancelled
    created: float
    started: float | None = None
    finished: float | None = None
    expires: float | None = None
    analyzers: list[str] = field(default_factory=list)
    filename: str = ""
    duration: float | None = None
    idempotency_key: str | None = None
    webhook_url: str | None = None
    error: str | None = None


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    # --- accounts -----------------------------------------------------------------------

    def add_account(self, name: str, now: float) -> Account:
        account = Account(new_id("acc"), name, now, {}, new_secret(WEBHOOK_PREFIX, 24))
        try:
            with self.tx() as c:
                c.execute("INSERT INTO accounts VALUES (?, ?, ?, '{}', ?)",
                          (account.id, name, now, account.webhook_secret))  # fmt: skip
        except sqlite3.IntegrityError as e:
            raise ValueError(f"an account named {name!r} already exists") from e
        return account

    @staticmethod
    def _account(row: sqlite3.Row) -> Account:
        return Account(row["id"], row["name"], row["created"], json.loads(row["limits"]), row["webhook_secret"])

    def account(self, ref: str) -> Account | None:
        """By id or name."""
        row = self._one("SELECT * FROM accounts WHERE id = ? OR name = ?", ref, ref)
        return self._account(row) if row else None

    def accounts(self) -> list[Account]:
        return [self._account(r) for r in self._all("SELECT * FROM accounts ORDER BY created")]

    def remove_account(self, account_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM deliveries WHERE job_id IN (SELECT id FROM jobs WHERE account_id = ?)", (account_id,))
            c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    def set_account_limits(self, account_id: str, limits: dict[str, Any]) -> None:
        with self.tx() as c:
            c.execute("UPDATE accounts SET limits = ? WHERE id = ?", (json.dumps(limits), account_id))

    def rotate_webhook_secret(self, account_id: str) -> str:
        secret = new_secret(WEBHOOK_PREFIX, 24)
        with self.tx() as c:
            c.execute("UPDATE accounts SET webhook_secret = ? WHERE id = ?", (secret, account_id))
        return secret

    # --- settings (server-wide values the CLI changes, e.g. default limits) ---------------

    def setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key = ?", key)
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (key, json.dumps(value)))  # fmt: skip

    # --- invites and devices ------------------------------------------------------------

    def add_invite(self, account_id: str, now: float, ttl_s: float) -> str:
        code = new_secret(INVITE_PREFIX, 18)
        with self.tx() as c:
            c.execute("INSERT INTO invites VALUES (?, ?, ?, ?, NULL)", (hash_secret(code), account_id, now, now + ttl_s))
        return code

    def redeem_invite(self, code: str, device_name: str, now: float) -> tuple[Device, str]:
        """Use up an invite: a new device on its account, and that device's key (shown once)."""
        with self.tx() as c:
            row = c.execute("SELECT * FROM invites WHERE code_hash = ?", (hash_secret(code),)).fetchone()
            if row is None or row["used"] is not None or row["expires"] < now:
                raise PermissionError("this invite is not valid (unknown, already used or expired)")
            c.execute("UPDATE invites SET used = ? WHERE code_hash = ?", (now, row["code_hash"]))
            device = Device(new_id("dev"), row["account_id"], device_name, now)
            key = new_secret(KEY_PREFIX)
            c.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                      (device.id, device.account_id, device.name, hash_secret(key), now))  # fmt: skip
        return device, key

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(row["id"], row["account_id"], row["name"], row["created"], row["last_seen"], row["revoked"])

    def device_for_key(self, key: str) -> Device | None:
        row = self._one("SELECT * FROM devices WHERE key_hash = ? AND revoked IS NULL", hash_secret(key))
        return self._device(row) if row else None

    def device(self, device_id: str) -> Device | None:
        row = self._one("SELECT * FROM devices WHERE id = ?", device_id)
        return self._device(row) if row else None

    def devices(self, account_id: str | None = None) -> list[Device]:
        if account_id is None:
            return [self._device(r) for r in self._all("SELECT * FROM devices ORDER BY created")]
        rows = self._all("SELECT * FROM devices WHERE account_id = ? ORDER BY created", account_id)
        return [self._device(r) for r in rows]

    def touch_device(self, device_id: str, now: float) -> None:
        with self.tx() as c:
            c.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, device_id))

    def rotate_key(self, device_id: str) -> str:
        """A new key for the device; the old one stops working at once."""
        key = new_secret(KEY_PREFIX)
        with self.tx() as c:
            c.execute("UPDATE devices SET key_hash = ? WHERE id = ? AND revoked IS NULL", (hash_secret(key), device_id))
        return key

    def revoke_device(self, device_id: str, now: float) -> None:
        with self.tx() as c:
            c.execute("UPDATE devices SET revoked = ? WHERE id = ? AND revoked IS NULL", (now, device_id))

    # --- jobs ---------------------------------------------------------------------------

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        data = dict(row)
        data["analyzers"] = json.loads(data["analyzers"])
        return Job(**data)

    def add_job(self, job: Job) -> Job:
        """Insert a job, or return the account's existing one with the same idempotency key."""
        with self.tx() as c:
            if job.idempotency_key:
                row = c.execute("SELECT * FROM jobs WHERE account_id = ? AND idempotency_key = ?",
                                (job.account_id, job.idempotency_key)).fetchone()  # fmt: skip
                if row:
                    return self._job(row)
            c.execute(
                "INSERT INTO jobs (id, account_id, status, created, analyzers, filename, duration, idempotency_key,"
                " webhook_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.account_id, job.status, job.created, json.dumps(job.analyzers), job.filename,
                 job.duration, job.idempotency_key, job.webhook_url),
            )  # fmt: skip
        return job

    def job(self, job_id: str, account_id: str | None = None) -> Job | None:
        """A job; with `account_id`, only if it belongs to that account."""
        row = self._one("SELECT * FROM jobs WHERE id = ?", job_id)
        if row is None or (account_id is not None and row["account_id"] != account_id):
            return None
        return self._job(row)

    def jobs(self, account_id: str | None = None, statuses: tuple[str, ...] | None = None) -> list[Job]:
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if account_id is not None:
            sql += " AND account_id = ?"
            args.append(account_id)
        if statuses:
            sql += f" AND status IN ({', '.join('?' * len(statuses))})"
            args += list(statuses)
        return [self._job(r) for r in self._all(sql + " ORDER BY created", *args)]

    def active_jobs(self, account_id: str) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM jobs WHERE account_id = ? AND status IN (?, ?)", account_id, *ACTIVE)
        return int(row["n"]) if row else 0

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def delete_job(self, job_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM deliveries WHERE job_id = ?", (job_id,))
            c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def expired_jobs(self, now: float) -> list[Job]:
        return [self._job(r) for r in self._all("SELECT * FROM jobs WHERE expires IS NOT NULL AND expires <= ?", now)]

    # --- webhook deliveries -------------------------------------------------------------

    def add_delivery(self, job_id: str, event: str, now: float) -> None:
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO deliveries (job_id, event, next_at) VALUES (?, ?, ?)", (job_id, event, now))

    def due_deliveries(self, now: float) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM deliveries WHERE status = 'pending' AND next_at <= ? ORDER BY next_at", now)
        return [dict(r) for r in rows]

    def update_delivery(self, job_id: str, event: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE deliveries SET {cols} WHERE job_id = ? AND event = ?", (*fields.values(), job_id, event))

    def deliveries(self, job_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._all("SELECT * FROM deliveries WHERE job_id = ?", job_id)]
