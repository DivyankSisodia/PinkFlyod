"""SQLite: the media registry, jobs and renders. Projects themselves are JSON files (see project/store.py)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 3

_MIGRATIONS = {
    3: """
    ALTER TABLE gameplay_clips ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE job_checkpoints (
        id INTEGER PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        pct REAL NOT NULL,
        stage TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX job_checkpoints_by_job ON job_checkpoints(job_id, id);
    """,
    2: """
    CREATE TABLE gameplay_clips (
        id           TEXT PRIMARY KEY,         -- gpc_...
        path         TEXT NOT NULL,            -- inside data/gameplay/<id>/
        display_name TEXT NOT NULL,
        tags         TEXT NOT NULL,            -- JSON list
        fingerprint  TEXT NOT NULL,            -- JSON
        sample       INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL
    );
    CREATE TABLE gameplay_usage (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id     TEXT NOT NULL,
        in_s        REAL NOT NULL,
        out_s       REAL NOT NULL,
        project_id  TEXT,
        scene_id    TEXT,
        used_at     TEXT NOT NULL
    );
    CREATE INDEX gameplay_usage_by_clip ON gameplay_usage(clip_id);
    """,
    1: """
    CREATE TABLE media (
        id          TEXT PRIMARY KEY,          -- the project source id (src_...)
        path        TEXT NOT NULL,             -- absolute path on disk
        fingerprint TEXT NOT NULL,             -- JSON, as stored in the project
        probe       TEXT NOT NULL,             -- JSON, extra ffprobe facts (pix_fmt, container, ...)
        poster      TEXT,
        filmstrip   TEXT,
        proxy       TEXT,
        proxy_state TEXT NOT NULL DEFAULT 'none',   -- none | needed | building | ready | failed
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE jobs (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        project_id  TEXT,
        status      TEXT NOT NULL,             -- queued | running | done | failed | cancelled
        pct         REAL NOT NULL DEFAULT 0,
        stage       TEXT NOT NULL DEFAULT '',
        error       TEXT,
        result      TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX jobs_by_project ON jobs(project_id, created_at);
    CREATE TABLE renders (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL,
        revision    INTEGER NOT NULL,
        path        TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        verify      TEXT NOT NULL,             -- JSON report from render/verify.py
        warnings    TEXT NOT NULL              -- JSON list
    );
    CREATE INDEX renders_by_project ON renders(project_id, created_at);
    """,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            current = c.execute("PRAGMA user_version").fetchone()[0]
            for version in range(current + 1, SCHEMA_VERSION + 1):
                c.executescript(_MIGRATIONS[version])
                c.execute(f"PRAGMA user_version={version}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── media ────────────────────────────────────────────────────────────
    def upsert_media(self, source_id: str, path: Path, fingerprint: dict, probe: dict,
                     proxy_state: str | None = None) -> None:
        with self.connect() as c:
            row = c.execute("SELECT path, fingerprint FROM media WHERE id=?", (source_id,)).fetchone()
            same_file = row is not None and row["path"] == str(path) and json.loads(row["fingerprint"]) == fingerprint
            if same_file:
                c.execute("UPDATE media SET probe=?, updated_at=? WHERE id=?",
                          (json.dumps(probe), now_iso(), source_id))
                if proxy_state is not None:
                    c.execute("UPDATE media SET proxy_state=? WHERE id=? AND proxy_state IN ('none','failed')",
                              (proxy_state, source_id))
                return
            # A new or relinked file: derived assets belong to the old file and are dropped.
            c.execute(
                "INSERT INTO media (id, path, fingerprint, probe, poster, filmstrip, proxy, proxy_state, updated_at) "
                "VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET path=excluded.path, fingerprint=excluded.fingerprint, "
                "probe=excluded.probe, poster=NULL, filmstrip=NULL, proxy=NULL, proxy_state=excluded.proxy_state, "
                "updated_at=excluded.updated_at",
                (source_id, str(path), json.dumps(fingerprint), json.dumps(probe), proxy_state or "none", now_iso()))

    def get_media(self, source_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM media WHERE id=?", (source_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["fingerprint"] = json.loads(out["fingerprint"])
        out["probe"] = json.loads(out["probe"])
        return out

    def set_media_fields(self, source_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as c:
            c.execute(f"UPDATE media SET {cols}, updated_at=? WHERE id=?", (*fields.values(), now_iso(), source_id))

    # ── jobs ─────────────────────────────────────────────────────────────
    def insert_job(self, job_id: str, kind: str, project_id: str | None) -> None:
        ts = now_iso()
        with self.connect() as c:
            c.execute("INSERT INTO jobs (id, kind, project_id, status, created_at, updated_at) "
                      "VALUES (?, ?, ?, 'queued', ?, ?)", (job_id, kind, project_id, ts, ts))
            c.execute("INSERT INTO job_checkpoints(job_id, pct, stage, created_at) VALUES (?, 0, 'Queued', ?)",
                      (job_id, ts))

    def update_job(self, job_id: str, **fields: Any) -> None:
        if "result" in fields and fields["result"] is not None and not isinstance(fields["result"], str):
            fields["result"] = json.dumps(fields["result"])
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as c:
            ts = now_iso()
            if "stage" in fields:
                c.execute("INSERT INTO job_checkpoints(job_id, pct, stage, created_at) "
                          "SELECT id, COALESCE(?, pct), ?, ? FROM jobs WHERE id=? AND stage<>?",
                          (fields.get("pct"), fields["stage"], ts, job_id, fields["stage"]))
            c.execute(f"UPDATE jobs SET {cols}, updated_at=? WHERE id=?", (*fields.values(), ts, job_id))

    def job_checkpoints(self, job_id: str) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT pct, stage, created_at FROM job_checkpoints WHERE job_id=? ORDER BY id",
                             (job_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job_dict(row) if row else None

    def list_jobs(self, project_id: str | None = None, limit: int = 20) -> list[dict]:
        with self.connect() as c:
            if project_id:
                rows = c.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY id DESC LIMIT ?",
                                 (project_id, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_job_dict(r) for r in rows]

    def fail_interrupted_jobs(self) -> int:
        """Jobs left 'running' by a previous process that stopped."""
        with self.connect() as c:
            ts = now_iso()
            c.execute("INSERT INTO job_checkpoints(job_id, pct, stage, created_at) "
                      "SELECT id, pct, 'Interrupted', ? FROM jobs WHERE status IN ('queued','running')", (ts,))
            cur = c.execute("UPDATE jobs SET status='failed', stage='Interrupted', "
                            "error='The app was closed while this job was running.', "
                            "updated_at=? WHERE status IN ('queued','running')", (ts,))
            return cur.rowcount

    # ── gameplay library ─────────────────────────────────────────────────
    def insert_clip(self, clip_id: str, path: Path, display_name: str, tags: list[str], fingerprint: dict,
                    sample: bool = False, downloaded: bool = False) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO gameplay_clips (id, path, display_name, tags, fingerprint, sample, created_at, downloaded) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (clip_id, str(path), display_name, json.dumps(tags),
                                                          json.dumps(fingerprint), int(sample), now_iso(), int(downloaded)))

    def list_clips(self) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM gameplay_clips ORDER BY created_at DESC").fetchall()
            used = {r["clip_id"]: r["n"] for r in c.execute(
                "SELECT clip_id, COUNT(*) AS n FROM gameplay_usage GROUP BY clip_id").fetchall()}
        return [_clip_dict(r, used.get(r["id"], 0)) for r in rows]

    def get_clip(self, clip_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM gameplay_clips WHERE id=?", (clip_id,)).fetchone()
            n = c.execute("SELECT COUNT(*) FROM gameplay_usage WHERE clip_id=?", (clip_id,)).fetchone()[0]
        return _clip_dict(row, n) if row else None

    def update_clip(self, clip_id: str, *, display_name: str | None = None, tags: list[str] | None = None) -> None:
        with self.connect() as c:
            if display_name is not None:
                c.execute("UPDATE gameplay_clips SET display_name=? WHERE id=?", (display_name, clip_id))
            if tags is not None:
                c.execute("UPDATE gameplay_clips SET tags=? WHERE id=?", (json.dumps(tags), clip_id))

    def delete_clip(self, clip_id: str) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM gameplay_clips WHERE id=?", (clip_id,))
            c.execute("DELETE FROM gameplay_usage WHERE clip_id=?", (clip_id,))

    def add_usage(self, clip_id: str, in_s: float, out_s: float, project_id: str | None, scene_id: str | None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO gameplay_usage (clip_id, in_s, out_s, project_id, scene_id, used_at) "
                      "VALUES (?, ?, ?, ?, ?, ?)", (clip_id, in_s, out_s, project_id, scene_id, now_iso()))

    def usage(self, clip_id: str) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM gameplay_usage WHERE clip_id=? ORDER BY id", (clip_id,)).fetchall()
        return [dict(r) for r in rows]

    # ── renders ──────────────────────────────────────────────────────────
    def insert_render(self, render_id: str, project_id: str, revision: int, path: Path, verify: dict,
                      warnings: list) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO renders (id, project_id, revision, path, created_at, verify, warnings) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (render_id, project_id, revision, str(path), now_iso(), json.dumps(verify), json.dumps(warnings)))

    def get_render(self, render_id: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM renders WHERE id=?", (render_id,)).fetchone()
        return _render_dict(row) if row else None

    def delete_media(self, source_id: str) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM media WHERE id=?", (source_id,))

    def delete_render(self, render_id: str) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM renders WHERE id=?", (render_id,))

    def delete_project_records(self, project_id: str) -> None:
        """Forget a deleted project's exports and jobs (the job history would point at a project that's gone)."""
        with self.connect() as c:
            c.execute("DELETE FROM renders WHERE project_id=?", (project_id,))
            ids = [r[0] for r in c.execute("SELECT id FROM jobs WHERE project_id=?", (project_id,)).fetchall()]
            c.executemany("DELETE FROM job_checkpoints WHERE job_id=?", [(i,) for i in ids])
            c.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))

    def list_renders(self, project_id: str, limit: int = 20) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM renders WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                             (project_id, limit)).fetchall()
        return [_render_dict(r) for r in rows]


def _clip_dict(row: sqlite3.Row, uses: int) -> dict:
    out = dict(row)
    out["tags"] = json.loads(out["tags"])
    out["fingerprint"] = json.loads(out["fingerprint"])
    out["sample"] = bool(out["sample"])
    out["downloaded"] = bool(out["downloaded"])
    out["uses"] = uses
    out["exists"] = Path(out["path"]).is_file()
    return out


def _job_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["result"] = json.loads(out["result"]) if out.get("result") else None
    return out


def _render_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["verify"] = json.loads(out["verify"])
    out["warnings"] = json.loads(out["warnings"])
    out["exists"] = Path(out["path"]).is_file()
    return out
