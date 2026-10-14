"""`speakcheck serve`: run the daemon + web page until Ctrl+C."""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser

from ..engine.engine import Engine
from ..engine.errors import SpeakcheckError
from .client import daemon_at, find_daemon, remove_daemon_file, write_daemon_file


def serve(engine: Engine, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False,
          shortcuts: bool = True) -> None:  # fmt: skip
    try:
        import uvicorn

        from .app import create_app
        from .daemon import Daemon
    except ImportError as e:
        raise SpeakcheckError(f"The web GUI needs extra packages: uv sync --extra web ({e.name} missing)") from e

    local = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{local}:{port}"
    data_dir = engine.config.engine.data_dir

    # Already running (e.g. the app launcher clicked again): show that one. Starting a second daemon
    # would register the shortcuts again, and its exit would switch them off for the first one too.
    running = find_daemon(data_dir) or (url if daemon_at(url) else None)
    if running:
        print(f"speakcheck is already running at {running}", file=sys.stderr)
        if open_browser:
            webbrowser.open(running)
        return
    if not port_free(host, port):
        raise SpeakcheckError(f"Port {port} is already in use by another program. "
                              f"Start speakcheck on another one with --port.")  # fmt: skip

    daemon = Daemon(engine, start_triggers=shortcuts)
    app = create_app(daemon)
    write_daemon_file(data_dir, url)
    print(f"speakcheck is running at {url}  (Ctrl+C to stop)", file=sys.stderr)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        daemon.close()
        remove_daemon_file(data_dir)


def port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True
