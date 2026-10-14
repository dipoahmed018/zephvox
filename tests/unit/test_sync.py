"""History sync between two devices of one account, and the offline queue (in-process server)."""

import json

import pytest

from speakcheck.client import credentials
from speakcheck.client.backend import RemoteBackend
from speakcheck.client.remote import QueuedOffline, ServerClient, ServerUnreachable
from speakcheck.client.sync import PENDING_FILE, SyncState, SyncWorker, pending
from speakcheck.engine.config import Config, EngineSettings, RemoteSettings
from speakcheck.engine.engine import Engine
from speakcheck.engine.practice import PracticeAttempt
from speakcheck.web.daemon import Daemon
from tests.unit.test_client_remote import URL, remote  # noqa: F401  (fixture)


def device(name, remote, engine, tmp_path):
    """A second computer on alice's account: its own data folder and key."""
    data = tmp_path / name
    config = Config(engine=EngineSettings(data_dir=data), providers=dict(engine.config.providers),
                    remote=RemoteSettings(mode="remote", url=URL, sync=True))  # fmt: skip
    dev = Engine(config, registry=engine.registry, caps=engine.caps)
    client = ServerClient(URL)
    info = client.redeem(remote.invite(), name)
    credentials.save(data, credentials.Credentials(URL, info["key"], info["device"]["id"], name, "alice"))
    dev.worker = SyncWorker(dev, lambda: ServerClient(URL, key=info["key"]), history=True)
    dev.key = info["key"]
    return dev


@pytest.fixture
def two(remote, engine, tmp_path):  # noqa: F811
    return device("laptop", remote, engine, tmp_path), device("desktop", remote, engine, tmp_path)


class TestHistorySync:
    def test_sessions_feedback_and_deletes_reach_the_other_device(self, two, remote, wav_file):  # noqa: F811
        a, b = two
        made = a.analyze(wav_file, ["pronunciation"])
        assert a.worker.run_once()["pushed"] == 1
        assert remote.server.db.storage_bytes(remote.account.id) > 0
        assert b.worker.run_once()["pulled"] == 1
        copy = b.sessions.get(made.session_id)
        result = b.sessions.load_result(copy)
        assert result.findings[0].target == "think" and result.audio_path == str(copy.audio_path)
        assert copy.audio_path.read_bytes() == a.sessions.get(made.session_id).audio_path.read_bytes()
        assert b.worker.run_once() == {"analyzed": 0, "pushed": 0, "pulled": 0, "deleted": 0}  # settled

        b.sessions.set_feedback(copy, 0, "dismissed")
        assert b.worker.run_once()["pushed"] == 1
        assert a.worker.run_once()["pulled"] == 1
        assert a.sessions.load_feedback(a.sessions.get(made.session_id)) == {0: "dismissed"}

        a.sessions.delete(a.sessions.get(made.session_id))
        a.worker.run_once()
        assert b.worker.run_once()["deleted"] == 1
        assert not (b.sessions.root / made.session_id).exists()

    def test_practice_attempts_sync_once(self, two):
        a, b = two
        a.practice_store.add(PracticeAttempt("think", 80, False, at="2026-10-14T10:00:00", audio="/a/x.wav"))
        a.worker.run_once()
        b.worker.run_once()
        b.worker.run_once()
        a.worker.run_once()
        (got,) = b.practice_store.attempts("think")
        assert got.score == 80 and got.audio is None
        assert len(a.practice_store.attempts()) == 1

    def test_same_id_on_two_devices_is_renamed(self, two, wav_file):
        a, b = two
        sa = a.analyze(wav_file, ["pronunciation"]).session_id
        other = b.analyze(wav_file, ["pronunciation"]).session_id  # b's own recording...
        if other != sa:
            (b.sessions.root / other).rename(b.sessions.root / sa)  # ...that got the same id
        path = b.sessions.root / sa / "result.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, "session_id": sa, "created": "2001-01-01T00:00:00"}))
        a.worker.run_once()
        b.worker.run_once()  # the server says id_taken: b renames its own, and fetches a's
        renamed = [s.id for s in b.sessions.list() if s.id.startswith(sa + "-")]
        assert len(renamed) == 1 and b.sessions.load_result(b.sessions.get(sa)).created != "2001-01-01T00:00:00"
        b.worker.run_once()
        assert remote_has(b, renamed[0])

    def test_storage_limit(self, two, remote, wav_file):  # noqa: F811
        a, _ = two
        remote.server.db.set_account_limits(remote.account.id, {"storage_mb": 0})
        a.analyze(wav_file, ["pronunciation"])
        a.worker.run_once()
        assert a.worker.status["storage_full"]


