"""The server: accounts, keys, jobs, limits, webhooks, practice and the admin CLI (fake providers)."""

import io
import json

import httpx
import numpy as np
import pytest
import respx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from speakcheck import cli
from speakcheck.engine import audio
from speakcheck.engine.config import ServerSettings
from speakcheck.engine.errors import SpeakcheckError
from speakcheck.server import cli as server_cli
from speakcheck.server.app import create_server_app
from speakcheck.server.db import Job
from speakcheck.server.keys import hash_secret, verify
from speakcheck.server.service import Server
from speakcheck.server.webhooks import RETRY_DELAYS_S, SIGNATURE_HEADER, WebhookError, check_url
from tests.unit.test_web import FakeTTS

HOOK = "https://hooks.example.com/speakcheck"


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def server(engine, registry, tmp_path, clock):
    registry.register("tts", "fake-tts", FakeTTS)
    engine.config.providers["tts"] = ["fake-tts"]
    settings = ServerSettings(data_dir=tmp_path / "srv", webhook_allow_private=True)
    srv = Server(engine, settings, clock=clock, start=False, http=httpx.Client())
    yield srv
    srv.close()


@pytest.fixture
def api(server):
    return TestClient(create_server_app(server))


def connect(server, api, name="alice", device="laptop"):
    account = server.db.account(name) or server.db.add_account(name, server.clock())
    code = server.db.add_invite(account.id, server.clock(), 3600)
    r = api.post("/v1/devices/redeem", json={"invite": code, "device_name": device})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['key']}"}


def wav(seconds=3.0) -> bytes:
    buf = io.BytesIO()
    audio.write_wav(buf, np.zeros(int(16000 * seconds), dtype=np.float32))
    return buf.getvalue()


def upload(api, headers, seconds=3.0, **form):
    return api.post("/v1/jobs", headers=headers, files={"audio": ("talk.wav", wav(seconds), "audio/wav")}, data=form)


class TestAccountsAndKeys:
    def test_keys_are_stored_hashed_and_unique(self, server, api):
        headers = connect(server, api)
        key = headers["Authorization"].split()[1]
        dump = "\n".join(server.db._conn.iterdump())
        assert key not in dump and hash_secret(key) in dump
        other = connect(server, api, device="phone")
        assert other != headers

    def test_invite_works_once_and_expires(self, server, api, clock):
        account = server.db.add_account("bob", clock())
        code = server.db.add_invite(account.id, clock(), 60)
        assert api.post("/v1/devices/redeem", json={"invite": code}).status_code == 200
        assert api.post("/v1/devices/redeem", json={"invite": code}).status_code == 403
        late = server.db.add_invite(account.id, clock(), 60)
        clock.t += 61
        assert api.post("/v1/devices/redeem", json={"invite": late}).status_code == 403

    def test_auth_rotate_and_revoke(self, server, api):
        assert api.get("/v1/account").status_code == 401
        assert api.get("/v1/account", headers={"Authorization": "Bearer sk_nope"}).status_code == 401
        headers = connect(server, api)
        me = api.get("/v1/account", headers=headers).json()
        assert me["name"] == "alice" and me["device"]["current"] and me["webhook_secret"].startswith("whsec_")
        new = api.post("/v1/devices/me/rotate", headers=headers).json()["key"]
        assert api.get("/v1/account", headers=headers).status_code == 401  # old key dead at once
        headers = {"Authorization": f"Bearer {new}"}
        phone = connect(server, api, device="phone")
        devices = api.get("/v1/devices", headers=headers).json()
        assert {d["name"] for d in devices} == {"laptop", "phone"}
        phone_id = next(d["id"] for d in devices if d["name"] == "phone")
        assert api.delete(f"/v1/devices/{phone_id}", headers=headers).status_code == 200
        assert api.get("/v1/account", headers=phone).status_code == 401

    def test_accounts_are_isolated(self, server, api):
        alice, bob = connect(server, api), connect(server, api, "bob")
        job = upload(api, alice).json()["id"]
        assert api.get(f"/v1/jobs/{job}", headers=bob).status_code == 404
        assert api.delete(f"/v1/jobs/{job}", headers=bob).status_code == 404
        assert api.get("/v1/jobs", headers=bob).json() == []
        alice_device = api.get("/v1/devices", headers=alice).json()[0]["id"]
        assert api.delete(f"/v1/devices/{alice_device}", headers=bob).status_code == 404


