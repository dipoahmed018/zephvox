"""The server running inside the app ("Share this computer"), using the app's own engine.

The models the app already loaded serve other devices too, instead of a second copy in another process.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

from ..engine.engine import Engine
from ..engine.errors import ZephvoxError


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network (best effort, nothing is sent)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # TEST-NET address: picks the outgoing interface, sends nothing
            found.append(s.getsockname()[0])
    except OSError:
        pass
    return [a for a in found if not a.startswith("127.")]


class EmbeddedServer:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.server: Any = None
        self._uvicorn: Any = None
        self._thread: threading.Thread | None = None
        self.host: str | None = None
        self.port: int | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, host: str, port: int, timeout: float = 10.0) -> None:
        import uvicorn

        from ..web.server import port_free
        from .app import create_server_app
        from .service import Server

        if self.running:
            return
        if not port_free(host, port):
            raise ZephvoxError(f"Port {port} is already in use (is the server already running as a service?)")
        self.error = None
        self.server = Server(self.engine, owns_engine=False)
        config = uvicorn.Config(create_server_app(self.server), host=host, port=port, log_level="warning")
        self._uvicorn = uvicorn.Server(config)
        self.host, self.port = host, port

        def run() -> None:
            try:
                self._uvicorn.run()
            except BaseException as e:  # noqa: BLE001 - shown in the page
                self.error = str(e) or type(e).__name__

        self._thread = threading.Thread(target=run, name="sharing", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._uvicorn.started and self._thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self._uvicorn.started:
            self.stop()
            raise ZephvoxError(f"The server didn't start: {self.error or 'timed out'}")

    def stop(self) -> None:
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        if self.server is not None:
            self.server.close()
        self.server = self._uvicorn = self._thread = None

    def info(self) -> dict[str, Any]:
        urls = []
        if self.running and self.port:
            hosts = lan_addresses() if self.host in ("0.0.0.0", "::") else [self.host]
            urls = [f"http://{h}:{self.port}" for h in ([*hosts, "127.0.0.1"] if self.host in ("0.0.0.0", "::") else hosts)]
        return {"running": self.running, "host": self.host, "port": self.port, "urls": urls, "error": self.error}
