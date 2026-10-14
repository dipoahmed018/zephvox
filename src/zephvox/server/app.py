"""The server's API (`/v1`). Every route except health and invite redemption needs a device key:
`Authorization: Bearer sk_...`. Accounts only ever see their own jobs and devices.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from ..engine import audio
from ..engine.errors import ZephvoxError
from ..engine.models import SAMPLE_RATE
from .db import Account, Device, Job
from .keys import new_id
from .service import Server
from .webhooks import WebhookError, check_url

FINAL = ("done", "failed", "cancelled")
EVENT_POLL_S = 0.2
KEEPALIVE_S = 15.0
PRACTICE_MAX_S = 30.0
TOUCH_EVERY_S = 60.0
CHUNK = 1 << 20


@dataclass
class Caller:
    device: Device
    account: Account


SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
MAX_SESSION_JSON = 5 * 1024 * 1024


class SessionBody(BaseModel):
    updated: float
    result: dict[str, Any]
    feedback: dict[str, str] = Field(default_factory=dict)


class AttemptsBody(BaseModel):
    attempts: list[dict[str, Any]] = Field(max_length=1000)


class RedeemBody(BaseModel):
    invite: str
    device_name: str = Field(default="device", min_length=1, max_length=80)


def create_server_app(server: Server) -> FastAPI:
    app = FastAPI(title="zephvox server", version="1", docs_url="/v1/docs", openapi_url="/v1/openapi.json")
    db = server.db

    def identify(authorization: str | None) -> Caller:
        scheme, _, key = (authorization or "").partition(" ")
        device = db.device_for_key(key.strip()) if scheme.lower() == "bearer" and key.strip() else None
        account = db.account(device.account_id) if device else None
        if device is None or account is None:
            raise HTTPException(401, "missing or invalid device key", headers={"WWW-Authenticate": "Bearer"})
        now = server.clock()
        if not server.rate.allow(account.id, server.limits(account).requests_per_minute, now):
            raise HTTPException(429, "too many requests: slow down", headers={"Retry-After": "5"})
        if device.last_seen is None or now - device.last_seen > TOUCH_EVERY_S:
            db.touch_device(device.id, now)
        return Caller(device, account)

    def caller(authorization: str | None = Header(default=None)) -> Caller:
        return identify(authorization)

    @app.middleware("http")
    async def check_uploads_early(request: Request, call_next):
        """Refuse an upload before its body is read: no key, or bigger than allowed."""
        if request.method == "POST" and request.url.path == "/v1/jobs":
            scheme, _, key = (request.headers.get("authorization") or "").partition(" ")
            if scheme.lower() != "bearer" or db.device_for_key(key.strip()) is None:
                return JSONResponse({"detail": "missing or invalid device key"}, 401, headers={"WWW-Authenticate": "Bearer"})
            length = int(request.headers.get("content-length") or 0)
            if length > server.settings.max_upload_mb * 1024 * 1024 + CHUNK:  # a little room for the form fields
                return JSONResponse({"detail": f"upload is larger than {server.settings.max_upload_mb} MB"}, 413)
        return await call_next(request)

    # --- public ------------------------------------------------------------------------

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return server.health()

    @app.post("/v1/devices/redeem")
    def redeem(body: RedeemBody) -> dict[str, Any]:
        try:
            device, key = db.redeem_invite(body.invite.strip(), body.device_name, server.clock())
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        account = db.account(device.account_id)
        return {"key": key, "device": _device(device, device.id), "account": account.name if account else None}

    # --- account and devices ------------------------------------------------------------

    @app.get("/v1/account")
    def account(who: Caller = Depends(caller)) -> dict[str, Any]:
        return {**server.account_view(who.account), "device": _device(who.device, who.device.id)}

    @app.get("/v1/devices")
    def devices(who: Caller = Depends(caller)) -> list[dict[str, Any]]:
        return [_device(d, who.device.id) for d in db.devices(who.account.id) if d.revoked is None]

    @app.post("/v1/devices/me/rotate")
    def rotate(who: Caller = Depends(caller)) -> dict[str, Any]:
        return {"key": db.rotate_key(who.device.id), "device": _device(who.device, who.device.id)}

    @app.delete("/v1/devices/{device_id}")
    def revoke(device_id: str, who: Caller = Depends(caller)) -> dict[str, Any]:
        device = db.device(device_id)
        if device is None or device.account_id != who.account.id:
            raise HTTPException(404, "no such device")
        db.revoke_device(device_id, server.clock())
        return {"revoked": device_id}

    # --- jobs ---------------------------------------------------------------------------

    def own_job(job_id: str, who: Caller) -> Job:
        job = db.job(job_id, who.account.id)
        if job is None:
            raise HTTPException(404, "no such job (it may have expired)")
        return job

    @app.post("/v1/jobs", status_code=202)
    def create_job(
        audio_file: UploadFile = File(alias="audio"),
        analyzers: str = Form(default=""),
        webhook_url: str | None = Form(default=None),
        idempotency_key: str | None = Header(default=None, max_length=200),
        who: Caller = Depends(caller),
    ) -> JSONResponse:
        if idempotency_key and (existing := _existing(idempotency_key, who)):
            return _accepted(existing, server)
        names = [a.strip() for a in analyzers.split(",") if a.strip()]
        known = set(server.installed_analyzers())
        if unknown := [a for a in names if a not in known]:
            raise HTTPException(422, f"unknown analyzer(s): {', '.join(unknown)}; available: {', '.join(sorted(known))}")
        if webhook_url:
            try:
                check_url(webhook_url, server.settings.webhook_allow_private)
            except WebhookError as e:
                raise HTTPException(422, str(e)) from e
        limit = server.limits(who.account)
        if db.active_jobs(who.account.id) >= limit.max_jobs:
            raise HTTPException(429, f"this account already has {limit.max_jobs} job(s) waiting or running",
                                headers={"Retry-After": "30"})  # fmt: skip
        job = Job(new_id("job"), who.account.id, "queued", server.clock(), analyzers=names,
                  filename=(audio_file.filename or "audio")[:200], idempotency_key=idempotency_key,
                  webhook_url=webhook_url or None)  # fmt: skip
        folder = server.jobs.job_dir(job.id)
        folder.mkdir(parents=True)
        try:
            upload = folder / "upload"
            _save_upload(audio_file, upload, server.settings.max_upload_mb)
            try:
                samples = audio.decode(upload)
            except ZephvoxError as e:
                raise HTTPException(422, f"can't read this audio: {e}") from e
            job.duration = round(audio.duration(samples), 2)
            if job.duration > limit.max_audio_minutes * 60:
                raise HTTPException(413, f"audio is {job.duration / 60:.1f} min; the limit is {limit.max_audio_minutes:g} min")
            audio.write_wav(server.jobs.audio_path(job), samples)
            upload.unlink()
            stored = db.add_job(job)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        if stored.id != job.id:  # the same idempotency key arrived twice at once
            shutil.rmtree(folder, ignore_errors=True)
        else:
            server.jobs.submit(stored)
        return _accepted(stored, server)

    def _existing(key: str, who: Caller) -> Job | None:
        return next((j for j in db.jobs(who.account.id) if j.idempotency_key == key), None)

    @app.get("/v1/jobs")
    def list_jobs(who: Caller = Depends(caller)) -> list[dict[str, Any]]:
        return [server.job_view(j, result=False) for j in db.jobs(who.account.id)]

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, who: Caller = Depends(caller)) -> dict[str, Any]:
        return server.job_view(own_job(job_id, who))

    @app.delete("/v1/jobs/{job_id}")
    def delete_job(job_id: str, who: Caller = Depends(caller)) -> dict[str, Any]:
        server.jobs.cancel(own_job(job_id, who))
        return {"deleted": job_id}

    @app.get("/v1/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request, who: Caller = Depends(caller)) -> StreamingResponse:
        own_job(job_id, who)

        async def stream():
            cursor, quiet = 0, 0.0
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                events = server.jobs.events_since(job_id, cursor)
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                cursor += len(events)
                job = db.job(job_id)
                if job is None or job.status in FINAL:
                    final = {"type": "job", "data": server.job_view(job, result=False) if job else {"id": job_id, "status": "deleted"}}
                    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                    return
                await asyncio.sleep(EVENT_POLL_S)
                quiet = 0.0 if events else quiet + EVENT_POLL_S
                if quiet >= KEEPALIVE_S:
                    quiet = 0.0
                    yield ": keepalive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    # --- practice -----------------------------------------------------------------------

    @app.websocket("/v1/practice")
    async def practice(ws: WebSocket) -> None:
        try:
            identify(ws.headers.get("authorization"))
        except HTTPException as e:
            await ws.close(code=4000 + e.status_code, reason=str(e.detail))
            return
        await ws.accept()
        loop = asyncio.get_running_loop()
        target: str | None = None
        warm: asyncio.Future | None = None
        buffer = bytearray()
        max_bytes = int(PRACTICE_MAX_S * SAMPLE_RATE * 2)
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    if target is None:
                        await ws.send_json({"type": "error", "message": "send start first"})
                    elif len(buffer) + len(message["bytes"]) > max_bytes:
                        await ws.send_json({"type": "error", "message": f"attempts are limited to {PRACTICE_MAX_S:g} s"})
                        target, buffer = None, bytearray()
                    else:
                        buffer += message["bytes"]
                    continue
                try:
                    data = json.loads(message.get("text") or "{}")
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "messages must be JSON or binary audio"})
                    continue
                kind = data.get("type")
                if kind == "start":
                    text = str(data.get("target") or "").strip()
                    if not 0 < len(text) <= 200:
                        await ws.send_json({"type": "error", "message": "target must be 1–200 characters"})
                        continue
                    if int(data.get("sample_rate", SAMPLE_RATE)) != SAMPLE_RATE:
                        await ws.send_json({"type": "error", "message": f"send 16-bit mono PCM at {SAMPLE_RATE} Hz"})
                        continue
                    target, buffer = text, bytearray()
                    warm = loop.run_in_executor(server.practice_pool, server.warm_practice, text)
                    await ws.send_json({"type": "started", "target": text})
                elif kind == "end":
                    if target is None:
                        await ws.send_json({"type": "error", "message": "send start first"})
                        continue
                    began = time.perf_counter()
                    samples = np.frombuffer(bytes(buffer[: len(buffer) // 2 * 2]), dtype="<i2").astype(np.float32) / 32768
                    try:
                        if warm is not None:
                            await warm
                        attempt = await loop.run_in_executor(server.practice_pool, server.score_practice, target, samples)
                    except Exception as e:  # report it on the socket; the connection stays usable
                        await ws.send_json({"type": "error", "message": str(e) or type(e).__name__})
                    else:
                        await ws.send_json({"type": "result", "attempt": attempt,
                                            "seconds": round(time.perf_counter() - began, 3)})  # fmt: skip
                    target, warm, buffer = None, None, bytearray()
                elif kind == "cancel":
                    target, warm, buffer = None, None, bytearray()
                    await ws.send_json({"type": "cancelled"})
                elif kind == "ping":
                    await ws.send_json({"type": "pong"})
                else:
                    await ws.send_json({"type": "error", "message": f"unknown message type {kind!r}"})
        except WebSocketDisconnect:
            return

    # --- synced history -------------------------------------------------------------------

    def session_dir(who: Caller, sid: str):
        if not SESSION_ID.match(sid):
            raise HTTPException(422, "invalid session id")
        return server.root / "accounts" / who.account.id / "sessions" / sid

    def check_storage(who: Caller, sid: str, new_bytes: int, part: str) -> None:
        limit = server.limits(who.account).storage_mb * 1024 * 1024
        current = db.synced(who.account.id, sid)
        folder = session_dir(who, sid)
        old = (folder / part).stat().st_size if (folder / part).exists() else 0
        if current and current["deleted"]:
            old = 0
        if db.storage_bytes(who.account.id) - old + new_bytes > limit:
            raise HTTPException(507, f"this account's synced history is full ({limit // (1024 * 1024)} MB)")

    def folder_bytes(folder) -> int:
        return sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) if folder.exists() else 0

    @app.get("/v1/sessions")
    def list_sessions(since: float = 0.0, who: Caller = Depends(caller)) -> dict[str, Any]:
        rows = db.synced_since(who.account.id, since)
        return {"now": server.clock(), "sessions": [
            {"id": r["session_id"], "updated": r["updated"], "deleted": bool(r["deleted"]),
             "has_audio": bool(r["has_audio"]), "origin": r["origin"]} for r in rows]}  # fmt: skip

    @app.get("/v1/sessions/{sid}")
    def get_session(sid: str, who: Caller = Depends(caller)) -> dict[str, Any]:
        row, folder = db.synced(who.account.id, sid), session_dir(who, sid)
        if row is None or row["deleted"] or not (folder / "result.json").exists():
            raise HTTPException(404, "no such session")
        feedback = json.loads((folder / "feedback.json").read_text()) if (folder / "feedback.json").exists() else {}
        return {"id": sid, "updated": row["updated"], "has_audio": bool(row["has_audio"]),
                "result": json.loads((folder / "result.json").read_text()), "feedback": feedback}  # fmt: skip

    @app.put("/v1/sessions/{sid}")
    def put_session(sid: str, body: SessionBody, who: Caller = Depends(caller)) -> dict[str, Any]:
        folder = session_dir(who, sid)
        row = db.synced(who.account.id, sid)
        if row and not row["deleted"]:
            if row["origin"] != who.device.id and (folder / "result.json").exists():
                stored = json.loads((folder / "result.json").read_text())
                if stored.get("created") != body.result.get("created"):
                    raise HTTPException(409, "id_taken: another device synced a different session with this id")
            if row["updated"] > body.updated:
                raise HTTPException(409, f"newer: the server has a newer version ({row['updated']})")
        result = json.dumps(body.result, ensure_ascii=False).encode()
        feedback = json.dumps(body.feedback).encode()
        if len(result) > MAX_SESSION_JSON:
            raise HTTPException(413, "session result is too large")
        check_storage(who, sid, len(result) + len(feedback), "result.json")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "result.json").write_bytes(result)
        (folder / "feedback.json").write_bytes(feedback)
        db.put_synced(who.account.id, sid, who.device.id, body.updated, server.clock(), bytes=folder_bytes(folder))
        return {"id": sid, "updated": body.updated}

    @app.put("/v1/sessions/{sid}/audio")
    async def put_session_audio(sid: str, request: Request, who: Caller = Depends(caller)) -> dict[str, Any]:
        folder = session_dir(who, sid)
        row = db.synced(who.account.id, sid)
        if row is None or row["deleted"]:
            raise HTTPException(404, "send the session before its audio")
        data = bytearray()
        limit = server.settings.max_upload_mb * 1024 * 1024
        async for chunk in request.stream():
            data += chunk
            if len(data) > limit:
                raise HTTPException(413, f"audio is larger than {server.settings.max_upload_mb} MB")
        if not bytes(data[:4]) == b"RIFF":
            raise HTTPException(422, "send the session audio as WAV")
        check_storage(who, sid, len(data), "audio.wav")
        (folder / "audio.wav").write_bytes(bytes(data))
        db.put_synced(who.account.id, sid, row["origin"], row["updated"], server.clock(), bytes=folder_bytes(folder),
                      has_audio=True)  # fmt: skip
        return {"id": sid, "bytes": len(data)}

    @app.get("/v1/sessions/{sid}/audio")
    def get_session_audio(sid: str, who: Caller = Depends(caller)) -> FileResponse:
        path = session_dir(who, sid) / "audio.wav"
        row = db.synced(who.account.id, sid)
        if row is None or row["deleted"] or not path.exists():
            raise HTTPException(404, "no audio for this session")
        return FileResponse(path, media_type="audio/wav")

    @app.delete("/v1/sessions/{sid}")
    def delete_session(sid: str, updated: float = Query(...), who: Caller = Depends(caller)) -> dict[str, Any]:
        folder = session_dir(who, sid)
        row = db.synced(who.account.id, sid)
        if row and not row["deleted"] and row["updated"] > updated:
            raise HTTPException(409, f"newer: the server has a newer version ({row['updated']})")
        shutil.rmtree(folder, ignore_errors=True)
        db.put_synced(who.account.id, sid, who.device.id, updated, server.clock(), deleted=True, bytes=0, has_audio=False)
        return {"deleted": sid}

    @app.post("/v1/practice/attempts")
    def push_attempts(body: AttemptsBody, who: Caller = Depends(caller)) -> dict[str, Any]:
        pairs = [(f"{a.get('at')}|{a.get('target')}|{a.get('score')}", json.dumps(a, ensure_ascii=False))
                 for a in body.attempts]  # fmt: skip
        return {"added": db.add_attempts(who.account.id, pairs, server.clock())}

    @app.get("/v1/practice/attempts")
    def pull_attempts(since: float = 0.0, who: Caller = Depends(caller)) -> dict[str, Any]:
        return {"now": server.clock(), "attempts": [json.loads(d) for _, d in db.attempts_since(who.account.id, since)]}

    # --- reference voices ---------------------------------------------------------------

    @app.get("/v1/voices")
    def voices(who: Caller = Depends(caller)) -> dict[str, Any]:
        try:
            caps = server._tts_provider(None).capabilities()
        except ZephvoxError as e:
            raise HTTPException(404, str(e)) from e
        return {"selected": caps.get("voice"), "voices": caps.get("voices", [])}

    @app.get("/v1/tts")
    def tts(text: str = Query(min_length=1, max_length=300), voice: str | None = Query(default=None, max_length=40),
            who: Caller = Depends(caller)) -> Response:  # fmt: skip
        try:
            wav = server.tts(text, voice)
        except ZephvoxError as e:
            raise HTTPException(404 if "tts" in str(e).lower() else 502, str(e)) from e
        return Response(wav, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})

    return app


def _device(device: Device, current_id: str) -> dict[str, Any]:
    return {"id": device.id, "name": device.name, "created": device.created, "last_seen": device.last_seen,
            "current": device.id == current_id}  # fmt: skip


def _accepted(job: Job, server: Server) -> JSONResponse:
    return JSONResponse(server.job_view(job, result=False), status_code=202, headers={"Location": f"/v1/jobs/{job.id}"})


def _save_upload(upload: UploadFile, path, max_mb: int) -> None:
    limit = max_mb * 1024 * 1024
    size = 0
    with open(path, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"upload is larger than {max_mb} MB")
            out.write(chunk)
