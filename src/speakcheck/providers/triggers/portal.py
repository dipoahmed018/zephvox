"""Global shortcuts through the XDG desktop portal (Linux: KDE Plasma, GNOME 48+, Hyprland; Wayland or X11).

The desktop shows its own confirmation dialog the first time and lets the user rebind the keys in
its settings, so we only *suggest* key combos.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import secrets
import sys
import threading
from collections.abc import Callable
from typing import Any

from ...engine.errors import SpeakcheckError
from ..base import Availability, ProviderSettings, TriggerProvider

DEST = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.GlobalShortcuts"

DESCRIPTIONS = {
    "toggle_recording": "speakcheck: start / stop recording",
    "practice_attempt": "speakcheck: record a practice attempt",
    "cancel": "speakcheck: cancel recording",
}

_MODIFIERS = {"ctrl": "CTRL", "control": "CTRL", "alt": "ALT", "shift": "SHIFT", "super": "LOGO",
              "meta": "LOGO", "win": "LOGO", "cmd": "LOGO"}  # fmt: skip


def to_portal_trigger(combo: str) -> str:
    """"Ctrl+Alt+R" → "CTRL+ALT+r" (freedesktop shortcuts spec)."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty shortcut {combo!r}")
    *mods, key = parts
    out = []
    for m in mods:
        if m.lower() not in _MODIFIERS:
            raise ValueError(f"Unknown modifier {m!r} in {combo!r}")
        out.append(_MODIFIERS[m.lower()])
    out.append(key.lower() if len(key) == 1 else key)
    return "+".join(out)


class PortalSession:
    """Portal protocol over any dbus-fast-like bus (`call`, `unique_name`, `add_message_handler`)."""

    def __init__(self, bus: Any, fire: Callable[[str], None], response_timeout: float = 180.0):
        from dbus_fast import Message, MessageType, Variant

        self._Message, self._MessageType, self._Variant = Message, MessageType, Variant
        self.bus = bus
        self.fire = fire
        self.timeout = response_timeout
        self.session_handle: str | None = None
        self._pending: dict[str, asyncio.Future] = {}
        bus.add_message_handler(self._on_message)

    def _on_message(self, msg: Any) -> None:
        if msg.member == "Response" and msg.path in self._pending:
            future = self._pending.pop(msg.path)
            if not future.done():
                future.set_result(msg.body)
        elif msg.member == "Activated" and msg.interface == IFACE and msg.body and msg.body[0] == self.session_handle:
            self.fire(msg.body[1])

    async def _call(self, path: str, interface: str, member: str, signature: str, body: list) -> Any:
        reply = await self.bus.call(self._Message(destination=DEST, path=path, interface=interface, member=member,
                                                  signature=signature, body=body))  # fmt: skip
        if reply.message_type == self._MessageType.ERROR:
            raise SpeakcheckError(f"Portal {member} failed: {reply.error_name}: {reply.body}")
        return reply

    async def _request(self, member: str, signature: str, body_for: Callable[[str], list]) -> dict[str, Any]:
        """Call a portal method that answers asynchronously via a Request object's Response signal."""
        token = f"speakcheck{secrets.token_hex(4)}"
        sender = self.bus.unique_name.lstrip(":").replace(".", "_")
        request_path = f"{PATH}/request/{sender}/{token}"
        future = asyncio.get_running_loop().create_future()
        self._pending[request_path] = future  # register before calling: the reply can be instant
        await self._call(PATH, IFACE, member, signature, body_for(token))
        code, results = await asyncio.wait_for(future, self.timeout)
        if code != 0:
            raise SpeakcheckError(f"Portal {member} was declined or failed (code {code})")
        return results

    async def setup(self, bindings: dict[str, str], app_id: str) -> None:
        V = self._Variant
        for rule in (
            "type='signal',interface='org.freedesktop.portal.Request',member='Response'",
            f"type='signal',interface='{IFACE}',member='Activated'",
        ):
            await self.bus.call(self._Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                              interface="org.freedesktop.DBus", member="AddMatch",
                                              signature="s", body=[rule]))  # fmt: skip
        try:  # lets non-sandboxed apps show up under a stable name in the desktop's settings
            await self._call(PATH, "org.freedesktop.host.portal.Registry", "Register", "sa{sv}", [app_id, {}])
        except SpeakcheckError:
            pass
        results = await self._request(
            "CreateSession", "a{sv}",
            lambda t: [{"handle_token": V("s", t), "session_handle_token": V("s", "speakcheck")}],
        )  # fmt: skip
        self.session_handle = results["session_handle"].value
        shortcuts = [
            [action, {"description": V("s", DESCRIPTIONS.get(action, action)),
                      "preferred_trigger": V("s", to_portal_trigger(combo))}]
            for action, combo in bindings.items()
        ]  # fmt: skip
        await self._request(
            "BindShortcuts", "oa(sa{sv})sa{sv}",
            lambda t: [self.session_handle, shortcuts, "", {"handle_token": V("s", t)}],
        )  # fmt: skip

    async def close(self) -> None:
        if self.session_handle:
            try:
                await self._call(self.session_handle, "org.freedesktop.portal.Session", "Close", "", [])
            except SpeakcheckError:
                pass
            self.session_handle = None


