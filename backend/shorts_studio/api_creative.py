"""Routes for creating from scratch, narration takes, the gameplay library, samples, overlays and previews."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .config import Settings
from . import providers
from .db import Database
from .jobs import JobError, JobManager
from .media import gameplay, importer, samples
from .project import presets
from .project.store import InvalidProject, ProjectNotFound, ProjectStore
from .render import ffmpeg as ff
from .render import sfx
from .render.engine import RenderError, preview_clip
from .render.raster import RasterStore
from .speech import engines, takes

AUDIO_UPLOAD = {".webm", ".ogg", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".opus", ".mp4", ".mov"}


class ScriptBody(BaseModel):
    kind: str = "script"                      # script | reddit | ranking_list | blank
    text: str = Field(default="", max_length=20000)
    title: str | None = None
    country: str = "US"
    reddit: dict | None = None                # {community, title, source_url}
    gameplay_clip_id: str | None = None
    voice_provider: str | None = None
    from_topic: bool = False


class TakeBody(BaseModel):
    scene_id: str
    text: str = Field(max_length=600)
    provider: str
    voice_id: str = ""
    rate_pct: int = 0
    model_id: str | None = None


class SpeedTakeBody(BaseModel):
    scene_id: str
    text: str = Field(max_length=600)
    audio_name: str
    speed: float = Field(ge=0.5, le=2.5)
    words: list = []
    timing: str = "estimated"


class GameplayAddBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)
    tags: list[str] = []


class GameplayEditBody(BaseModel):
    display_name: str | None = None
    tags: list[str] | None = None


class PickBody(BaseModel):
    seconds: float = Field(gt=0, le=600)
    project_id: str | None = None
    scene_id: str | None = None
    seed: int | None = None


class GameplayProjectBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)
    gameplay_clip_id: str
    layout: str = "split"
    ownership: str = "own"
    country: str = "US"


class ClipBody(BaseModel):
    project: dict
    scene_id: str
    t0: float
    t1: float


def install(app: FastAPI, *, settings: Settings, db: Database, jobs: JobManager, store: ProjectStore,
            ai: providers.ProviderSettings) -> None:
    rasters = RasterStore(settings.raster_dir)

    def load(pid: str):
        try:
            return store.load(pid)
        except ProjectNotFound:
            raise HTTPException(404, "That project doesn't exist.") from None

    # ── create from scratch ──────────────────────────────────────────────
    @app.post("/api/projects/script")
    async def create_from_script(body: ScriptBody):
        if body.country not in ("US", "CA", "BOTH"):
            raise HTTPException(400, "Unknown audience.")
        if body.voice_provider not in (None, "edge", "system", "elevenlabs"):
            raise HTTPException(400, "Unknown voice provider.")
        pick = None
        try:
            if body.gameplay_clip_id:
                pick = await asyncio.to_thread(gameplay.pick, settings, db, body.gameplay_clip_id, 120.0,
                                               project_id=None, scene_id=None)
            if body.kind == "blank":
                doc = presets.blank(title=body.title, country=body.country)
            elif body.kind == "ranking_list":
                doc = presets.ranking_from_lines(body.text, title=body.title, country=body.country)
            elif body.kind in ("script", "reddit"):
                doc = presets.story(body.text, title=body.title, country=body.country,
                                    reddit=body.reddit if body.kind == "reddit" else None, gameplay=pick)
            else:
                raise HTTPException(400, "Unknown starting point.")
            if body.voice_provider == "system":
                doc["voice"] = {"provider": "system", "voice_id": "", "rate_pct": 0}
            elif body.voice_provider == "elevenlabs":
                doc["voice"] = ai.narration_voice()
            if body.from_topic and body.kind == "script":
                doc["origin"]["input"] = "topic"
            if pick:
                importer.ensure_registered(settings, db, jobs, doc)
            doc = store.create(doc)
        except (presets.PresetError, gameplay.GameplayError) as e:
            return JSONResponse({"detail": str(e)}, status_code=422)
        except InvalidProject as e:
            return JSONResponse({"detail": str(e), "issues": [i.to_dict() for i in e.issues]}, status_code=422)
        return {"project": doc, "usernames_replaced": doc["extensions"].get("import", {}).get("usernames_replaced", 0)}

    @app.post("/api/projects/gameplay")
    async def create_clips_over_gameplay(body: GameplayProjectBody):
        if body.layout not in ("split", "pip") or body.country not in ("US", "CA", "BOTH"):
            raise HTTPException(400, "Unknown layout or audience.")
        paths, gameplay_clip_id, layout, country = body.paths, body.gameplay_clip_id, body.layout, body.country
        sources, errors = await asyncio.to_thread(importer.probe_paths, settings, db, jobs, paths,
                                                  ownership=body.ownership)
        if not sources:
            return JSONResponse({"detail": errors[0]["error"] if errors else "No usable files.", "errors": errors},
                                status_code=422)
        total = sum(float(s["fingerprint"]["duration_s"] or 0) for _, s in sources if s["kind"] == "video")
        try:
            pick = await asyncio.to_thread(gameplay.pick, settings, db, gameplay_clip_id, max(1.0, total),
                                           project_id=None, scene_id=None)
            doc = presets.clips_over_gameplay(sources, pick, country=country, layout=layout)
            importer.ensure_registered(settings, db, jobs, doc)
            doc = store.create(doc)
        except (presets.PresetError, gameplay.GameplayError) as e:
            return JSONResponse({"detail": str(e)}, status_code=422)
        return {"project": doc, "import_errors": errors}

    # ── overlays drawn once for preview and export ───────────────────────
    @app.get("/api/raster/{rid}")
    def raster(rid: str):
        rid = rid.removesuffix(".png")
        if not rid.startswith("r") or len(rid) != 32 or not rasters.known(rid):
            raise HTTPException(404, "Unknown overlay.")
        return FileResponse(rasters.ensure(rid), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # ── narration ────────────────────────────────────────────────────────
    @app.get("/api/voices")
    async def voices(provider: str = "edge"):
        if provider == "edge":
            items, online = await asyncio.to_thread(engines.edge_voices)
            return {"provider": "edge", "online": online, "voices": items}
        if provider == "system":
            return {"provider": "system", "online": True, "voices": await asyncio.to_thread(engines.system_voices)}
        if provider == "elevenlabs":
            try:
                entries = await asyncio.to_thread(ai.options, "elevenlabs", "voices")
            except providers.ProviderError as error:
                raise HTTPException(422, str(error)) from None
            return {"provider": provider, "online": True,
                    "voices": [{**entry, "locale": "", "gender": ""} for entry in entries]}
        raise HTTPException(400, "Unknown voice provider.")

    @app.post("/api/projects/{pid}/takes")
    def generate_take(pid: str, body: TakeBody):
        load(pid)
        config = ai.read() if body.provider == "elevenlabs" else None

        def work(ctx):
            ctx.progress(10, "Generating narration" if body.provider == "elevenlabs" else "Speaking the line")
            try:
                take = takes.generate(settings, body.text, body.provider, body.voice_id, body.rate_pct, ctx.cancel,
                                      model_id=body.model_id, config=config,
                                      on_audio=lambda: ctx.progress(80, "Preparing audio and caption timings"))
            except (takes.TakeError, engines.SpeechError, providers.ProviderError) as e:
                raise JobError(str(e)) from e
            return {"scene_id": body.scene_id, "take": take, "speed": body.speed}
        return {"job_id": jobs.submit("take", work, project_id=pid, pool="media")}

    @app.post("/api/projects/{pid}/takes/upload")
    async def upload_take(pid: str, file: UploadFile = File(...), scene_id: str = Form(...), text: str = Form(...),
                          method: str = Form("recorded")):
        load(pid)
        suffix = Path(file.filename or "take.webm").suffix.lower() or ".webm"
        if suffix not in AUDIO_UPLOAD:
            raise HTTPException(400, "That file type isn't a supported recording.")
        fd, tmp = tempfile.mkstemp(suffix=suffix, dir=settings.scratch_dir)
        try:
            with open(fd, "wb") as out:
                while chunk := await file.read(1 << 20):
                    out.write(chunk)
            take = await asyncio.to_thread(takes.from_audio, settings, Path(tmp), text, method)
        except (takes.TakeError, ff.FFmpegError) as e:
            raise HTTPException(422, str(e)) from None
        finally:
            Path(tmp).unlink(missing_ok=True)
        return {"scene_id": scene_id, "take": take}

    @app.post("/api/projects/{pid}/takes/speed")
    async def speed_take(pid: str, body: SpeedTakeBody):
        load(pid)
        try:
            take = await asyncio.to_thread(takes.retempo, settings, body.audio_name, body.text, body.speed,
                                           body.words, body.timing)
        except (takes.TakeError, ff.FFmpegError) as e:
            raise HTTPException(422, str(e)) from None
        return {"scene_id": body.scene_id, "take": take, "speed": body.speed}

    @app.get("/api/takes/{name}")
    def take_audio(name: str):
        p = takes.take_file(settings, name)
        if p is None:
            raise HTTPException(404, "Unknown take.")
        return FileResponse(p, media_type="audio/wav", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/api/sfx/{name}")
    def sound_effect(name: str):
        name = name.removesuffix(".wav")
        if name not in sfx.SOUNDS:
            raise HTTPException(404, "Unknown sound.")
        return FileResponse(sfx.ensure(settings.sfx_dir, name), media_type="audio/wav")

    # ── gameplay library ─────────────────────────────────────────────────
    @app.get("/api/gameplay")
    def list_gameplay():
        return {"clips": db.list_clips()}

    @app.post("/api/gameplay")
    async def add_gameplay(body: GameplayAddBody):
        added, errors = await asyncio.to_thread(gameplay.add, settings, db, jobs, body.paths, body.tags)
        return {"clips": added, "errors": errors}

    @app.post("/api/gameplay/sample")
    def add_sample_gameplay():
        def work(ctx):
            ctx.progress(5, "Generating a sample clip")
            try:
                return {"clip": gameplay.add_sample(settings, db, jobs, ctx.cancel)}
            except gameplay.GameplayError as e:
                raise JobError(str(e)) from e
        return {"job_id": jobs.submit("gameplay_sample", work, pool="media")}

    @app.patch("/api/gameplay/{clip_id}")
    def edit_gameplay(clip_id: str, body: GameplayEditBody):
        if db.get_clip(clip_id) is None:
            raise HTTPException(404, "Unknown clip.")
        tags = sorted({t.strip().lower()[:30] for t in body.tags if t.strip()}) if body.tags is not None else None
        db.update_clip(clip_id, display_name=(body.display_name or "").strip()[:80] or None, tags=tags)
        return db.get_clip(clip_id)

    @app.delete("/api/gameplay/{clip_id}")
    def delete_gameplay(clip_id: str):
        try:
            gameplay.remove(settings, db, clip_id)
        except gameplay.GameplayError as e:
            raise HTTPException(404, str(e)) from None
        return {"ok": True}

    @app.post("/api/gameplay/{clip_id}/pick")
    async def pick_gameplay(clip_id: str, body: PickBody):
        try:
            res = await asyncio.to_thread(gameplay.pick, settings, db, clip_id, body.seconds,
                                          project_id=body.project_id, scene_id=body.scene_id, seed=body.seed)
        except gameplay.GameplayError as e:
            raise HTTPException(404, str(e)) from None
        fp_path = settings.resolve_media_path(res["source"]["path"])
        _kind, _fp, extra = await asyncio.to_thread(importer.probe_file, fp_path)
        importer.register(settings, db, jobs, res["source_id"], res["source"], extra)
        return res

    # ── music ────────────────────────────────────────────────────────────
    @app.post("/api/projects/{pid}/music/sample")
    async def sample_music(pid: str):
        load(pid)
        dest = settings.music_dir / samples.MUSIC_NAME
        if not dest.is_file():
            await asyncio.to_thread(samples.music_loop, dest)
        sources, errors = await asyncio.to_thread(importer.probe_paths, settings, db, jobs, [str(dest)])
        if errors:
            raise HTTPException(500, errors[0]["error"])
        sid, record = sources[0]
        record["origin"] = "generated"
        record["display_name"] = "Generated sample music loop (royalty-free)"
        return {"sources": {sid: record}}

    # ── previews through the export pipeline ─────────────────────────────
    @app.post("/api/projects/{pid}/preview-clip")
    async def preview(pid: str, body: ClipBody):
        from .schema import schema_issues
        if schema_issues(body.project):
            raise HTTPException(422, "The project is not valid.")
        fd, tmp = tempfile.mkstemp(suffix=".mp4", dir=settings.scratch_dir)
        os.close(fd)
        try:
            await asyncio.to_thread(preview_clip, settings, body.project, body.scene_id, body.t0, body.t1, Path(tmp))
            return Response(Path(tmp).read_bytes(), media_type="video/mp4", headers={"Cache-Control": "no-store"})
        except (RenderError, ff.FFmpegError) as e:
            raise HTTPException(422, str(e)) from None
        finally:
            Path(tmp).unlink(missing_ok=True)