class TestJobs:
    def test_lifecycle_progress_and_expiry(self, server, api, clock):
        headers = connect(server, api)
        r = upload(api, headers, analyzers="pronunciation")
        assert r.status_code == 202 and r.headers["location"] == f"/v1/jobs/{r.json()['id']}"
        job = r.json()
        assert job["status"] == "queued" and job["duration"] == 3.0 and job["analyzers"] == ["pronunciation"]
        server.jobs.run(server.jobs.next_job())
        done = api.get(f"/v1/jobs/{job['id']}", headers=headers).json()
        assert done["status"] == "done" and done["expires_at"]
        assert done["result"]["audio_path"] == "" and done["result"]["findings"][0]["target"] == "think"
        lines = [json.loads(line[6:]) for line in api.get(f"/v1/jobs/{job['id']}/events", headers=headers).text.splitlines()
                 if line.startswith("data: ")]  # fmt: skip
        types = [e["type"] for e in lines]
        assert "stage_started" in types and types[-1] == "job" and lines[-1]["data"]["status"] == "done"
        clock.t += 24 * 3600 + 1
        assert server.jobs.expire() == 1
        assert api.get(f"/v1/jobs/{job['id']}", headers=headers).status_code == 404
        assert not server.jobs.job_dir(job["id"]).exists()

    def test_failure_is_reported(self, server, api, engine):
        headers = connect(server, api)
        job = upload(api, headers).json()["id"]
        engine.config.providers["stt"] = []  # nothing can transcribe
        server.jobs.run(server.jobs.next_job())
        failed = api.get(f"/v1/jobs/{job}", headers=headers).json()
        assert failed["status"] == "failed" and "stt" in failed["error"] and "result" not in failed

    def test_idempotency_key(self, server, api):
        headers = {**connect(server, api), "Idempotency-Key": "upload-1"}
        first, second = upload(api, headers), upload(api, headers)
        assert first.json()["id"] == second.json()["id"] and second.status_code == 202
        assert len(server.db.jobs()) == 1 and server.jobs.queued() == 1

    def test_rejects_bad_input(self, server, api):
        headers = connect(server, api)
        assert upload(api, headers, analyzers="nonsense").status_code == 422
        assert upload(api, headers, webhook_url="ftp://x").status_code == 422
        bad = api.post("/v1/jobs", headers=headers, files={"audio": ("x.wav", b"not audio", "audio/wav")})
        assert bad.status_code == 422 and not list((server.root / "jobs").iterdir())
        assert api.post("/v1/jobs", files={"audio": ("x.wav", wav(), "audio/wav")}).status_code == 401

    def test_cancel_and_delete(self, server, api):
        headers = connect(server, api)
        queued = upload(api, headers).json()["id"]
        assert api.delete(f"/v1/jobs/{queued}", headers=headers).status_code == 200
        assert server.db.job(queued) is None
        server.jobs.run(queued)  # a cancelled job never runs (and nothing breaks)

    def test_round_robin_between_accounts(self, server, clock):
        alice, bob = server.db.add_account("a", clock()), server.db.add_account("b", clock())
        for job_id, account in [("a1", alice), ("a2", alice), ("a3", alice), ("b1", bob)]:
            server.jobs.submit(Job(job_id, account.id, "queued", clock()))
        assert [server.jobs.next_job() for _ in range(5)] == ["a1", "b1", "a2", "a3", None]

    def test_restart_requeues_running_jobs(self, server, api):
        headers = connect(server, api)
        job = upload(api, headers).json()["id"]
        server.db.update_job(job, status="running")
        fresh = Server(server.engine, server.settings, clock=server.clock, start=False)
        try:
            fresh.jobs.recover()
            assert fresh.db.job(job).status == "queued" and fresh.jobs.next_job() == job
        finally:
            fresh.jobs.stop()
            fresh.db.close()


