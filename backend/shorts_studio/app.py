"""The FastAPI application: REST API, WebSocket events and the built frontend, on 127.0.0.1 only."""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .config import FRONTEND_DIST, Settings, load_settings
from .db import Database
from .ids import new_id
from .jobs import EventHub, JobError, JobManager
from .media import importer
from .media.probe import SUPPORTED_SUFFIXES
from .project import presets
from .project.relink import check_candidate, check_sources, search_folder
from .project.store import InvalidProject, ProjectNotFound, ProjectStore, ReadOnlyProject, RevisionConflict
from .render import ffmpeg as ff
from .render.engine import RenderError, render_frame, render_project
from .render.raster import RasterStore
from .timeline.resolve import resolve

log = logging.getLogger("shorts_studio")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_UPLOAD_BYTES = 20 * 1024 ** 3


class Guard(BaseHTTPMiddleware):
    """Refuse requests addressed to other host names (DNS rebinding) and writes without the session token."""

    def __init__(self, app, *, allowed_hosts: set[str], token: str):
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.token = token

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        if host not in self.allowed_hosts:
            return JSONResponse({"detail": "Unknown host."}, status_code=421)
        if request.method in WRITE_METHODS and request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("x-studio-token", ""), self.token):
                return JSONResponse({"detail": "Missing or wrong session token. Reload the page."}, status_code=403)
        return await call_next(request)


# ── request bodies ───────────────────────────────────────────────────────
class CreateBody(BaseModel):
    preset: str = "quick_short"               # quick_short | blank | ranking
    paths: list[str] = Field(min_length=1, max_length=50)
    ownership: str = "own"
    title: str | None = None
    country: str = "US"
    direction: str = "descending"


class SaveBody(BaseModel):
    base_revision: int
    project: dict


class PathsBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)
    ownership: str = "own"


class ResolveBody(BaseModel):
    project: dict


class FrameBody(BaseModel):
    project: dict
    t: float = 0.0


class RenderBody(BaseModel):
    revision: int


class DialogBody(BaseModel):
    mode: str = "open_files"
    title: str = "Choose files"


class RelinkCheckBody(BaseModel):
    path: str
    source: dict


class RelinkSearchBody(BaseModel):
    folder: str
    sources: dict[str, dict]


OWNERSHIP = {"own", "licensed", "third_party", "unknown"}


