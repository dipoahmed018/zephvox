"""`zephvox server ...`: run the server and manage its accounts, invites, devices, limits and jobs.

The admin commands open the server's database directly, so they work over SSH on the server
machine, whether or not the server is running.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..engine.config import Config
from ..engine.errors import ZephvoxError
from . import admin
from . import limits as limits_mod
from .db import Database
from .service import server_dir

DURATION = re.compile(r"^(\d+(?:\.\d+)?)([smhd])$")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
LIMIT_FLAGS = {"max_audio_minutes": float, "max_jobs": int, "storage_mb": int, "requests_per_minute": int}


def add_parser(sub: Any, common: argparse.ArgumentParser) -> None:
    srv = sub.add_parser("server", parents=[common], help="run zephvox as a service for many accounts, and manage it")
    cmd = srv.add_subparsers(dest="server_command", required=True)
    # The common options also work at the end (`server invite bob --config x.toml`); SUPPRESS keeps
    # a nested parser's default from overwriting a value given earlier.
    shared = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    shared.add_argument("--config", type=Path)
    shared.add_argument("-q", "--quiet", action="store_true")

    def group(name: str, help: str) -> Any:
        return cmd.add_parser(name, parents=[shared], help=help).add_subparsers(dest="action", required=True)

    s = cmd.add_parser("serve", parents=[shared], help="run the server until Ctrl+C")
    s.add_argument("--host", help="default from [server] in config.toml (127.0.0.1); 0.0.0.0 for all interfaces")
    s.add_argument("--port", type=int, help="default 8770")

    svc = cmd.add_parser("install-service", parents=[shared],
                         help="run the server in the background, started with the computer")  # fmt: skip
    svc.add_argument("--host", help="default from [server] in config.toml (127.0.0.1)")
    svc.add_argument("--port", type=int)
    cmd.add_parser("remove-service", parents=[shared], help="stop and remove the background service")

    acc = group("accounts", "people who may use this server")
    acc.add_parser("list", parents=[shared])
    acc.add_parser("add", parents=[shared]).add_argument("name")
    r = acc.add_parser("remove", parents=[shared], help="delete an account with its devices, jobs and data")
    r.add_argument("account")
    r.add_argument("-y", "--yes", action="store_true")

    inv = cmd.add_parser("invite", parents=[shared], help="a one-time code that connects one device to an account")
    inv.add_argument("account")
    inv.add_argument("--expires", default="7d", help="e.g. 30m, 12h, 7d (default 7d)")
    inv.add_argument("--url", help="this server's address, to print the client's setup command")

    dev = group("devices", "devices connected to accounts")
    dev.add_parser("list", parents=[shared]).add_argument("account", nargs="?")
    dev.add_parser("revoke", parents=[shared], help="its key stops working at once").add_argument("device")

    lim = group("limits", "per-account limits")
    lim.add_parser("show", parents=[shared]).add_argument("account", nargs="?", help="default: the server-wide defaults")
    lset = lim.add_parser("set", parents=[shared], help="change limits for one account, or for all with --default")
    who = lset.add_mutually_exclusive_group(required=True)
    who.add_argument("account", nargs="?")
    who.add_argument("--default", action="store_true", help="server-wide default for every account")
    for name, kind in LIMIT_FLAGS.items():
        lset.add_argument(f"--{name.replace('_', '-')}", type=kind, dest=name)
    lset.add_argument("--clear", nargs="+", choices=list(LIMIT_FLAGS), default=[], help="go back to the default")

    jobs = group("jobs", "analysis jobs")
    jl = jobs.add_parser("list", parents=[shared])
    jl.add_argument("--account")
    jl.add_argument("--status", choices=["queued", "running", "done", "failed", "cancelled"])
    jobs.add_parser("cancel", parents=[shared]).add_argument("job")

    wh = cmd.add_parser("webhook-secret", parents=[shared], help="the secret an account's webhooks are signed with")
    wh.add_argument("account")
    wh.add_argument("--rotate", action="store_true", help="make a new one (the old one stops verifying)")


def parse_duration(text: str) -> float:
    match = DURATION.match(text.strip())
    if not match:
        raise ZephvoxError(f"durations look like 30m, 12h or 7d, not {text!r}")
    return float(match[1]) * UNITS[match[2]]


def when(ts: float | None) -> str:
    return "-" if ts is None else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def run(args: argparse.Namespace, config: Config, ask: Callable[[str], str] = input,
        clock: Callable[[], float] = time.time) -> int:  # fmt: skip
    if args.server_command == "serve":
        return serve(config, args.host, args.port)
    if args.server_command in ("install-service", "remove-service"):
        from . import os_service

        if args.server_command == "remove-service":
            print("Removed the zephvox server service." if os_service.remove() else "No service was installed.")
            return 0
        workdir = config.source.parent if config.source else Path.cwd()
        cmd = os_service.command(sys.executable, getattr(args, "config", None) or config.source if config.source and
                                 config.source.exists() else None, args.host, args.port)  # fmt: skip
        try:
            where = os_service.install(cmd, workdir)
        except (OSError, subprocess.CalledProcessError) as e:
            raise ZephvoxError(f"couldn't install the service: {e}") from e
        print(f"The server now runs in the background: {where}")
        return 0
    db = Database(server_dir(config) / "server.db")
    try:
        return _admin(args, config, db, ask, clock)
    finally:
        db.close()


def _account(db: Database, ref: str):
    account = db.account(ref)
    if account is None:
        raise ZephvoxError(f"no account {ref!r} (see `zephvox server accounts list`)")
    return account


def _admin(args: argparse.Namespace, config: Config, db: Database, ask: Callable[[str], str],
           clock: Callable[[], float]) -> int:  # fmt: skip
    command, action = args.server_command, getattr(args, "action", None)
    if command == "accounts" and action == "list":
        rows = db.accounts()
        if not rows:
            print("No accounts yet: zephvox server accounts add <name>")
        for acc in rows:
            devices = [d for d in db.devices(acc.id) if d.revoked is None]
            print(f"{acc.name:<24} {acc.id}  {len(devices)} device(s)  created {when(acc.created)}")
    elif command == "accounts" and action == "add":
        acc = admin.add_account(db, args.name, clock())
        print(f"Added {acc.name} ({acc.id}). Connect a device with: zephvox server invite {acc.name}")
    elif command == "accounts" and action == "remove":
        acc = _account(db, args.account)
        if not args.yes and ask(f"Delete {acc.name} with all its devices, jobs and data? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing deleted.")
            return 1
        print(f"Deleted {admin.remove_account(db, config, acc.id)}.")
    elif command == "invite":
        acc = _account(db, args.account)
        ttl = parse_duration(args.expires)
        code = db.add_invite(acc.id, clock(), ttl)
        print(f"Invite for {acc.name} (one device, expires {when(clock() + ttl)}):\n\n  {code}\n")
        url = args.url or "https://<this server>"
        print("On the device: Settings → Where analysis runs → A server (with this address and code), or install the small client with:\n")
        print(f"  zephvox setup --server-url {url} --invite {code}")
    elif command == "devices" and action == "list":
        account_id = _account(db, args.account).id if args.account else None
        names = {a.id: a.name for a in db.accounts()}
        for d in db.devices(account_id):
            state = f"revoked {when(d.revoked)}" if d.revoked else f"last seen {when(d.last_seen)}"
            print(f"{d.id}  {names.get(d.account_id, '?'):<20} {d.name:<24} {state}")
    elif command == "devices" and action == "revoke":
        device = db.device(args.device)
        if device is None:
            raise ZephvoxError(f"no device {args.device!r}")
        db.revoke_device(device.id, clock())
        print(f"Revoked {device.name} ({device.id}); its key no longer works.")
    elif command == "limits":
        return _limits(args, config, db)
    elif command == "jobs" and action == "list":
        account_id = _account(db, args.account).id if args.account else None
        names = {a.id: a.name for a in db.accounts()}
        for j in db.jobs(account_id, (args.status,) if args.status else None):
            length = f"{j.duration / 60:.1f} min" if j.duration else "-"
            print(f"{j.id}  {names.get(j.account_id, '?'):<16} {j.status:<9} {length:>9}  {when(j.created)}  {j.error or ''}")
    elif command == "jobs" and action == "cancel":
        admin.cancel_job(db, args.job, clock())
        print(f"Cancelled {args.job}.")
    elif command == "webhook-secret":
        acc = _account(db, args.account)
        print(db.rotate_webhook_secret(acc.id) if args.rotate else acc.webhook_secret)
    return 0


def _limits(args: argparse.Namespace, config: Config, db: Database) -> int:
    defaults = config.server.limits
    if args.action == "show":
        account = _account(db, args.account) if args.account else None
        effective = limits_mod.effective(defaults, db, account)
        overrides = account.limits if account else db.setting(limits_mod.DEFAULTS_KEY, {})
        print(f"Limits for {account.name if account else 'every account (defaults)'}:")
        for name, value in effective.model_dump().items():
            mark = "  (set here)" if name in overrides else ""
            print(f"  {name:<20} {value:g}{mark}")
        return 0
    changes: dict[str, Any] = {name: getattr(args, name) for name in LIMIT_FLAGS if getattr(args, name) is not None}
    changes.update({name: None for name in args.clear})
    if not changes:
        raise ZephvoxError("nothing to change: pass e.g. --max-jobs 3 or --clear max_jobs")
    try:
        changes = limits_mod.parse_overrides(changes)
    except ValueError as e:
        raise ZephvoxError(str(e)) from e
    if args.default:
        db.set_setting(limits_mod.DEFAULTS_KEY, limits_mod.apply(db.setting(limits_mod.DEFAULTS_KEY, {}), changes))
        print("Updated the defaults for every account.")
    else:
        account = _account(db, args.account)
        db.set_account_limits(account.id, limits_mod.apply(account.limits, changes))
        print(f"Updated limits for {account.name}.")
    return 0


def serve(config: Config, host: str | None, port: int | None) -> int:
    try:
        import uvicorn

        from ..engine.engine import Engine
        from .app import create_server_app
        from .service import Server
    except ImportError as e:
        raise ZephvoxError(f"The server needs extra packages: uv sync --extra web ({e.name} missing)") from e
    host = host or config.server.host
    port = port or config.server.port
    server = Server(Engine(config))
    if not server.db.accounts():
        print("No accounts yet. Add one with: zephvox server accounts add <name>", file=sys.stderr)
    print(f"zephvox server is running at http://{host}:{port}  (API docs: /v1/docs; Ctrl+C to stop)", file=sys.stderr)
    try:
        uvicorn.run(create_server_app(server), host=host, port=port, log_level="warning")
    finally:
        server.close()
    return 0
