"""Daemon, HTTP API, daemon client and daemon-aware CLI."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from speakcheck import cli
from speakcheck.engine.errors import SpeakcheckError
from speakcheck.engine.models import Finding
from speakcheck.providers.base import Availability, TriggerProvider, TTSProvider
from speakcheck.web import client as web_client
from speakcheck.web import server as web_server
from speakcheck.web.app import create_app
from speakcheck.web.daemon import Daemon, EventHub, jsonable
from tests.conftest import FakeLLM


class FakeTTS(TTSProvider):
    name = "fake-tts"
    calls = 0

    def synthesize(self, text):
        type(self).calls += 1
        if text == "boom":
            raise SpeakcheckError("synth failed")
        return b"RIFF" + text.encode()


class FakeTriggers(TriggerProvider):
    name = "fake-triggers"
    instance = None

    def start(self, bindings, fire):
        self.bindings, self.fire_cb, self.stopped = bindings, fire, False
        FakeTriggers.instance = self

    def stop(self):
        self.stopped = True

    def describe(self):
        return "rebind in config"


class ClosingLLM(FakeLLM):
    name = "closing-llm"
    closed = 0

    def close(self):
        type(self).closed += 1


@pytest.fixture
def daemon(engine, registry):
    registry.register("tts", "fake-tts", FakeTTS)
    registry.register("triggers", "fake-triggers", FakeTriggers)
    registry.register("llm", "closing-llm", ClosingLLM)
    engine.config.providers.update({"tts": ["fake-tts"], "triggers": ["fake-triggers"], "llm": ["closing-llm"]})
    ClosingLLM.closed = 0
    d = Daemon(engine, start_triggers=False)
    events = []
    engine.events.subscribe(events.append)
    d.recorded = events
    original = d.hub.publish
    d.published = []

    def publish(type, data):
        d.published.append((type, data))
        original(type, data)

    d.hub.publish = publish
    yield d
    d.close()


@pytest.fixture
def api(daemon):
    return TestClient(create_app(daemon))


def wait_for_jobs(daemon):
    daemon._worker.submit(lambda: None).result(timeout=10)


def published(daemon, type):
    return [data for t, data in daemon.published if t == type]


class TestDaemonActions:
    def test_record_stop_runs_analysis_and_releases_llm(self, daemon):
        daemon.start(analyzers=["grammar"])
        rec = daemon.stop()
        wait_for_jobs(daemon)
        session = daemon.engine.sessions.get(rec.session_id)
        result = daemon.engine.sessions.load_result(session)
        assert result.analyzers == ["grammar"] and result.by_analyzer("grammar")
        assert ClosingLLM.closed == 1 and "llm" not in daemon.engine._providers
        assert published(daemon, "analysis_done") == [{"session_id": rec.session_id}]
        assert [t for t, _ in daemon.published if t.startswith("job_")] == ["job_started", "job_finished"]

    def test_practice_needs_target_then_scores(self, daemon):
        with pytest.raises(SpeakcheckError, match="Pick a word"):
            daemon.start(mode="practice")
        daemon.set_practice_target("think", session_id="s1")
        assert published(daemon, "practice_target")[-1] == {"target": {"text": "think", "session_id": "s1"}}
        daemon.toggle(mode="practice")
        daemon.toggle(mode="practice")
        wait_for_jobs(daemon)
        attempt = published(daemon, "practice_result")[0]["attempt"]
        assert attempt["target"] == "think" and attempt["source_session"] == "s1"
        daemon.set_practice_target(None)
        assert daemon.practice_target is None

    def test_toggle_never_crosses_modes(self, daemon):
        daemon.set_practice_target("think")
        daemon.toggle("analysis")
        with pytest.raises(SpeakcheckError, match="analysis recording is in progress"):
            daemon.toggle("practice")
        assert daemon.engine.is_recording()
        daemon.cancel()

    def test_fire_actions_and_errors(self, daemon):
        daemon.fire("toggle_recording")
        assert daemon.engine.is_recording()
        daemon.fire("cancel")
        assert not daemon.engine.is_recording()
        daemon.fire("cancel")  # nothing to cancel: quietly ignored
        daemon.fire("practice_attempt")  # no target
        daemon.fire("self_destruct")
        errors = published(daemon, "action_error")
        assert [e["action"] for e in errors] == ["practice_attempt", "self_destruct"]

    def test_job_errors_are_published(self, daemon):
        def boom():
            raise SpeakcheckError("model exploded")

        def crash():
            raise ValueError("bug")

        for fn in (boom, crash):
            with pytest.raises(Exception):
                daemon._submit("x", fn).result(timeout=5)
        assert [e["message"] for e in published(daemon, "job_error")] == ["model exploded", "ValueError: bug"]
        assert not daemon.busy

    def test_settings_update_switches_device(self, daemon):
        daemon.engine.provider("capture")
        out = daemon.update_settings({"capture": {"provider": "fake-capture", "device": "mic-2"}, "bogus": 1})
        assert out["capture"] == {"provider": "fake-capture", "device": "mic-2"}
        assert "capture" not in daemon.engine._providers  # rebuilt with the new device next time
        assert daemon.engine.config.provider_settings("fake-capture") == {"device": "mic-2"}
        daemon.update_settings({"analyzers": ["pronunciation"]})
        assert daemon.settings()["analyzers"] == ["pronunciation"]

    def test_triggers_started_and_dispatched(self, daemon):
        daemon._start_triggers()
        trig = FakeTriggers.instance
        assert trig.bindings["toggle_recording"] == "Ctrl+Shift+Alt+R"
        assert daemon.triggers["active"] and daemon.triggers["description"] == "rebind in config"
        trig.fire_cb("toggle_recording")
        assert daemon.engine.is_recording()
        daemon.fire("cancel")
        assert daemon.status()["triggers"]["driver"] == "fake-triggers"

    def test_triggers_unavailable(self, daemon):
        daemon.engine.config.providers["triggers"] = []
        daemon._start_triggers()
        assert not daemon.triggers["active"] and "No usable triggers" in daemon.triggers["error"]

    def test_close_cancels_recording_and_stops_triggers(self, engine, registry):
        registry.register("triggers", "fake-triggers", FakeTriggers)
        engine.config.providers["triggers"] = ["fake-triggers"]
        d = Daemon(engine, start_triggers=False)
        d._start_triggers()
        d.start()
        d.close()
        assert not engine.is_recording() and FakeTriggers.instance.stopped


def stop_real_ticker(daemon):
    daemon._stop.set()
    daemon._ticker.join(timeout=5)


def fake_stop(*waits):
    it = iter(waits)
    return SimpleNamespace(wait=lambda t: next(it), set=lambda: None)


class TestTicker:
    def run_ticks(self, daemon, statuses, monkeypatch):
        stop_real_ticker(daemon)
        seq = iter(statuses)
        monkeypatch.setattr(daemon.engine, "recording_status", lambda: next(seq, None))
        stops = []
        monkeypatch.setattr(daemon, "stop", lambda: stops.append(True))
        clock = iter(range(0, 1000))
        monkeypatch.setattr("speakcheck.web.daemon.time.monotonic", lambda: next(clock))
        daemon._stop = fake_stop(*([False] * len(statuses) + [True]))
        daemon._tick()
        return stops

    def status(self, level, elapsed=1.0, mode="practice"):
        return {"level": level, "elapsed": elapsed, "mode": mode}

    def test_auto_stop_after_speech_then_silence(self, daemon, monkeypatch):
        statuses = [self.status(0.1), self.status(0.7), self.status(0.1), self.status(0.1), self.status(0.1)]
        assert self.run_ticks(daemon, statuses, monkeypatch) == [True]
        assert len(published(daemon, "level")) == 5

    def test_no_stop_without_speech_or_in_analysis_mode(self, daemon, monkeypatch):
        statuses = [self.status(0.1)] * 3 + [self.status(0.9, mode="analysis"), None]
        assert self.run_ticks(daemon, statuses, monkeypatch) == []

    def test_max_duration_and_stop_errors(self, daemon, monkeypatch):
        monkeypatch.setattr(daemon, "publish", lambda type, **d: daemon.published.append((type, d)))
        assert self.run_ticks(daemon, [self.status(0.1, elapsed=99)], monkeypatch) == [True]

        def failing_status():
            raise OSError("state file vanished")

        monkeypatch.setattr(daemon.engine, "recording_status", failing_status)
        daemon._stop = fake_stop(False, True)
        daemon._tick()  # survives

    def test_auto_stop_error_is_published(self, daemon, monkeypatch):
        stop_real_ticker(daemon)
        seq = iter([self.status(0.1, elapsed=99)])
        monkeypatch.setattr(daemon.engine, "recording_status", lambda: next(seq, None))

        def failing_stop():
            raise SpeakcheckError("mic unplugged")

        monkeypatch.setattr(daemon, "stop", failing_stop)
        daemon._stop = fake_stop(False, True)
        daemon._tick()
        assert published(daemon, "action_error")[0]["message"] == "mic unplugged"


class TestEventHub:
    def test_fan_out_overflow_and_dead_loops(self):
        async def main():
            hub = EventHub()
            q1 = hub.subscribe(asyncio.get_running_loop())
            hub.publish("level", {"level": 0.5, "finding": Finding("g", "s", "t", "a", "b", "e", "c")})
            await asyncio.sleep(0)
            msg = json.loads(q1.get_nowait())
            assert msg["type"] == "level" and msg["data"]["finding"]["target"] == "t"
            for i in range(600):  # overflow drops the oldest
                hub._put(q1, str(i))
            assert q1.qsize() == 500 and q1.get_nowait() == "100"
            hub.unsubscribe(q1)
            return hub

        hub = asyncio.run(main())
        dead_loop = asyncio.new_event_loop()
        dead_loop.close()
        hub.subscribe(dead_loop)
        hub.publish("x", {})  # closed loop → subscriber dropped
        assert hub._subscribers == []

    def test_jsonable(self, tmp_path):
        assert jsonable({"p": tmp_path, "t": (1, 2), 3: [tmp_path]}) == {"p": str(tmp_path), "t": [1, 2],
                                                                         "3": [str(tmp_path)]}  # fmt: skip


class TestAPI:
    def test_status_settings_devices(self, api):
        status = api.get("/api/status").json()
        assert status["busy"] is False and status["recording"] is None
        assert "fake-stt" in {p["name"] for p in status["doctor"]["providers"]}
        assert api.get("/api/settings").json()["shortcuts"]["cancel"] == "Ctrl+Shift+Alt+X"
        devices = api.get("/api/devices").json()
        assert devices["provider"] == "fake-capture" and devices["devices"][0]["is_default"] is True
        out = api.put("/api/settings", json={"analyzers": ["grammar"]}).json()
        assert out["analyzers"] == ["grammar"]

    def test_recording_endpoints(self, api, daemon):
        rec = api.post("/api/record/start", json={"mode": "analysis"}).json()
        assert rec["mode"] == "analysis"
        assert api.post("/api/record/start", json={}).status_code == 409
        assert api.get("/api/status").json()["recording"]["level"] == 0.25
        api.post("/api/record/cancel")
        assert api.post("/api/record/stop").status_code == 409
        api.post("/api/record/toggle", json={"analyzers": ["pronunciation"]})
        api.post("/api/record/toggle", json={})
        wait_for_jobs(daemon)
        sessions = api.get("/api/sessions").json()
        assert len(sessions) == 1 and sessions[0]["counts"] == {"pronunciation": 1}

    def test_sessions_detail_audio_feedback_delete(self, api, daemon, wav_file):
        result = daemon.engine.analyze(wav_file)
        sid = result.session_id
        daemon.engine.sessions.create()  # unanalyzed session: hidden from the list, 404 in detail
        listed = api.get("/api/sessions").json()
        assert [s["id"] for s in listed] == [sid] and listed[0]["preview"].startswith("I think")
        detail = api.get(f"/api/sessions/{sid}").json()
        assert len(detail["result"]["findings"]) == 2 and detail["feedback"] == {}
        clip = api.get(f"/api/sessions/{sid}/audio", params={"start": 0.2, "end": 0.6})
        assert clip.headers["content-type"] == "audio/wav" and len(clip.content) == 44 + int(0.7 * 16000) * 2
        assert len(api.get(f"/api/sessions/{sid}/audio").content) == 44 + 3 * 16000 * 2
        assert api.post(f"/api/sessions/{sid}/findings/0/feedback", json={}).json() == {"0": "dismissed"}
        assert api.get("/api/sessions").json()[0]["counts"] == {"grammar": 1}
        assert api.post(f"/api/sessions/{sid}/findings/9/feedback", json={}).status_code == 404
        assert api.get("/api/history").json()["dismissed"] == 1
        unanalyzed = [s.id for s in daemon.engine.sessions.list() if s.id != sid][0]
        assert api.get(f"/api/sessions/{unanalyzed}").status_code == 404
        assert api.get("/api/sessions/nope").status_code == 404
        assert api.delete(f"/api/sessions/{sid}").json() == {"deleted": sid}
        assert api.get(f"/api/sessions/{sid}").status_code == 404

    def test_upload_analysis(self, api, daemon, wav_file):
        resp = api.post("/api/analyze", files={"file": ("talk.wav", wav_file.read_bytes())},
                        data={"analyzers": "grammar"})  # fmt: skip
        assert resp.json() == {"queued": True}
        wait_for_jobs(daemon)
        assert published(daemon, "analysis_done")

    def test_practice_endpoints(self, api, daemon):
        assert api.put("/api/practice/target", json={"text": "think"}).json()["target"]["text"] == "think"
        assert api.get("/api/practice/attempts/latest/audio", params={"target": "think"}).status_code == 404
        api.post("/api/record/toggle", json={"mode": "practice"})
        api.post("/api/record/toggle", json={"mode": "practice"})
        wait_for_jobs(daemon)
        stats = api.get("/api/practice/stats", params={"target": "think"}).json()
        assert stats["attempts"] == 1
        latest = api.get("/api/practice/attempts/latest/audio", params={"target": "think"})
        assert latest.status_code == 200 and latest.content[:4] == b"RIFF"
        assert api.get("/api/practice/weak").json() == []

    def test_tts(self, api, daemon):
        FakeTTS.calls = 0
        assert api.get("/api/tts", params={"text": "think"}).content == b"RIFFthink"
        api.get("/api/tts", params={"text": "think"})
        assert FakeTTS.calls == 1  # cached
        assert api.get("/api/tts", params={"text": " "}).status_code == 400
        assert api.get("/api/tts", params={"text": "boom"}).status_code == 502
        daemon.engine.release("tts")
        daemon.engine.config.providers["tts"] = []
        assert api.get("/api/tts", params={"text": "other"}).status_code == 404

    def test_events_stream(self, daemon):
        app = create_app(daemon)
        endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/events")

        async def main():
            checks = iter([False, False, True])

            class FakeRequest:
                async def is_disconnected(self):
                    return next(checks)

            response = await endpoint(FakeRequest())
            chunks = []
            daemon.publish("hello", n=1)
            async for chunk in response.body_iterator:
                chunks.append(chunk)
                if len(chunks) == 1:
                    daemon.publish("hello", n=1)
            return chunks

        chunks = asyncio.run(main())
        assert chunks[0] == "retry: 2000\n\n"
        assert json.loads(chunks[1].removeprefix("data: "))["type"] == "hello"
        assert daemon.hub._subscribers == []

    def test_events_keepalive(self, daemon, monkeypatch):
        monkeypatch.setattr("speakcheck.web.app.KEEPALIVE_S", 0.01)
        app = create_app(daemon)
        endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/events")

        async def main():
            checks = iter([False, True])

            class FakeRequest:
                async def is_disconnected(self):
                    return next(checks)

            response = await endpoint(FakeRequest())
            return [c async for c in response.body_iterator]

        assert asyncio.run(main())[1] == ": keepalive\n\n"

    def test_frontend_or_placeholder(self, daemon, monkeypatch, tmp_path):
        monkeypatch.setattr("speakcheck.web.app.STATIC_DIR", tmp_path)
        assert "hasn't been built" in TestClient(create_app(daemon)).get("/").text
        (tmp_path / "index.html").write_text("<h1>speakcheck app</h1>")
        assert "speakcheck app" in TestClient(create_app(daemon)).get("/").text


URL = "http://127.0.0.1:8765"


class TestClientAndCLI:
    def test_daemon_file_and_discovery(self, tmp_path):
        assert web_client.find_daemon(tmp_path) is None
        web_client.write_daemon_file(tmp_path, URL)
        with respx.mock:
            respx.get(f"{URL}/api/settings").respond(json={})
            assert web_client.find_daemon(tmp_path) == URL
            respx.get(f"{URL}/api/settings").mock(side_effect=httpx.ConnectError("down"))
            assert web_client.find_daemon(tmp_path) is None
        web_client.remove_daemon_file(tmp_path)
        assert not web_client.daemon_file(tmp_path).exists()

    @respx.mock
    def test_call_errors(self):
        respx.post(f"{URL}/api/x").respond(409, json={"detail": "Already recording"})
        with pytest.raises(web_client.DaemonError, match="Already recording"):
            web_client.call(URL, "POST", "/api/x")
        respx.post(f"{URL}/api/y").respond(500, text="oops")
        with pytest.raises(web_client.DaemonError, match="oops"):
            web_client.call(URL, "POST", "/api/y")

    @pytest.fixture
    def run(self, engine, capsys, monkeypatch):
        def go(*argv, daemon_url=URL, ask=lambda p: ""):
            monkeypatch.setattr(cli, "find_daemon", lambda data_dir: daemon_url)
            code = cli.main(list(argv), engine_factory=lambda c: engine, ask=ask)
            out = capsys.readouterr()
            return code, out.out, out.err

        return go

    @respx.mock
    def test_commands_route_to_daemon(self, run):
        status = respx.get(f"{URL}/api/status").respond(json={"recording": None})
        toggle = respx.post(f"{URL}/api/record/toggle").respond(json={})
        start = respx.post(f"{URL}/api/record/start").respond(json={})
        stop = respx.post(f"{URL}/api/record/stop").respond(json={})
        assert run("toggle", "-q")[1].startswith("Recording")
        status.respond(json={"recording": {"mode": "analysis"}})
        assert run("practice", "-q")[1].startswith("Stopped")
        assert json.loads(toggle.calls.last.request.content) == {"mode": "practice"}
        assert "Run `speakcheck stop`" in run("start", "-q")[1]
        assert "report will appear" in run("stop", "-q")[1]
        assert "report will appear" in run("record", "--analyzers", "grammar", "-q")[1]
        assert json.loads(start.calls.last.request.content)["analyzers"] == ["grammar"]
        assert stop.call_count == 2
        stop.respond(409, json={"detail": "Not recording"})
        code, _, err = run("stop", "-q")
        assert code == 2 and "Not recording" in err

    def test_standalone_toggle_and_practice(self, run, engine):
        code, out, _ = run("toggle", "-q", daemon_url=None)
        assert code == 0 and "Run `speakcheck toggle` again" in out and engine.is_recording()
        code, out, _ = run("toggle", "-q", daemon_url=None)
        assert code == 0 and "Pronunciation (1)" in out and not engine.is_recording()
        code, _, err = run("practice", daemon_url=None)
        assert code == 2 and "needs the daemon" in err

    def test_serve_command(self, run, monkeypatch):
        seen = {}
        monkeypatch.setattr(web_server, "serve", lambda engine, host, port, open_, shortcuts: seen.update(
            host=host, port=port, open=open_, shortcuts=shortcuts))  # fmt: skip
        assert run("serve", "--port", "9000", "--open", "--no-shortcuts", "-q", daemon_url=None)[0] == 0
        assert seen == {"host": "127.0.0.1", "port": 9000, "open": True, "shortcuts": False}

    def test_server_lifecycle(self, engine, registry, monkeypatch):
        registry.register("triggers", "fake-triggers", FakeTriggers)
        engine.config.providers["triggers"] = ["fake-triggers"]
        ran, opened = {}, []

        def fake_run(app, host, port, log_level):
            ran.update(host=host, port=port)
            assert web_client.daemon_file(engine.config.engine.data_dir).exists()

        import uvicorn

        monkeypatch.setattr(uvicorn, "run", fake_run)
        monkeypatch.setattr(web_server.threading, "Timer", lambda d, fn, args: SimpleNamespace(
            start=lambda: opened.append(args[0])))  # fmt: skip
        web_server.serve(engine, host="0.0.0.0", port=9001, open_browser=True, shortcuts=False)
        assert ran == {"host": "0.0.0.0", "port": 9001} and opened == ["http://127.0.0.1:9001"]
        assert not web_client.daemon_file(engine.config.engine.data_dir).exists()


def test_availability_helper_type():
    assert Availability(True).ok


class VoicedTTS(FakeTTS):
    name = "voiced-tts"

    class Settings(FakeTTS.Settings):
        voice: str = "v1"

    def capabilities(self):
        return {"voice": self.settings.voice, "voices": [{"id": "v1", "label": "One"}, {"id": "v2", "label": "Two"}]}

    def synthesize(self, text):
        return f"RIFF{self.settings.voice}:{text}".encode()


def test_voice_choice_changes_tts_audio(daemon, registry):
    registry.register("tts", "voiced-tts", VoicedTTS)
    daemon.engine.config.providers["tts"] = ["voiced-tts"]
    daemon.engine.release("tts")
    api = TestClient(create_app(daemon))
    assert api.get("/api/voices").json() == {"provider": "voiced-tts", "selected": "v1",
                                             "voices": [{"id": "v1", "label": "One"}, {"id": "v2", "label": "Two"}]}  # fmt: skip
    assert api.get("/api/tts", params={"text": "hi"}).content == b"RIFFv1:hi"
    assert api.put("/api/settings", json={"tts": {"provider": "voiced-tts", "voice": "v2"}}).json()["tts"]["voice"] == "v2"
    assert api.get("/api/tts", params={"text": "hi"}).content == b"RIFFv2:hi"  # not the cached v1 audio
    api.put("/api/settings", json={"tts": {"provider": "voiced-tts", "voice": None}})
    assert api.get("/api/voices").json()["selected"] == "v1"  # cleared → driver default
    daemon.engine.config.providers["tts"] = []
    daemon.engine.release("tts")
    assert api.get("/api/voices").status_code == 409


def test_reanalyze_session_in_place(api, daemon, wav_file):
    first = daemon.engine.analyze(wav_file, analyzers=["grammar"])
    assert api.post(f"/api/sessions/{first.session_id}/analyze", json={"analyzers": ["pronunciation"]}).json() == {
        "queued": True}  # fmt: skip
    wait_for_jobs(daemon)
    result = daemon.engine.sessions.load_result(daemon.engine.sessions.get(first.session_id))
    assert result.analyzers == ["pronunciation"] and len(daemon.engine.sessions.list()) == 1
    assert api.post("/api/sessions/nope/analyze", json={}).status_code == 404


class TestProfilesApi:
    @pytest.fixture
    def setup(self, daemon, tmp_path, monkeypatch):
        from speakcheck.engine.hardware import GPU, Hardware
        from speakcheck.web import daemon as daemon_mod

        path = tmp_path / "config.toml"
        path.write_text(f'[engine]\ndata_dir = "{tmp_path / "data"}"\n')
        daemon.engine.config.source = path
        daemon.__dict__["hardware"] = Hardware("linux", "x86_64", "CPU", 8, 32.0, 100.0,
                                               [GPU("nvidia", "RTX", 12.0, "cuda")])  # fmt: skip
        monkeypatch.setattr(daemon_mod, "project_root", lambda: None)
        return path

    def test_list_and_switch(self, api, daemon, setup):
        info = api.get("/api/profiles").json()
        assert info["current"] is None and info["recommended"] == "standard"
        assert [p["name"] for p in info["profiles"]] == ["large", "standard", "small", "cpu", "cpu-light"]
        assert info["config_path"] == str(setup)
        resp = api.put("/api/profile", json={"name": "small"})
        assert resp.status_code == 200 and resp.json()["current"] == "small"
        assert 'profile = "small"' in setup.read_text()
        assert daemon.engine.config.provider_settings("openai-compat")["model"] == "qwen3:4b"
        assert any(t == "settings_changed" for t, _ in daemon.published)

    def test_unknown_profile_and_busy(self, api, daemon, setup, monkeypatch):
        assert api.put("/api/profile", json={"name": "huge"}).status_code == 409
        monkeypatch.setattr(type(daemon), "busy", property(lambda self: True))
        resp = api.put("/api/profile", json={"name": "cpu"})
        assert resp.status_code == 409 and "finish" in resp.json()["detail"]

    def test_cpu_install_needs_setup_for_a_gpu_profile(self, api, daemon, setup, monkeypatch, tmp_path):
        from speakcheck.install.state import InstallState
        from speakcheck.web import daemon as daemon_mod

        InstallState("cpu", ["models", "cpu"]).save(tmp_path)
        monkeypatch.setattr(daemon_mod, "project_root", lambda: tmp_path)
        needs = api.put("/api/profile", json={"name": "large"}).json()["needs"]
        assert any("setup --profile large" in n for n in needs)
        needs = api.put("/api/profile", json={"name": "cpu"}).json()["needs"]
        assert not any("PyTorch" in n for n in needs)