class TestLimits:
    def test_max_jobs_audio_length_and_upload_size(self, server, api, clock):
        headers = connect(server, api)
        account = server.db.account("alice")
        server.db.set_account_limits(account.id, {"max_jobs": 1, "max_audio_minutes": 0.04})  # 2.4 s
        assert upload(api, headers, seconds=3).status_code == 413
        assert upload(api, headers, seconds=2).status_code == 202
        r = upload(api, headers, seconds=2)
        assert r.status_code == 429 and "1 job" in r.json()["detail"]
        server.settings.max_upload_mb = 0
        server.db.set_account_limits(account.id, {})
        assert upload(api, headers).status_code == 413

    def test_requests_per_minute(self, server, api, clock):
        headers = connect(server, api)
        server.db.set_setting("default_limits", {"requests_per_minute": 2})
        codes = [api.get("/v1/account", headers=headers).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        clock.t += 30  # one token back
        assert api.get("/v1/account", headers=headers).status_code == 200


class TestWebhooks:
    def finish_with_hook(self, server, api, url=HOOK):
        headers = connect(server, api)
        job = upload(api, headers, webhook_url=url).json()["id"]
        server.jobs.run(server.jobs.next_job())
        return job

    @respx.mock
    def test_signed_delivery(self, server, api, clock):
        route = respx.post(HOOK).respond(204)
        job = self.finish_with_hook(server, api)
        assert server.webhooks.run_due() == 1
        request = route.calls.last.request
        secret = server.db.account("alice").webhook_secret
        assert verify(secret, request.headers[SIGNATURE_HEADER], request.content, clock())
        body = json.loads(request.content)
        assert body["event"] == "job.completed" and body["job"]["id"] == job and body["job"]["result"]["findings"]
        assert server.db.deliveries(job)[0]["status"] == "delivered"
        assert not verify("whsec_wrong", request.headers[SIGNATURE_HEADER], request.content, clock())

    @respx.mock
    def test_retries_then_gives_up(self, server, api, clock):
        respx.post(HOOK).respond(500)
        job = self.finish_with_hook(server, api)
        for delay in RETRY_DELAYS_S:
            assert server.webhooks.run_due() == 1
            assert server.webhooks.run_due() == 0  # not due yet
            clock.t += delay
        server.webhooks.run_due()
        delivery = server.db.deliveries(job)[0]
        assert delivery["status"] == "failed" and delivery["attempts"] == 4 and delivery["last_error"] == "HTTP 500"

    def test_private_addresses_refused(self):
        with pytest.raises(WebhookError, match="private"):
            check_url("http://intranet/hook", allow_private=False, resolve=lambda h: ["10.0.0.5"])
        with pytest.raises(WebhookError, match="private"):
            check_url("http://localhost/hook", allow_private=False, resolve=lambda h: ["127.0.0.1"])
        check_url("https://hooks.example.com/x", allow_private=False, resolve=lambda h: ["93.184.216.34"])
        check_url("http://10.0.0.5/x", allow_private=True)


class TestPractice:
    def test_streamed_attempt(self, server, api):
        headers = connect(server, api)
        pcm = (np.zeros(16000, dtype="<i2")).tobytes()
        with api.websocket_connect("/v1/practice", headers=headers) as ws:
            ws.send_json({"type": "start", "target": "think", "sample_rate": 16000})
            assert ws.receive_json() == {"type": "started", "target": "think"}
            for i in range(0, len(pcm), 3200):
                ws.send_bytes(pcm[i : i + 3200])
            ws.send_json({"type": "end"})
            reply = ws.receive_json()
            assert reply["type"] == "result" and reply["attempt"]["target"] == "think" and reply["attempt"]["audio"] is None
            assert "score" in reply["attempt"] and reply["seconds"] >= 0
            ws.send_json({"type": "end"})  # the connection stays usable for the next attempt
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        assert not server.engine.practice_store.log_path.exists()  # the server doesn't keep attempts

    def test_needs_a_key(self, api):
        with pytest.raises(WebSocketDisconnect) as e, api.websocket_connect("/v1/practice") as ws:
            ws.receive_json()
        assert e.value.code == 4401

    def test_tts(self, server, api):
        headers = connect(server, api)
        r = api.get("/v1/tts", params={"text": "hello"}, headers=headers)
        assert r.status_code == 200 and r.content == b"RIFFhello" and r.headers["content-type"] == "audio/wav"

    def test_health(self, api):
        health = api.get("/v1/health").json()
        assert health["service"] == "speakcheck" and health["practice"] and health["tts"]
        assert "practice" not in health["analyzers"] and health["source"].startswith("https://github.com/")


class TestAdminCli:
    def run(self, server, argv, ask=lambda q: "y"):
        args = cli._parser().parse_args(["server", *argv])
        engine = server.engine
        engine.config.server = server.settings
        return server_cli.run(args, engine.config, ask, clock=server.clock)

    def test_accounts_invites_devices_limits(self, server, api, capsys):
        assert self.run(server, ["accounts", "add", "carol"]) == 0
        assert self.run(server, ["invite", "carol", "--expires", "2h", "--url", "https://speak.example.com"]) == 0
        out = capsys.readouterr().out
        code = next(w for w in out.split() if w.startswith("inv_"))
        assert "--server-url https://speak.example.com" in out
        key = api.post("/v1/devices/redeem", json={"invite": code, "device_name": "pc"}).json()["key"]
        self.run(server, ["accounts", "list"])
        listed = capsys.readouterr().out
        assert "carol" in listed and "1 device(s)" in listed
        self.run(server, ["limits", "set", "carol", "--max-jobs", "5", "--storage-mb", "100"])
        self.run(server, ["limits", "set", "--default", "--requests-per-minute", "60"])
        capsys.readouterr()
        self.run(server, ["limits", "show", "carol"])
        shown = capsys.readouterr().out
        assert "max_jobs             5  (set here)" in shown and "requests_per_minute  60" in shown
        self.run(server, ["limits", "set", "carol", "--clear", "max_jobs"])
        assert server.limits(server.db.account("carol")).max_jobs == 2
        device = server.db.devices(server.db.account("carol").id)[0]
        self.run(server, ["devices", "revoke", device.id])
        assert api.get("/v1/account", headers={"Authorization": f"Bearer {key}"}).status_code == 401

    def test_jobs_cancel_webhook_secret_and_remove(self, server, api, capsys):
        headers = connect(server, api)
        job = upload(api, headers).json()["id"]
        self.run(server, ["jobs", "cancel", job])
        assert server.db.job(job).status == "cancelled"
        capsys.readouterr()
        old = server.db.account("alice").webhook_secret
        self.run(server, ["webhook-secret", "alice", "--rotate"])
        assert capsys.readouterr().out.strip() != old
        assert self.run(server, ["accounts", "remove", "alice"], ask=lambda q: "n") == 1
        assert self.run(server, ["accounts", "remove", "alice", "-y"]) == 0
        assert server.db.account("alice") is None and server.db.job(job) is None

    def test_bad_input(self, server):
        server.db.add_account("x", 0)
        with pytest.raises(SpeakcheckError, match="durations look like"):
            self.run(server, ["invite", "x", "--expires", "soon"])
        with pytest.raises(SpeakcheckError, match="no account"):
            self.run(server, ["invite", "nobody"])
        with pytest.raises(SpeakcheckError, match="nothing to change"):
            self.run(server, ["limits", "set", "x"])


class TestOsService:
    def test_systemd(self, tmp_path):
        from speakcheck.server import os_service

        runner = []
        record = lambda cmd, **kw: runner.append(cmd) or type("P", (), {"stdout": "Linger=no", "returncode": 0})()  # noqa: E731
        cmd = os_service.command("/py", tmp_path / "config.toml", "0.0.0.0", 9000)
        where = os_service.install(cmd, tmp_path, record, platform="linux", home=tmp_path)
        unit = (tmp_path / ".config/systemd/user/speakcheck-server.service").read_text()
        assert "ExecStart=/py -m speakcheck.cli server serve --config" in unit and "--port 9000" in unit
        assert ["systemctl", "--user", "enable", "--now", "speakcheck-server"] in runner
        assert "enable-linger" in where
        assert os_service.remove(record, platform="linux", home=tmp_path)
        assert not os_service.remove(record, platform="linux", home=tmp_path)

    def test_macos_and_windows(self, tmp_path):
        from speakcheck.server import os_service

        runner = []
        record = lambda cmd, **kw: runner.append(cmd) or type("P", (), {"stdout": "", "returncode": 0})()  # noqa: E731
        cmd = os_service.command("/Applications/My Python/py", None, None, None)
        os_service.install(cmd, tmp_path, record, platform="darwin", home=tmp_path)
        plist = (tmp_path / "Library/LaunchAgents/com.speakcheck.server.plist").read_text()
        assert "<string>/Applications/My Python/py</string>" in plist and "<key>KeepAlive</key>" in plist
        os_service.install(["C:\\Program Files\\py.exe", "-m", "speakcheck.cli"], tmp_path, record, platform="win32")
        task = runner[-2]
        assert task[:3] == ["schtasks", "/Create", "/TN"] and '"C:\\Program Files\\py.exe" -m speakcheck.cli' in task
        with pytest.raises(OSError):
            os_service.install(cmd, tmp_path, record, platform="plan9")
