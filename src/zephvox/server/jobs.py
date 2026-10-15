"""Async analysis jobs: one worker thread, a queue per account served round-robin, so one account's
long uploads can't hold everyone else back. Finished jobs are deleted after `job_ttl_hours`.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..engine.engine import Engine
from ..engine.events import Event
from ..web.daemon import jsonable
from .db import Database, Job

PROGRESS_EVENTS = ("stage_started", "stage_finished", "progress", "warning", "provider_fallback")
MAX_EVENTS = 500
JANITOR_EVERY_S = 60.0


class JobRunner:
    def __init__(self, engine: Engine, db: Database, root: Path, clock: Callable[[], float], ttl_s: float,
                 on_finished: Callable[[Job], None] = lambda job: None):  # fmt: skip
        self.engine = engine
        self.db = db
        self.root = root
        self.clock = clock
        self.ttl_s = ttl_s
        self.on_finished = on_finished
        self._queues: dict[str, deque[str]] = {}
        self._order: deque[str] = deque()  # accounts with queued jobs, in serving order
        self._cond = threading.Condition()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._current: str | None = None
        self._worker_ident: int | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._unsubscribe = engine.events.subscribe(self._on_event)

    # --- files --------------------------------------------------------------------------

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def audio_path(self, job: Job) -> Path:
        """Uploads are decoded to 16 kHz mono WAV when they arrive (that also measures them)."""
        return self.job_dir(job.id) / "audio.wav"

    def result(self, job_id: str) -> dict[str, Any] | None:
        path = self.job_dir(job_id) / "result.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    # --- queue --------------------------------------------------------------------------

    def recover(self) -> None:
        """After a restart: jobs that were running start again; queued ones keep their place."""
        for job in self.db.jobs(statuses=("running",)):
            self.db.update_job(job.id, status="queued", started=None)
        for job in self.db.jobs(statuses=("queued",)):
            self._enqueue(job)

    def start(self) -> None:
        self.recover()
        for target, name in ((self._work, "jobs"), (self._janitor, "janitor")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        for thread in self._threads:
            thread.join(timeout=5)
        self._unsubscribe()

    def submit(self, job: Job) -> None:
        self._events[job.id] = []
        self._enqueue(job)

    def _enqueue(self, job: Job) -> None:
        with self._cond:
            if job.account_id not in self._queues:
                self._queues[job.account_id] = deque()
            if job.account_id not in self._order:
                self._order.append(job.account_id)
            self._queues[job.account_id].append(job.id)
            self._cond.notify()

    def queued(self) -> int:
        with self._cond:
            return sum(len(q) for q in self._queues.values())

    def next_job(self) -> str | None:
        """Round-robin: the next account's oldest job (each account takes its turn)."""
        with self._cond:
            while self._order:
                account = self._order.popleft()
                queue = self._queues.get(account)
                if not queue:
                    continue
                job_id = queue.popleft()
                if queue:
                    self._order.append(account)  # its next job waits for the other accounts
                return job_id
            return None

    def _work(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while not self._stop.is_set() and not any(self._queues.values()):
                    self._cond.wait()
            job_id = self.next_job()
            if job_id is not None:
                self.run(job_id)

    def run(self, job_id: str) -> None:
        job = self.db.job(job_id)
        if job is None or job.status != "queued":  # cancelled (or deleted) while waiting
            return
        self._worker_ident = threading.get_ident()  # events from this thread belong to this job
        self._current = job_id
        self._events.setdefault(job_id, [])
        self.db.update_job(job_id, status="running", started=self.clock())
        try:
            result = self.engine.analyze(self.audio_path(job), job.analyzers or None, save=False)
            data = result.to_dict()
            data["audio_path"] = ""  # a path on the server means nothing to the client
            (self.job_dir(job_id) / "result.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            update: dict[str, Any] = {"status": "done", "error": None}
        except Exception as e:  # any failure belongs to this job, not the server
            update = {"status": "failed", "error": str(e) or type(e).__name__}
        finally:
            self._current = None
            if self.queued() == 0:
                self.engine.release("llm")  # free the GPU (and stop an autostarted Ollama) when idle
        now = self.clock()
        current = self.db.job(job_id)
        if current is None:
            return
        if current.status == "cancelled":  # deleted while it ran
            self.delete(job_id)
            return
        self.db.update_job(job_id, finished=now, expires=now + self.ttl_s, **update)
        self._events[job_id].append({"type": "job_" + update["status"], "data": {"error": update["error"]}})
        self.on_finished(self.db.job(job_id))  # type: ignore[arg-type]

    def cancel(self, job: Job) -> None:
        """Queued: never runs. Running: its result is thrown away. Finished: deleted now."""
        if job.status in ("queued", "running"):
            self.db.update_job(job.id, status="cancelled", finished=self.clock())
            if job.status == "queued":
                self.delete(job.id)
        else:
            self.delete(job.id)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        self.db.delete_job(job_id)
        self._events.pop(job_id, None)

    # --- progress -----------------------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        job_id = self._current
        if job_id is None or threading.get_ident() != self._worker_ident or event.type not in PROGRESS_EVENTS:
            return
        events = self._events.setdefault(job_id, [])
        if len(events) < MAX_EVENTS:
            events.append({"type": event.type, "data": jsonable(event.data)})

    def events_since(self, job_id: str, cursor: int) -> list[dict[str, Any]]:
        return self._events.get(job_id, [])[cursor:]

    # --- cleanup ------------------------------------------------------------------------

    def expire(self) -> int:
        expired = self.db.expired_jobs(self.clock())
        for job in expired:
            self.delete(job.id)
        return len(expired)

    def _janitor(self) -> None:
        while not self._stop.wait(JANITOR_EVERY_S):
            self.expire()
