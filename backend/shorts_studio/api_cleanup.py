"""Free up space: delete old exports, or a whole project with the media only it uses. Everything goes to the
Recycle Bin on Windows (see trash.py).

What a project delete removes: its folder (project file, saved history, exported MP4s), its database records (exports,
jobs, media cache rows), its thumbnails and preview copies, and the files it copied or downloaded into the app's data
folder (data/media/...) when no other project uses them. Never removed: your own files linked from elsewhere on disk,
the gameplay library, and voice takes (they are shared by text and voice, so other projects may reuse them).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import trash
from .config import Settings
from .db import Database
from .project.store import ProjectNotFound, ProjectStore


class PruneBody(BaseModel):
    keep: int = 1          # how many of the newest exports to keep


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _size(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return total


def plan_project_delete(settings: Settings, db: Database, store: ProjectStore, pid: str) -> dict:
    """What deleting project ``pid`` would remove, without removing anything."""
    doc = store.load(pid).doc
    others: list[dict] = []
    for s in store.list():
        if s["id"] != pid:
            try:
                others.append(store.load(s["id"]).doc)
            except Exception:  # noqa: BLE001 - an unreadable project still counts as "may use anything": keep all
                return {"error": f"Project {s['id']} couldn't be read, so shared media can't be checked."}
    used_elsewhere = {settings.resolve_media_path(src["path"]).resolve() for o in others for src in o["sources"].values()}
    ids_elsewhere = {sid for o in others for sid in o["sources"]}
    media_root = settings.data_dir / "media"
    media_files, derived = [], []
    for sid, src in doc["sources"].items():
        p = settings.resolve_media_path(src["path"])
        # Only files the app copied or downloaded into its own data folder; never the gameplay library.
        if _inside(p, media_root) and p.resolve() not in used_elsewhere and p.is_file():
            media_files.append(p)
        if sid not in ids_elsewhere and (settings.derived_dir / sid).is_dir():
            derived.append(settings.derived_dir / sid)
    folder = store.dir_for(pid)
    renders = [Path(r["path"]) for r in db.list_renders(pid, limit=10_000) if r["exists"]]
    return {"project": folder, "renders": renders, "media": sorted(set(media_files)), "derived": derived,
            "source_ids": [sid for sid in doc["sources"] if sid not in ids_elsewhere],
            "title": doc["title"]}


def install(app: FastAPI, *, settings: Settings, db: Database, store: ProjectStore) -> None:
    def load_plan(pid: str) -> dict:
        try:
            plan = plan_project_delete(settings, db, store, pid)
        except (ProjectNotFound, ValueError):
            raise HTTPException(404, "That project doesn't exist.") from None
        if "error" in plan:
            raise HTTPException(409, plan["error"])
        return plan

    @app.get("/api/projects/{pid}/delete-preview")
    def delete_preview(pid: str):
        plan = load_plan(pid)
        return {"title": plan["title"], "exports": len(plan["renders"]),
                "exports_bytes": _size(plan["renders"]), "media_files": [p.name for p in plan["media"]],
                "media_bytes": _size(plan["media"]),
                "total_bytes": _size([plan["project"], *plan["media"], *plan["derived"]])}

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str):
        plan = load_plan(pid)
        freed = _size([plan["project"], *plan["media"], *plan["derived"]])
        recycled = trash.to_trash([*plan["media"], *plan["derived"]])
        try:
            store.delete(pid, trash.to_trash)
        except ProjectNotFound:
            raise HTTPException(404, "That project doesn't exist.") from None
        for p in plan["media"]:              # tidy the per-import folder the copied file lived in, if now empty
            parent = p.parent
            if _inside(parent, settings.data_dir / "media") and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        db.delete_project_records(pid)
        for sid in plan["source_ids"]:
            db.delete_media(sid)
        return {"ok": True, "freed_bytes": freed, "recycle_bin": recycled}

    @app.delete("/api/renders/{render_id}")
    def delete_render(render_id: str):
        r = db.get_render(render_id)
        if r is None:
            raise HTTPException(404, "Unknown export.")
        path = Path(r["path"])
        if not _inside(path, settings.projects_dir):       # only files the app wrote into a project's renders folder
            raise HTTPException(400, "That export isn't inside the app's projects folder, so it wasn't deleted.")
        size = path.stat().st_size if path.is_file() else 0
        recycled = trash.to_trash([path])
        db.delete_render(render_id)
        return {"ok": True, "freed_bytes": size, "recycle_bin": recycled}

    @app.post("/api/projects/{pid}/renders/prune")
    def prune_renders(pid: str, body: PruneBody):
        try:
            store.dir_for(pid)
        except ProjectNotFound:
            raise HTTPException(404, "That project doesn't exist.") from None
        keep = max(0, body.keep)
        rows = db.list_renders(pid, limit=10_000)              # newest first
        old = rows[keep:]
        paths = [Path(r["path"]) for r in old if r["exists"] and _inside(Path(r["path"]), settings.projects_dir)]
        freed = _size(paths)
        recycled = trash.to_trash(paths)
        for r in old:
            db.delete_render(r["id"])
        return {"ok": True, "deleted": len(old), "freed_bytes": freed, "recycle_bin": recycled}
