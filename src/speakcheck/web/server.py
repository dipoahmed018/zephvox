"""`speakcheck serve`: run the daemon + web page until Ctrl+C."""

from __future__ import annotations

import sys
import threading
import webbrowser

from ..engine.engine import Engine
from ..engine.errors import SpeakcheckError
from .client import remove_daemon_file, write_daemon_file


def serve(engine: Engine, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False,
          shortcuts: bool = True) -> None:  # fmt: skip
    try:
        import uvicorn

        from .app import create_app
        from .daemon import Daemon
    except ImportError as e:
        raise SpeakcheckError(f"The web GUI needs extra packages: uv sync --extra web ({e.name} missing)") from e

    daemon = Daemon(engine, start_triggers=shortcuts)
    app = create_app(daemon)
    local = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{local}:{port}"
    data_dir = engine.config.engine.data_dir
    write_daemon_file(data_dir, url)
    print(f"speakcheck is running at {url}  (Ctrl+C to stop)", file=sys.stderr)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        daemon.close()
        remove_daemon_file(data_dir)