def create_app(settings: Settings | None = None, *, extra_hosts: set[str] | None = None,
               token: str | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.fail_interrupted_jobs()
    hub = EventHub()
    jobs = JobManager(db, hub)
    store = ProjectStore(settings.projects_dir)
    token = token or secrets.token_urlsafe(24)
    port = settings.port
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"} | (extra_hosts or set())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.bind(asyncio.get_running_loop())
        yield
        jobs.shutdown()

    app = FastAPI(title="Shorts Studio", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(Guard, allowed_hosts=allowed, token=token)
    app.state.settings, app.state.db, app.state.jobs, app.state.store, app.state.token = settings, db, jobs, store, token

    def load(pid: str):
        try:
            return store.load(pid)
        except ProjectNotFound:
            raise HTTPException(404, "That project doesn't exist.") from None

    def issues_response(e: InvalidProject, status: int = 422) -> JSONResponse:
        return JSONResponse({"detail": str(e), "issues": [i.to_dict() for i in e.issues]}, status_code=status)

    # ── system ───────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        try:
            ffv = ff.version()
            ff.ffprobe_bin()
            ok = True
        except ff.FFmpegError as e:
            ffv, ok = str(e), False
        return {"ok": ok, "version": __version__, "ffmpeg": ffv, "data_dir": str(settings.data_dir)}

    @app.get("/api/session")
    def session():
        return {"token": token, "version": __version__}

    @app.post("/api/dialog")
    async def dialog(body: DialogBody):
        if body.mode not in ("open_files", "open_file", "open_folder"):
            raise HTTPException(400, "Unknown dialog.")
        try:
            paths = await asyncio.to_thread(importer.native_dialog, body.mode, body.title[:80])
        except (importer.DialogError, subprocess.TimeoutExpired) as e:
            raise HTTPException(500, str(e)) from None
        return {"paths": paths}

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)):
        name = Path(file.filename or "upload").name
        if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise HTTPException(400, f"{name}: this file type isn't supported.")
        folder = settings.imports_dir / new_id("src")[4:14]
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        written = 0
        with dest.open("wb") as out:
            while chunk := await file.read(4 * 1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    out.close()
                    shutil.rmtree(folder, ignore_errors=True)
                    raise HTTPException(413, "That file is too large.")
                out.write(chunk)
        return {"path": str(dest), "size_bytes": written}

    # ── projects ─────────────────────────────────────────────────────────
    @app.get("/api/projects")
    def list_projects():
        out = []
        for s in store.list():
            try:
                doc = store.load(s["id"]).doc
                statuses = check_sources(settings, doc)
                s["missing"] = sum(1 for v in statuses.values() if v != "ok")
            except Exception:  # noqa: BLE001 - one unreadable project must not hide the rest
                s["missing"] = None
            out.append(s)
        return {"projects": out}

    @app.post("/api/projects")
    async def create_project(body: CreateBody):
        if body.preset not in presets.PRESETS:
            raise HTTPException(400, f"Unknown preset {body.preset}.")
        if body.ownership not in OWNERSHIP:
            raise HTTPException(400, "Unknown ownership.")
        if body.country not in ("US", "CA", "BOTH"):
            raise HTTPException(400, "Unknown audience.")
        if body.direction not in ("descending", "ascending"):
            raise HTTPException(400, "Unknown ranking direction.")
        sources, errors = await asyncio.to_thread(importer.probe_paths, settings, db, jobs, body.paths,
                                                  ownership=body.ownership)
        if not sources:
            return JSONResponse({"detail": errors[0]["error"] if errors else "No usable files.", "errors": errors},
                                status_code=422)
        try:
            extra = {"direction": body.direction} if body.preset == "ranking" else {}
            doc = presets.PRESETS[body.preset](sources, title=body.title, country=body.country, **extra)
            doc = store.create(doc)
        except presets.PresetError as e:
            return JSONResponse({"detail": str(e), "errors": errors}, status_code=422)
        except InvalidProject as e:
            return issues_response(e)
        return {"project": doc, "import_errors": errors}

    @app.get("/api/projects/{pid}")
    async def get_project(pid: str):
        loaded = load(pid)
        doc = loaded.doc
        await asyncio.to_thread(importer.ensure_registered, settings, db, jobs, doc)
        statuses = await asyncio.to_thread(check_sources, settings, doc)
        return {"project": doc, "read_only": loaded.read_only, "statuses": statuses,
                "renders": db.list_renders(pid, limit=10)}

    @app.put("/api/projects/{pid}")
    async def save_project(pid: str, body: SaveBody):
        try:
            doc = await asyncio.to_thread(store.save, pid, body.project, body.base_revision)
        except ProjectNotFound:
            raise HTTPException(404, "That project doesn't exist.") from None
        except RevisionConflict as e:
            return JSONResponse({"detail": "This project was saved from another tab or window.",
                                 "current_revision": e.current}, status_code=409)
        except ReadOnlyProject:
            raise HTTPException(423, "This project was saved by a newer version of Shorts Studio.") from None
        except InvalidProject as e:
            return issues_response(e)
        await asyncio.to_thread(importer.ensure_registered, settings, db, jobs, doc)
        return {"revision": doc["revision"], "updated_at": doc["updated_at"]}

    @app.post("/api/projects/{pid}/sources")
    async def add_sources(pid: str, body: PathsBody):
        load(pid)
        if body.ownership not in OWNERSHIP:
            raise HTTPException(400, "Unknown ownership.")
        sources, errors = await asyncio.to_thread(importer.probe_paths, settings, db, jobs, body.paths,
                                                  ownership=body.ownership)
        return {"sources": dict(sources), "errors": errors}

    raster_store = RasterStore(settings.raster_dir)

    @app.post("/api/resolve")
    async def resolve_doc(body: ResolveBody):
        from .schema import schema_issues
        issues = schema_issues(body.project)
        if issues:
            return JSONResponse({"detail": issues[0].message, "issues": [i.to_dict() for i in issues]},
                                status_code=422)
        statuses = await asyncio.to_thread(check_sources, settings, body.project)
        timeline = resolve(body.project, statuses)
        # Overlay images are described by specs; the preview fetches them by id from /api/raster/<id>.
        await asyncio.to_thread(raster_store.register, timeline.pop("rasters"))
        return timeline

    @app.post("/api/projects/{pid}/frame")
    async def exact_frame(pid: str, body: FrameBody):
        from .schema import schema_issues
        if schema_issues(body.project):
            raise HTTPException(422, "The project is not valid.")
        fd, tmp = tempfile.mkstemp(suffix=".png", dir=settings.scratch_dir)
        os.close(fd)
        try:
            await asyncio.to_thread(render_frame, settings, body.project, body.t, Path(tmp))
            return Response(Path(tmp).read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})
        except (RenderError, ff.FFmpegError) as e:
            raise HTTPException(422, str(e)) from None
        finally:
            Path(tmp).unlink(missing_ok=True)

    @app.post("/api/projects/{pid}/render")
    def start_render(pid: str, body: RenderBody):
        loaded = load(pid)
        if loaded.doc["revision"] != body.revision:
            return JSONResponse({"detail": "Save the project before exporting.",
                                 "current_revision": loaded.doc["revision"]}, status_code=409)
        snapshot = copy.deepcopy(loaded.doc)
        renders_dir = store.renders_dir(pid)

        def work(ctx):
            try:
                return render_project(settings, db, snapshot, renders_dir, job_id=ctx.job_id, cancel=ctx.cancel,
                                      progress=ctx.progress)
            except RenderError as e:
                raise JobError(str(e), {"issues": e.issues, "verify": e.verify}) from e
        job_id = jobs.submit("render", work, project_id=pid)
        return {"job_id": job_id}

    @app.get("/api/projects/{pid}/renders")
    def list_renders(pid: str):
        load(pid)
        return {"renders": db.list_renders(pid)}

    # ── relink ───────────────────────────────────────────────────────────
    @app.post("/api/relink/check")
    async def relink_check(body: RelinkCheckBody):
        path = Path(body.path)
        if not path.is_file():
            raise HTTPException(404, "That file doesn't exist.")
        result = await asyncio.to_thread(check_candidate, path, body.source)
        if result.get("ok"):
            result["project_path"] = settings.to_project_path(path)
        return result

    @app.post("/api/relink/search")
    async def relink_search(body: RelinkSearchBody):
        folder = Path(body.folder)
        if not folder.is_dir():
            raise HTTPException(404, "That folder doesn't exist.")
        found = await asyncio.to_thread(search_folder, folder, body.sources)
        out = {}
        for sid, p in found.items():
            res = await asyncio.to_thread(check_candidate, Path(p), body.sources[sid])
            if res.get("ok"):
                out[sid] = {"path": p, "project_path": settings.to_project_path(Path(p)),
                            "fingerprint": res["fingerprint"]}
        return {"found": out}

    # ── media ────────────────────────────────────────────────────────────
    def media_row(source_id: str) -> dict:
        row = db.get_media(source_id)
        if row is None:
            raise HTTPException(404, "Unknown media.")
        return row

    @app.get("/api/media/{source_id}/info")
    def media_info(source_id: str):
        row = media_row(source_id)
        return {"source_id": source_id, "proxy_state": row["proxy_state"], "has_poster": bool(row["poster"]),
                "has_filmstrip": bool(row["filmstrip"]), "probe": row["probe"],
                "exists": Path(row["path"]).is_file()}

    @app.get("/api/media/{source_id}/file")
    def media_file(source_id: str, variant: str = "preview"):
        row = media_row(source_id)
        path = Path(row["path"])
        if variant == "preview" and row["proxy_state"] == "ready" and row["proxy"] and Path(row["proxy"]).is_file():
            path = Path(row["proxy"])
        if not path.is_file():
            raise HTTPException(404, "The file is missing.")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/api/media/{source_id}/{asset}")
    def media_asset(source_id: str, asset: str):
        if asset not in ("poster", "filmstrip"):
            raise HTTPException(404)
        row = media_row(source_id)
        p = row.get(asset)
        if not p or not Path(p).is_file():
            raise HTTPException(404, "Not ready yet.")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    # ── jobs and renders ─────────────────────────────────────────────────
    @app.get("/api/jobs")
    def list_jobs(project_id: str | None = None):
        return {"jobs": db.list_jobs(project_id)}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return job

    @app.get("/api/jobs/{job_id}/checkpoints")
    def job_checkpoints(job_id: str):
        if db.get_job(job_id) is None:
            raise HTTPException(404, "Unknown job.")
        return {"checkpoints": db.job_checkpoints(job_id)}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return {"cancelled": jobs.cancel(job_id)}

    def render_row(render_id: str) -> dict:
        r = db.get_render(render_id)
        if r is None:
            raise HTTPException(404, "Unknown render.")
        return r

    @app.get("/api/renders/{render_id}")
    def get_render(render_id: str):
        return render_row(render_id)

    @app.get("/api/renders/{render_id}/file")
    def render_file(render_id: str):
        r = render_row(render_id)
        if not r["exists"]:
            raise HTTPException(404, "The file was moved or deleted.")
        return FileResponse(r["path"], media_type="video/mp4")

    @app.post("/api/renders/{render_id}/open")
    def open_render(render_id: str):
        r = render_row(render_id)
        if not r["exists"]:
            raise HTTPException(404, "The file was moved or deleted.")
        _open_with_os(Path(r["path"]), reveal=False)
        return {"ok": True}

    @app.post("/api/renders/{render_id}/reveal")
    def reveal_render(render_id: str):
        r = render_row(render_id)
        if not r["exists"]:
            raise HTTPException(404, "The file was moved or deleted.")
        _open_with_os(Path(r["path"]), reveal=True)
        return {"ok": True}

    # ── events ───────────────────────────────────────────────────────────
    @app.websocket("/api/ws")
    async def events(ws: WebSocket):
        host = (ws.headers.get("host") or "").lower()
        if host not in allowed or not secrets.compare_digest(ws.query_params.get("token", ""), token):
            await ws.close(code=4403)
            return
        await ws.accept()
        q = hub.subscribe()
        try:
            await ws.send_json({"type": "hello", "version": __version__})
            while True:
                event = await q.get()
                await ws.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.unsubscribe(q)

    from . import api_cleanup, api_creative, api_workflows, providers
    api_cleanup.install(app, settings=settings, db=db, store=store)
    ai = providers.ProviderSettings(settings)
    api_creative.install(app, settings=settings, db=db, jobs=jobs, store=store, ai=ai)
    api_workflows.install(app, settings=settings, db=db, jobs=jobs, store=store, ai=ai)

    # ── frontend ─────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        page = FRONTEND_DIST / "index.html"
        if not page.is_file():
            return JSONResponse({"detail": "The frontend isn't built. Run scripts\\setup.ps1 (or npm run build in "
                                 "frontend/)."}, status_code=503)
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/assets/{name:path}")
    def assets(name: str):
        base = (FRONTEND_DIST / "assets").resolve()
        p = (base / name).resolve()
        if base not in p.parents or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p)

    @app.get("/{name}")
    def root_file(name: str):
        p = (FRONTEND_DIST / name).resolve()
        if p.parent != FRONTEND_DIST.resolve() or not p.is_file() or name == "index.html":
            raise HTTPException(404)
        return FileResponse(p)

    return app


def _open_with_os(path: Path, *, reveal: bool) -> None:
    if sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            os.startfile(str(path))  # noqa: S606 - a render id was resolved to a file the app wrote
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])
