"""Bring files into the app: probe, register, and queue their posters, filmstrips and proxies."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from ..config import Settings
from ..db import Database
from ..ids import new_id
from ..jobs import JobContext, JobManager
from ..project import defaults as d
from . import assets
from .probe import SUPPORTED_SUFFIXES, ProbeError, needs_proxy, probe_file

log = logging.getLogger("shorts_studio.media")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DialogError(Exception):
    pass


def native_dialog(mode: str, title: str) -> list[str]:
    proc = subprocess.run([sys.executable, "-m", "shorts_studio.media.dialog_proc", mode, title],
                          capture_output=True, text=True, timeout=1800, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise DialogError("The file dialog could not be opened: " + proc.stderr.strip()[-300:])
    return json.loads(proc.stdout or "[]")


def probe_paths(settings: Settings, db: Database, jobs: JobManager, paths: list[str], *,
                ownership: str = "own") -> tuple[list[tuple[str, dict]], list[dict]]:
    """Probe each path and register it. Returns ([(source_id, source_record)], [errors])."""
    out: list[tuple[str, dict]] = []
    errors: list[dict] = []
    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            errors.append({"path": raw, "error": f"{path.name}: this file type isn't supported."})
            continue
        try:
            kind, fp, extra = probe_file(path)
        except ProbeError as e:
            errors.append({"path": raw, "error": str(e)})
            continue
        sid = new_id("src")
        record = d.source_record(kind, settings.to_project_path(path), path.name, fp, ownership=ownership)
        register(settings, db, jobs, sid, record, extra)
        out.append((sid, record))
    return out, errors


def register(settings: Settings, db: Database, jobs: JobManager, source_id: str, record: dict, extra: dict) -> None:
    path = settings.resolve_media_path(record["path"])
    proxy_needed = needs_proxy(record["kind"], record["fingerprint"], extra)
    db.upsert_media(source_id, path, record["fingerprint"], {**extra, "kind": record["kind"]},
                    proxy_state="needed" if proxy_needed else "none")
    row = db.get_media(source_id)
    if row and ((record["kind"] != "audio" and not row["poster"])
                or (proxy_needed and row["proxy_state"] in ("needed", "failed"))
                or (record["kind"] == "video" and not row["filmstrip"])):
        jobs.submit("media_prep", lambda ctx: prepare(settings, db, jobs, source_id, ctx), pool="media")


def ensure_registered(settings: Settings, db: Database, jobs: JobManager, doc: dict) -> None:
    """Opening a project re-registers its sources (the database is a cache; the project file is the truth)."""
    for sid, record in doc["sources"].items():
        row = db.get_media(sid)
        path = settings.resolve_media_path(record["path"])
        if row and row["path"] == str(path) and row["fingerprint"] == record["fingerprint"]:
            continue
        if not path.is_file():
            continue
        try:
            _kind, _fp, extra = probe_file(path)
        except ProbeError:
            continue
        register(settings, db, jobs, sid, record, extra)


def prepare(settings: Settings, db: Database, jobs: JobManager, source_id: str, ctx: JobContext) -> dict:
    row = db.get_media(source_id)
    if row is None:
        return {}
    src = Path(row["path"])
    kind = row["probe"].get("kind")
    dur = row["fingerprint"].get("duration_s") or 0
    folder = settings.derived_dir / source_id
    made = []
    if not row["poster"] and kind in ("video", "image"):          # audio files have no picture
        ctx.progress(5, "Poster")
        db.set_media_fields(source_id, poster=str(assets.poster(src, kind, dur, folder / "poster.jpg")))
        made.append("poster")
    if kind == "video" and not row["filmstrip"]:
        ctx.progress(20, "Filmstrip")
        db.set_media_fields(source_id, filmstrip=str(assets.filmstrip(src, dur, folder / "filmstrip.jpg")))
        made.append("filmstrip")
    jobs.hub.publish({"type": "media.updated", "source_id": source_id, "made": made})
    if row["proxy_state"] in ("needed", "failed"):
        db.set_media_fields(source_id, proxy_state="building")
        jobs.hub.publish({"type": "media.updated", "source_id": source_id, "proxy_state": "building"})
        try:
            p = assets.proxy(src, dur, folder / "proxy.mp4", cancel=ctx.cancel,
                             progress=lambda f: ctx.progress(30 + 70 * f, "Preview copy"))
            db.set_media_fields(source_id, proxy=str(p), proxy_state="ready")
            made.append("proxy")
        except Exception:
            db.set_media_fields(source_id, proxy_state="failed")
            jobs.hub.publish({"type": "media.updated", "source_id": source_id, "proxy_state": "failed"})
            raise
        jobs.hub.publish({"type": "media.updated", "source_id": source_id, "proxy_state": "ready"})
    return {"source_id": source_id, "made": made}
