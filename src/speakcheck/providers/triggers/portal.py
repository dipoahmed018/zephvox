"""Global shortcuts through the XDG desktop portal (Linux: KDE Plasma, GNOME 48+, Hyprland; Wayland or X11).

The desktop shows its own confirmation dialog the first time and lets the user rebind the keys in
its settings, so we only *suggest* key combos.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
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


# KDE stores shortcuts as Qt key codes: modifier bits plus the key.
_QT_MODS = {"SHIFT": 0x02000000, "CTRL": 0x04000000, "ALT": 0x08000000, "LOGO": 0x10000000}
_QT_KEYS = {"space": 0x20, "escape": 0x01000000, "tab": 0x01000001, "backspace": 0x01000003, "return": 0x01000004,
            "enter": 0x01000005, "insert": 0x01000006, "delete": 0x01000007, "home": 0x01000010, "end": 0x01000011,
            "left": 0x01000012, "up": 0x01000013, "right": 0x01000014, "down": 0x01000015,
            "pageup": 0x01000016, "pagedown": 0x01000017}  # fmt: skip
_QT_NAMES = {"SHIFT": "Shift", "CTRL": "Ctrl", "ALT": "Alt", "LOGO": "Super"}


def to_qt_key(combo: str) -> int:
    """"Ctrl+Shift+Alt+R" → the Qt key code KDE stores."""
    *mods, key = to_portal_trigger(combo).split("+")
    code = sum(_QT_MODS[m] for m in mods)
    k = key.lower()
    if len(key) == 1:
        return code + ord(key.upper())
    if k in _QT_KEYS:
        return code + _QT_KEYS[k]
    if k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 35:
        return code + 0x01000030 + int(k[1:]) - 1
    raise ValueError(f"Can't set {combo!r} on this desktop")


def from_qt_key(code: int) -> str | None:
    """A Qt key code back to "Ctrl+Shift+Alt+R" (None for keys we don't name)."""
    mods = [name for flag, name in ((_QT_MODS["CTRL"], "Ctrl"), (_QT_MODS["SHIFT"], "Shift"),
                                    (_QT_MODS["ALT"], "Alt"), (_QT_MODS["LOGO"], "Super")) if code & flag]  # fmt: skip
    key = code & 0x01FFFFFF
    if 0x20 < key < 0x7F:
        name = chr(key).upper()
    elif 0x01000030 <= key <= 0x01000052:
        name = f"F{key - 0x01000030 + 1}"
    else:
        name = next((n.capitalize() for n, v in _QT_KEYS.items() if v == key), None)
        if name is None:
            return None
    return "+".join([*mods, name])


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

    def _action_id(self, app_id: str, action: str) -> list[str]:
        return [app_id, action, "speakcheck", DESCRIPTIONS.get(action, action)]

    async def kde_bindings(self, app_id: str, actions: list[str]) -> dict[str, str] | None:
        """The keys KDE really uses for each action (they may have been changed in its settings)."""
        out: dict[str, str] = {}
        for action in actions:
            reply = await self.bus.call(self._Message(
                destination="org.kde.kglobalaccel", path="/kglobalaccel", interface="org.kde.KGlobalAccel",
                member="shortcut", signature="as", body=[self._action_id(app_id, action)]))  # fmt: skip
            if reply.message_type == self._MessageType.ERROR:
                return None
            keys = [k for k in reply.body[0] if k]
            if keys and (combo := from_qt_key(keys[0])):
                out[action] = combo
        return out

    async def set_kde_bindings(self, app_id: str, bindings: dict[str, str]) -> bool:
        """Set the keys in KDE directly (as its System Settings does). False when this isn't KDE."""
        for action, combo in bindings.items():
            reply = await self.bus.call(self._Message(
                destination="org.kde.kglobalaccel", path="/kglobalaccel", interface="org.kde.KGlobalAccel",
                member="setForeignShortcut", signature="asai",
                body=[self._action_id(app_id, action), [to_qt_key(combo)]]))  # fmt: skip
            if reply.message_type == self._MessageType.ERROR:
                return False
        return True

    async def active_on_kde(self, app_id: str) -> bool | None:
        """Whether KDE currently delivers this app's shortcuts; None when the desktop isn't KDE.

        KDE switches an app's shortcuts off when any of its portal sessions closes, including a
        stale one from an earlier run, so a session can look fine and never fire."""
        reply = await self.bus.call(self._Message(
            destination="org.kde.kglobalaccel", path="/component/" + re.sub(r"[^A-Za-z0-9_]", "_", app_id),
            interface="org.kde.kglobalaccel.Component", member="isActive"))  # fmt: skip
        if reply.message_type == self._MessageType.ERROR or not reply.body:
            return None
        return bool(reply.body[0])

    async def watch(self, bindings: dict[str, str], app_id: str, interval: float = 15.0,
                    on_rebind: Callable[[], None] | None = None) -> None:  # fmt: skip
        """Re-bind whenever KDE has switched the shortcuts off. Returns at once on other desktops."""
        while True:
            await asyncio.sleep(interval)
            try:
                active = await self.active_on_kde(app_id)
                if active is None:
                    return
                if not active:
                    await self.close()
                    await self.setup(bindings, app_id)
                    if on_rebind:
                        on_rebind()
            except (SpeakcheckError, TimeoutError):
                continue  # try again next round

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
        self._watch: asyncio.Task | None = None

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
            if self._session is not None:
                self._watch = loop.create_task(self._session.watch(bindings, self.settings.app_id, on_rebind=self._log_rebind))
            loop.run_forever()
            loop.close()

        threading.Thread(target=run, name="portal-shortcuts", daemon=True).start()
        ready.wait()
        if "e" in error:
            raise SpeakcheckError(f"Could not register shortcuts with the desktop portal: {error['e']}")

    def _call(self, coro_fn, timeout: float = 5.0):
        if self._loop is None or self._session is None:
            return None
        return asyncio.run_coroutine_threadsafe(coro_fn(self._session), self._loop).result(timeout=timeout)

    def current_bindings(self, actions: list[str]) -> dict[str, str] | None:
        """The keys the desktop really uses (KDE only), or None when it can't tell."""
        try:
            return self._call(lambda s: s.kde_bindings(self.settings.app_id, actions))
        except Exception:  # noqa: BLE001 - a status nicety
            return None

    def rebind(self, bindings: dict[str, str]) -> bool:
        """Change the keys in place. The portal only *suggests* keys when first registering, so on KDE
        they are set through its shortcut service; elsewhere this returns False (change them in the
        desktop's settings)."""
        try:
            return bool(self._call(lambda s: s.set_kde_bindings(self.settings.app_id, bindings)))
        except (ValueError, TimeoutError):
            return False

    @staticmethod
    def _log_rebind() -> None:
        print("· shortcuts were switched off by the desktop; registered them again", file=sys.stderr)

    def stop(self) -> None:
        loop, session, bus, watch = self._loop, self._session, self._bus, self._watch
        if loop is None:
            return

        async def shutdown():
            if watch:
                watch.cancel()
            if session:
                await session.close()
            if bus:
                bus.disconnect()

        asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        self._loop = self._session = self._bus = self._watch = None

    def close(self) -> None:
        self.stop()