def _run_coro(coro, timeout: float):
    """Run a coroutine to completion on a private loop in a helper thread (safe inside other loops)."""
    box: dict[str, Any] = {}

    def runner():
        try:
            box["value"] = asyncio.run(asyncio.wait_for(coro, timeout))
        except BaseException as e:  # noqa: BLE001 - reported to the caller
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout + 1)
    if "error" in box:
        raise box["error"]
    return box.get("value")


async def _portal_version() -> int:
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    try:
        reply = await bus.call(Message(destination=DEST, path=PATH, interface="org.freedesktop.DBus.Properties",
                                       member="Get", signature="ss", body=[IFACE, "version"]))  # fmt: skip
        return 0 if reply.message_type == MessageType.ERROR else int(reply.body[0].value)
    finally:
        bus.disconnect()


class PortalTriggers(TriggerProvider):
    name = "portal"

    class Settings(ProviderSettings):
        app_id: str = "io.github.speakcheck"  # matches the desktop entry from `speakcheck desktop-entry`

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: PortalSession | None = None
        self._bus: Any = None

    def check_available(self) -> Availability:
        if not sys.platform.startswith("linux"):
            return Availability(False, "desktop portals exist on Linux only")
        if importlib.util.find_spec("dbus_fast") is None:
            return Availability(False, "python package 'dbus_fast' not installed (uv sync --extra desktop)")
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return Availability(False, "no D-Bus session (not running inside a desktop session?)")
        try:
            version = _run_coro(_portal_version(), timeout=3.0)
        except Exception as e:
            return Availability(False, f"cannot reach the desktop portal ({type(e).__name__})")
        if not version:
            return Availability(False, "this desktop's portal has no GlobalShortcuts support")
        return Availability(True)

    def describe(self) -> str:
        return ("Registered with your desktop. Change the keys in your system settings "
                "(KDE: System Settings → Keyboard → Shortcuts → speakcheck).")  # fmt: skip

    def start(self, bindings: dict[str, str], fire: Callable[[str], None]) -> None:
        """Blocks until the desktop accepted the shortcuts (it may show a dialog first)."""
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        ready = threading.Event()
        error: dict[str, BaseException] = {}

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop

            async def setup():
                self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
                self._session = PortalSession(self._bus, fire)
                await self._session.setup(bindings, self.settings.app_id)

            try:
                loop.run_until_complete(setup())
            except BaseException as e:  # noqa: BLE001
                error["e"] = e
                ready.set()
                loop.close()
                return
            ready.set()
            loop.run_forever()
            loop.close()

        threading.Thread(target=run, name="portal-shortcuts", daemon=True).start()
        ready.wait()
        if "e" in error:
            raise SpeakcheckError(f"Could not register shortcuts with the desktop portal: {error['e']}")

    def stop(self) -> None:
        loop, session, bus = self._loop, self._session, self._bus
        if loop is None:
            return

        async def shutdown():
            if session:
                await session.close()
            if bus:
                bus.disconnect()

        asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        self._loop = self._session = self._bus = None

    def close(self) -> None:
        self.stop()
