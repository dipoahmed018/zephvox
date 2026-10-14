"""Per-account limits: config.toml defaults < server-wide overrides < the account's own."""

from __future__ import annotations

import threading
from typing import Any

from ..engine.config import ServerLimits
from .db import Account, Database

DEFAULTS_KEY = "default_limits"
NAMES = tuple(ServerLimits.model_fields)


def effective(config_defaults: ServerLimits, db: Database, account: Account | None = None) -> ServerLimits:
    data: dict[str, Any] = config_defaults.model_dump()
    data.update(db.setting(DEFAULTS_KEY, {}))
    if account is not None:
        data.update(account.limits)
    return ServerLimits(**data)


def parse_overrides(values: dict[str, Any]) -> dict[str, Any]:
    """Validate `limits set` values (None = remove the override)."""
    unknown = set(values) - set(NAMES)
    if unknown:
        raise ValueError(f"unknown limit(s): {', '.join(sorted(unknown))}; choose from {', '.join(NAMES)}")
    checked = ServerLimits(**{k: v for k, v in values.items() if v is not None})  # type checks
    return {k: getattr(checked, k) if v is not None else None for k, v in values.items()}


def apply(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    out = dict(current)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class RateLimiter:
    """A token bucket per account: `per_minute` requests, refilled continuously."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}  # account → (tokens, at)
        self._lock = threading.Lock()

    def allow(self, account_id: str, per_minute: int, now: float) -> bool:
        if per_minute <= 0:
            return True
        with self._lock:
            tokens, at = self._buckets.get(account_id, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - at) * per_minute / 60.0)
            if tokens < 1.0:
                self._buckets[account_id] = (tokens, now)
                return False
            self._buckets[account_id] = (tokens - 1.0, now)
            return True
