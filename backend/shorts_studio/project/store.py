"""Project files: data/projects/<id>/project.json is the source of truth.

Saves are atomic (write a temp file, flush, fsync, os.replace) and revision-checked: a save names the revision
it was based on, and a mismatch is refused so a second tab can't silently overwrite the first. The previous
revision is kept, gzipped, in history/ (the last HISTORY_KEEP of them).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from ..db import now_iso
from ..schema import Issue, errors_only, migrate, validate_document

HISTORY_KEEP = 50
_ID_RE = re.compile(r"^prj_[0-9A-Za-z]{6,32}$")


class ProjectNotFound(Exception):
    pass


class RevisionConflict(Exception):
    def __init__(self, current: int):
        super().__init__(f"The project is at revision {current}.")
        self.current = current


class InvalidProject(Exception):
    def __init__(self, issues: list[Issue]):
        super().__init__("; ".join(i.message for i in issues[:3]))
        self.issues = issues


class ReadOnlyProject(Exception):
    pass


@dataclass
class Loaded:
    doc: dict
    read_only: bool
    path: Path


class ProjectStore:
    def __init__(self, projects_dir: Path):
        self.root = projects_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, project_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def dir_for(self, project_id: str) -> Path:
        if not _ID_RE.match(project_id):
            raise ProjectNotFound(project_id)
        return self.root / project_id

    def file_for(self, project_id: str) -> Path:
        return self.dir_for(project_id) / "project.json"

    def renders_dir(self, project_id: str) -> Path:
        d = self.dir_for(project_id) / "renders"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── create / load / save ─────────────────────────────────────────────
    def create(self, doc: dict) -> dict:
        issues = errors_only(validate_document(doc))
        if issues:
            raise InvalidProject(issues)
        pid = doc["id"]
        with self._lock(pid):
            folder = self.dir_for(pid)
            if folder.exists():
                raise FileExistsError(pid)
            (folder / "history").mkdir(parents=True)
            doc = {**doc, "revision": 1, "updated_at": now_iso()}
            _atomic_write_json(folder / "project.json", doc)
        return doc

    def load(self, project_id: str) -> Loaded:
        path = self.file_for(project_id)
        if not path.is_file():
            raise ProjectNotFound(project_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc, read_only = migrate(raw)
        if not read_only and doc is not raw and doc.get("schema_version") != raw.get("schema_version"):
            backup = path.parent / "history" / f"pre-migration-v{raw['schema_version']}.json"
            if not backup.exists():
                shutil.copy2(path, backup)
        return Loaded(doc=doc, read_only=read_only, path=path)

    def save(self, project_id: str, doc: dict, base_revision: int) -> dict:
        if doc.get("id") != project_id:
            raise InvalidProject([Issue("id_mismatch", "The document's id does not match the project being saved.")])
        with self._lock(project_id):
            current = self.load(project_id)
            if current.read_only:
                raise ReadOnlyProject(project_id)
            if current.doc["revision"] != base_revision:
                raise RevisionConflict(current.doc["revision"])
            new = {**doc, "revision": base_revision + 1, "updated_at": now_iso(),
                   "created_at": current.doc["created_at"]}
            issues = errors_only(validate_document(new))
            if issues:
                raise InvalidProject(issues)
            self._keep_history(current.path, current.doc["revision"])
            _atomic_write_json(current.path, new)
        return new

    def _keep_history(self, path: Path, revision: int) -> None:
        hist = path.parent / "history"
        hist.mkdir(exist_ok=True)
        with path.open("rb") as src, gzip.open(hist / f"rev-{revision:06d}.json.gz", "wb") as dst:
            shutil.copyfileobj(src, dst)
        revs = sorted(hist.glob("rev-*.json.gz"))
        for old in revs[:-HISTORY_KEEP]:
            old.unlink(missing_ok=True)

    def history(self, project_id: str) -> list[int]:
        hist = self.dir_for(project_id) / "history"
        return sorted(int(p.name[4:10]) for p in hist.glob("rev-*.json.gz"))

    def load_revision(self, project_id: str, revision: int) -> dict:
        p = self.dir_for(project_id) / "history" / f"rev-{revision:06d}.json.gz"
        if not p.is_file():
            raise ProjectNotFound(f"{project_id}@{revision}")
        with gzip.open(p, "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def delete(self, project_id: str, remove) -> None:
        """Remove the project's folder (document, history, exports) with ``remove`` (a list-of-paths deleter)."""
        folder = self.dir_for(project_id)
        if not (folder / "project.json").is_file():
            raise ProjectNotFound(project_id)
        with self._lock(project_id):
            remove([folder])

    # ── listing ──────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        out = []
        for f in self.root.glob("prj_*/project.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append(summary(doc))
        out.sort(key=lambda s: s["updated_at"], reverse=True)
        return out


def summary(doc: dict) -> dict:
    scenes = [s for s in doc.get("scenes", []) if s.get("enabled")]
    first_source = None
    for s in scenes:
        layer = s["layers"]["primary"]
        if layer["type"] == "segment":
            seg = doc["segments"].get(layer["segment_id"])
            first_source = seg["source_id"] if seg else None
        elif layer["type"] == "image":
            first_source = layer.get("source_id")
        if first_source:
            break
    return {"id": doc["id"], "title": doc["title"], "updated_at": doc["updated_at"], "revision": doc["revision"],
            "preset": doc.get("origin", {}).get("preset"), "scene_count": len(scenes),
            "schema_version": doc.get("schema_version"), "poster_source_id": first_source}


def _atomic_write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
