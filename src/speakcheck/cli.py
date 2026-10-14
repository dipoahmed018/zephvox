"""Thin developer CLI over the engine API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from .engine.config import Config, load_config
from .engine.engine import Engine
from .engine.errors import SpeakcheckError
from .engine.events import Event
from .engine.models import AnalysisResult
from .web.client import DaemonError, call, find_daemon

EngineFactory = Callable[[Config], Engine]


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="config file (default: ~/.config/speakcheck/config.toml)")
    common.add_argument("--set", action="append", default=[], metavar="KIND=NAME",
                        help="choose a provider, e.g. --set stt=faster-whisper (repeatable)")  # fmt: skip
    common.add_argument("-q", "--quiet", action="store_true", help="no progress output")

    analysis = argparse.ArgumentParser(add_help=False)
    analysis.add_argument("--analyzers", help="comma-separated, e.g. pronunciation,grammar")
    analysis.add_argument("--format", default="terminal", help="reporter: terminal, markdown, json")
    analysis.add_argument("-o", "--output", type=Path, help="also write the report to this file")

    p = argparse.ArgumentParser(prog="speakcheck", description="Find mistakes in your spoken English.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("record", parents=[common, analysis], help="record until Enter, then analyze")
    sub.add_parser("start", parents=[common], help="start recording in the background")
    sub.add_parser("stop", parents=[common, analysis], help="stop the background recording and analyze it")
    a = sub.add_parser("analyze", parents=[common, analysis], help="analyze an audio file")
    a.add_argument("file", type=Path)
    r = sub.add_parser("report", parents=[common, analysis], help="show a saved session's report")
    r.add_argument("session", nargs="?", help="session id (default: latest)")
    sub.add_parser("toggle", parents=[common], help="start, or stop and analyze (bind this to a shortcut)")
    sub.add_parser("practice", parents=[common], help="record a practice attempt for the word chosen in the page")
    s = sub.add_parser("serve", parents=[common], help="run the daemon + web page")
    s.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices on your network")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the page in your browser")
    s.add_argument("--no-shortcuts", action="store_true", help="don't register global shortcuts")
    sub.add_parser("providers", parents=[common], help="list providers and whether they can run here")
    sub.add_parser("doctor", parents=[common], help="system + plugin diagnostics as JSON")
    h = sub.add_parser("history", parents=[common], help="your most frequent mistakes")
    h.add_argument("--limit", type=int, default=10)
    return p


def _progress(event: Event) -> None:
    d = event.data
    if event.type == "stage_started":
        print(f"· {d['stage']} …", file=sys.stderr)
    elif event.type == "stage_finished" and "seconds" in d:
        print(f"  done in {d['seconds']:.1f}s", file=sys.stderr)
    elif event.type == "provider_selected":
        print(f"· using {d['kind']} provider: {d['name']}", file=sys.stderr)
    elif event.type == "provider_fallback":
        print(f"  ({d['kind']}: skipped {'; '.join(d['skipped'])})", file=sys.stderr)
    elif event.type == "recording_started":
        print(f"● recording ({d['mode']})", file=sys.stderr)


def _emit_report(engine: Engine, result: AnalysisResult, args: argparse.Namespace) -> None:
    reporter = engine.registry.get("reporters", args.format)()
    text = reporter.render(result)
    print(text, end="")
    if args.output:
        args.output.write_text(text)


def _analyzers(args: argparse.Namespace) -> list[str] | None:
    return [a.strip() for a in args.analyzers.split(",") if a.strip()] if args.analyzers else None


DAEMON_COMMANDS = {"start", "stop", "record", "toggle", "practice"}


def _via_daemon(url: str, args: argparse.Namespace, ask: Callable[[str], str]) -> int:
    """Recording commands are forwarded to a running daemon, which owns the microphone."""
    cmd = args.command
    analyzers = _analyzers(args) if getattr(args, "analyzers", None) else None
    try:
        if cmd in ("toggle", "practice"):
            was_recording = call(url, "GET", "/api/status")["recording"] is not None
            mode = "practice" if cmd == "practice" else "analysis"
            call(url, "POST", "/api/record/toggle", json={"mode": mode})
            print("Stopped; analyzing in speakcheck." if was_recording else "Recording… run it again to stop.")
        elif cmd == "start":
            call(url, "POST", "/api/record/start", json={"mode": "analysis", "analyzers": analyzers})
            print("Recording in the speakcheck daemon. Run `speakcheck stop` when done.")
        elif cmd == "stop":
            call(url, "POST", "/api/record/stop")
            print(f"Analyzing — the report will appear at {url}")
        elif cmd == "record":
            call(url, "POST", "/api/record/start", json={"mode": "analysis", "analyzers": analyzers})
            try:
                ask("Speak now. Press Enter to stop… ")
            finally:
                call(url, "POST", "/api/record/stop")
            print(f"Analyzing — the report will appear at {url}")
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def run(args: argparse.Namespace, engine: Engine, ask: Callable[[str], str]) -> int:
    cmd = args.command
    if cmd in DAEMON_COMMANDS:
        url = find_daemon(engine.config.engine.data_dir)
        if url:
            return _via_daemon(url, args, ask)
        if cmd == "practice":
            print("error: practice needs the daemon: run `speakcheck serve` and pick a word in the page",
                  file=sys.stderr)  # fmt: skip
            return 2
        if cmd == "toggle":
            if not engine.is_recording():
                recording = engine.start_recording()
                print(f"Recording into session {recording.session_id}. Run `speakcheck toggle` again to stop.")
                return 0
            cmd = "stop"
            args.analyzers, args.format, args.output = None, "terminal", None
    if cmd == "serve":
        from .web.server import serve

        serve(engine, args.host, args.port, args.open, shortcuts=not args.no_shortcuts)
    elif cmd == "record":
        engine.start_recording()
        try:
            ask("Speak now. Press Enter to stop… ")
        finally:
            recording = engine.stop_recording()
        _emit_report(engine, engine.analyze(recording, _analyzers(args)), args)
    elif cmd == "start":
        recording = engine.start_recording()
        print(f"Recording into session {recording.session_id}. Run `speakcheck stop` when done.")
    elif cmd == "stop":
        recording = engine.stop_recording()
        _emit_report(engine, engine.analyze(recording, _analyzers(args)), args)
    elif cmd == "analyze":
        _emit_report(engine, engine.analyze(args.file, _analyzers(args)), args)
    elif cmd == "report":
        sessions = engine.sessions.list()
        session = engine.sessions.get(args.session) if args.session else (sessions[-1] if sessions else None)
        result = engine.sessions.load_result(session) if session else None
        if result is None:
            print("No analyzed session found.", file=sys.stderr)
            return 1
        _emit_report(engine, result, args)
    elif cmd == "providers":
        for s in engine.list_providers():
            mark = "★" if s.selected else ("✓" if s.available else "✗")
            reason = f"  — {s.reason}" if s.reason else ""
            print(f"{mark} {s.kind:<9} {s.name:<16}{reason}")
        print("\n★ selected  ✓ available  ✗ unavailable")
    elif cmd == "doctor":
        print(json.dumps(engine.doctor(), indent=2, ensure_ascii=False))
    elif cmd == "history":
        h = engine.history(args.limit)
        print(f"{h['sessions']} analyzed session(s)")
        for analyzer, items in h["targets"].items():
            print(f"\n{analyzer.capitalize()} — most frequent:")
            for target, count in items:
                print(f"  {count:>3}× {target}")
            print("  by type: " + ", ".join(f"{c} ({n})" for c, n in h["categories"][analyzer]))
    return 0


def main(argv: list[str] | None = None, engine_factory: EngineFactory = Engine,
         ask: Callable[[str], str] = input) -> int:  # fmt: skip
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config).with_overrides(args.set)
        engine = engine_factory(config)
        if not args.quiet:
            engine.events.subscribe(_progress)
        try:
            return run(args, engine, ask)
        finally:
            engine.close()
    except SpeakcheckError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
