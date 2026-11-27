"""Background jobs (renders, media preparation) with progress events and cancellation."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .db import Database
from .ids import new_id
from .render.ffmpeg import Cancelled, CancelToken

log = logging.getLogger("shorts_studio.jobs")


class JobError(Exception):
    """A failure with a message meant for the user, plus optional structured detail."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class EventHub:
    """Fan-out of JSON events to WebSocket clients. ``publish`` is safe to call from any thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def _fanout(self, event: dict) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def publish(self, event: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, event)
        except RuntimeError:
            pass


@dataclass
class JobContext:
    job_id: str
    kind: str
    project_id: str | None
    cancel: CancelToken
    _db: Database
    _hub: EventHub
    _last_write: float = 0.0
    _last_stage: str = ""
    _pct: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def progress(self, pct: float, stage: str) -> None:
        now = time.monotonic()
        with self._lock:
            pct = max(self._pct, min(100.0, pct))
            changed_stage = stage != self._last_stage
            if not changed_stage and now - self._last_write < 0.25 and pct < 100:
                self._pct = pct
                return
            self._pct, self._last_stage, self._last_write = pct, stage, now
        self._db.update_job(self.job_id, pct=round(pct, 1), stage=stage)
        self._hub.publish({"type": "job.progress", "job_id": self.job_id, "kind": self.kind,
                           "project_id": self.project_id, "pct": round(pct, 1), "stage": stage})


class JobManager:
    def __init__(self, db: Database, hub: EventHub, *, render_workers: int = 1, media_workers: int = 2):
        self.db = db
        self.hub = hub
        self._pools = {"render": ThreadPoolExecutor(render_workers, thread_name_prefix="render"),
                       "media": ThreadPoolExecutor(media_workers, thread_name_prefix="media")}
        self._tokens: dict[str, CancelToken] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[JobContext], dict | None], *, project_id: str | None = None,
               pool: str = "render") -> str:
        job_id = new_id("job")
        token = CancelToken()
        with self._lock:
            self._tokens[job_id] = token
        self.db.insert_job(job_id, kind, project_id)
        ctx = JobContext(job_id, kind, project_id, token, self.db, self.hub)
        self.hub.publish({"type": "job.queued", "job_id": job_id, "kind": kind, "project_id": project_id})
        self._pools[pool].submit(self._run, ctx, fn)
        return job_id

    def _run(self, ctx: JobContext, fn: Callable[[JobContext], dict | None]) -> None:
        base = {"job_id": ctx.job_id, "kind": ctx.kind, "project_id": ctx.project_id}
        try:
            if ctx.cancel.cancelled:
                raise Cancelled(ctx.kind)
            self.db.update_job(ctx.job_id, status="running", stage="Starting")
            self.hub.publish({"type": "job.progress", **base, "pct": 0, "stage": "Starting"})
            result = fn(ctx) or {}
            self.db.update_job(ctx.job_id, status="done", pct=100, stage="Done", result=result)
            self.hub.publish({"type": "job.done", **base, "result": result})
        except Cancelled:
            self.db.update_job(ctx.job_id, status="cancelled", stage="Cancelled")
            self.hub.publish({"type": "job.cancelled", **base})
        except JobError as e:
            self.db.update_job(ctx.job_id, status="failed", stage="Failed", error=str(e), result=e.detail or None)
            self.hub.publish({"type": "job.failed", **base, "error": str(e), "detail": e.detail})
        except Exception as e:  # noqa: BLE001 - every failure must reach the user, not just the log
            log.error("job %s failed:\n%s", ctx.job_id, traceback.format_exc())
            msg = str(e) or e.__class__.__name__
            self.db.update_job(ctx.job_id, status="failed", stage="Failed", error=msg)
            self.hub.publish({"type": "job.failed", **base, "error": msg})
        finally:
            with self._lock:
                self._tokens.pop(ctx.job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(job_id)
        if token is None:
            return False
        token.cancel()
        return True

    def shutdown(self) -> None:
        with self._lock:
            tokens = list(self._tokens.values())
        for t in tokens:
            t.cancel()
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
