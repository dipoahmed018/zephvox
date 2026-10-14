"""Server administration shared by `zephvox server …` and the page's Sharing settings.

Works on the server's database directly, whether or not the server is running.
"""

from __future__ import annotations

import shutil
from typing import Any

from ..engine.config import Config
from ..engine.errors import ZephvoxError
from . import limits as limits_mod
from .db import Account, Database
from .service import server_dir

LIMIT_NAMES = ("max_audio_minutes", "max_jobs", "storage_mb", "requests_per_minute")


def account(db: Database, ref: str) -> Account:
    found = db.account(ref)
    if found is None:
        raise ZephvoxError(f"no account {ref!r}")
    return found


def overview(db: Database, config: Config, jobs: int = 50) -> dict[str, Any]:
    """Accounts with their devices, usage and limits; the default limits; recent jobs."""
    defaults = config.server.limits
    names = {}
    accounts = []
    for acc in db.accounts():
        names[acc.id] = acc.name
        accounts.append({
            "id": acc.id, "name": acc.name, "created": acc.created,
            "limits": limits_mod.effective(defaults, db, acc).model_dump(), "overrides": acc.limits,
            "usage": {"active_jobs": db.active_jobs(acc.id),
                      "storage_mb": round(db.storage_bytes(acc.id) / (1024 * 1024), 1)},
            "webhook_secret": acc.webhook_secret,
            "devices": [{"id": d.id, "name": d.name, "created": d.created, "last_seen": d.last_seen,
                         "revoked": d.revoked} for d in db.devices(acc.id)],
        })  # fmt: skip
    return {
        "accounts": accounts,
        "defaults": {"limits": limits_mod.effective(defaults, db).model_dump(),
                     "overrides": db.setting(limits_mod.DEFAULTS_KEY, {}), "config": defaults.model_dump()},
        "jobs": [{"id": j.id, "account": names.get(j.account_id, "?"), "status": j.status, "created": j.created,
                  "duration": j.duration, "error": j.error} for j in db.jobs()[:jobs]],
    }  # fmt: skip


def add_account(db: Database, name: str, now: float) -> Account:
    name = name.strip()
    if not name:
        raise ZephvoxError("an account needs a name")
    try:
        return db.add_account(name, now)
    except ValueError as e:
        raise ZephvoxError(str(e)) from e


def remove_account(db: Database, config: Config, ref: str) -> str:
    """Delete an account with its devices, jobs and synced data. Returns its name."""
    acc = account(db, ref)
    root = server_dir(config)
    for job in db.jobs(acc.id):
        shutil.rmtree(root / "jobs" / job.id, ignore_errors=True)
    shutil.rmtree(root / "accounts" / acc.id, ignore_errors=True)
    db.remove_account(acc.id)
    return acc.name


def invite(db: Database, ref: str, now: float, ttl_s: float) -> dict[str, Any]:
    acc = account(db, ref)
    return {"account": acc.name, "code": db.add_invite(acc.id, now, ttl_s), "expires": now + ttl_s}


def revoke_device(db: Database, device_id: str, now: float) -> str:
    device = db.device(device_id)
    if device is None:
        raise ZephvoxError(f"no device {device_id!r}")
    db.revoke_device(device.id, now)
    return device.name


def set_limits(db: Database, ref: str | None, changes: dict[str, Any]) -> None:
    """Change limits for one account, or the defaults for every account (`ref=None`). None = back to the default."""
    unknown = set(changes) - set(LIMIT_NAMES)
    if unknown:
        raise ZephvoxError(f"unknown limit(s): {', '.join(sorted(unknown))}")
    try:
        changes = limits_mod.parse_overrides(changes)
    except ValueError as e:
        raise ZephvoxError(str(e)) from e
    if ref is None:
        db.set_setting(limits_mod.DEFAULTS_KEY, limits_mod.apply(db.setting(limits_mod.DEFAULTS_KEY, {}), changes))
    else:
        acc = account(db, ref)
        db.set_account_limits(acc.id, limits_mod.apply(acc.limits, changes))


def cancel_job(db: Database, job_id: str, now: float) -> None:
    job = db.job(job_id)
    if job is None:
        raise ZephvoxError(f"no job {job_id!r}")
    if job.status not in ("queued", "running"):
        raise ZephvoxError(f"job {job.id} is already {job.status}")
    db.update_job(job.id, status="cancelled", finished=now, expires=now)  # the janitor removes it


def rotate_webhook_secret(db: Database, ref: str) -> str:
    return db.rotate_webhook_secret(account(db, ref).id)