def remote_has(dev, sid):
    client = ServerClient(URL, key=dev.key)
    return any(s["id"] == sid for s in client.sessions_since(0)["sessions"])


class TestServerSyncApi:
    def test_newer_versions_win(self, two, wav_file):
        a, b = two
        sid = a.analyze(wav_file, ["pronunciation"]).session_id
        client = ServerClient(URL, key=a.key)
        result = json.loads(a.sessions.get(sid).result_path.read_text())
        client.put_session(sid, 100.0, result, {})
        with pytest.raises(Exception, match="newer"):
            client.put_session(sid, 50.0, result, {})
        with pytest.raises(Exception, match="newer"):
            client.delete_session(sid, 50.0)
        client.delete_session(sid, 200.0)
        listed = {s["id"]: s for s in client.sessions_since(0)["sessions"]}
        assert listed[sid]["deleted"]


class TestOfflineQueue:
    def test_queued_then_analyzed_when_back(self, remote, engine, wav_file, tmp_path, monkeypatch):  # noqa: F811
        dev = device("tablet", remote, engine, tmp_path)
        backend = RemoteBackend(dev, ServerClient(URL, key=dev.key))
        real_submit = ServerClient.submit

        def offline(self, *a, **kw):
            raise ServerUnreachable("can't reach the server (ConnectError)")

        monkeypatch.setattr(ServerClient, "submit", offline)
        with pytest.raises(QueuedOffline, match="Saved"):
            backend.analyze(wav_file, ["pronunciation"])
        (session,) = dev.sessions.list()
        assert pending(session) == {"analyzers": ["pronunciation"], "since": pytest.approx(pending(session)["since"])}
        worker = SyncWorker(dev, lambda: ServerClient(URL, key=dev.key), history=False,
                            analyze_pending=lambda s, names: backend.analyze(s, names))  # fmt: skip
        worker.run_once()
        assert worker.status["offline"] and pending(session) is not None  # still down: kept
        monkeypatch.setattr(ServerClient, "submit", real_submit)
        assert worker.run_once()["analyzed"] == 1
        assert not (session.dir / PENDING_FILE).exists() and dev.sessions.load_result(session).findings

    def test_daemon_reports_and_lists_queued_recordings(self, remote, engine, monkeypatch):  # noqa: F811
        from fastapi.testclient import TestClient

        from speakcheck.web.app import create_app

        engine.config.providers["stt"] = []
        daemon = Daemon(engine, start_triggers=False)
        try:
            daemon.connect(URL, remote.invite(), "laptop")
            published = []
            original = daemon.hub.publish
            daemon.hub.publish = lambda type, data: (published.append((type, data)), original(type, data))
            monkeypatch.setattr(ServerClient, "submit", lambda self, *a, **kw: (_ for _ in ()).throw(
                ServerUnreachable("down")))  # fmt: skip
            daemon.start("analysis")
            daemon.stop()
            daemon._worker.submit(lambda: None).result(timeout=10)
            assert any(t == "warning" and d["message"].startswith("Saved") for t, d in published)
            listed = TestClient(create_app(daemon)).get("/api/sessions").json()
            assert listed[0]["pending"] and listed[0]["preview"] == "Waiting for the server…"
        finally:
            daemon.close()

    def test_sync_state_roundtrip(self, tmp_path):
        state = SyncState(cursor=5.0, known={"s": 1.0}, audio=["s"], attempts_pushed=2)
        state.save(tmp_path)
        assert SyncState.load(tmp_path) == state
        (tmp_path / "sync.json").write_text("junk")
        assert SyncState.load(tmp_path) == SyncState()
