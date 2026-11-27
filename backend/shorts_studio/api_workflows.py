"""URL imports and optional AI creation tasks use the same projects, library and jobs as local workflows."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from . import intro, providers, publish
from .config import Settings
from .db import Database
from .ids import new_id
from .jobs import JobContext, JobError, JobManager
from .media import download, gameplay, importer
from .media.probe import ProbeError, probe_file
from .project import defaults, presets
from .project.store import InvalidProject, ProjectNotFound, ProjectStore


class UrlImport(BaseModel):
    youtube: str = Field(default="", max_length=4000)
    instagram: str = Field(default="", max_length=4000)
    gameplay: str = Field(default="", max_length=4000)
    layout: Literal["split", "pip"] = "split"
    country: Literal["US", "CA", "BOTH"] = "US"
    tags: list[str] = Field(default_factory=list, max_length=25)


class DraftRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    country: Literal["US", "CA", "BOTH"] = "US"


class IntroRequest(BaseModel):
    revision: int = Field(ge=1)
    notes: str = Field(default="", max_length=500)


def _import_urls(settings: Settings, db: Database, jobs: JobManager, store: ProjectStore, ctx: JobContext,
                 body: UrlImport, links: list[tuple[str, str]]) -> dict:
    sources = []
    background = None
    with tempfile.TemporaryDirectory(dir=settings.scratch_dir, prefix="url-") as tmp:
        for index, (role, url) in enumerate(links):
            label = {"youtube": "YouTube video", "instagram": "Instagram Reel", "gameplay": "gameplay video"}[role]
            start = 5 + (70 * index / len(links))
            stage = f"Downloading {label}"
            ctx.progress(start, stage)
            try:
                path, name = download.fetch(url, Path(tmp) / role, ctx.cancel,
                                            lambda fraction: ctx.progress(start + (65 / len(links)) * fraction, stage))
                ctx.progress(start + 67 / len(links), f"Checking {label}")
                kind, fingerprint, extra = probe_file(path)
                if kind != "video" or (fingerprint["duration_s"] or 0) < 1 / 30:
                    raise download.DownloadError("The downloaded file has no usable video frames.")
            except (download.DownloadError, ProbeError) as error:
                reason = str(error) if isinstance(error, download.DownloadError) else "The downloaded file is not a usable video."
                raise JobError(f"{label[0].upper()}{label[1:]}: {reason}") from None
            if role == "gameplay":
                background = path, name
            else:
                sources.append((path, name, url, fingerprint, extra))

        ctx.cancel.check("finish video import")
        clip_id = None
        if background:
            ctx.progress(80, "Saving gameplay to the library")
            path, name = background
            clips, errors = gameplay.add(settings, db, jobs, [str(path)], body.tags, downloaded=True, display_name=name)
            if errors or not clips:
                raise JobError("Couldn’t save the downloaded gameplay in the library.")
            clip_id = clips[0]["id"]
        if not sources:
            return {"clip_id": clip_id}

        ctx.progress(90, "Creating the editable short")
        media_dir = settings.imports_dir / ctx.job_id
        media_dir.mkdir()
        imports = []
        try:
            for index, (path, name, url, fingerprint, extra) in enumerate(sources, 1):
                local_path = media_dir / f"source-{index}{path.suffix}"
                path.replace(local_path)
                source = defaults.source_record("video", settings.to_project_path(local_path), name, fingerprint,
                                                origin="url_download", ownership="third_party")
                source["url"] = url
                imports.append((new_id("src"), source, extra))
            records = [(source_id, record) for source_id, record, _ in imports]
            seconds = defaults.QUICK_SHORT_DEFAULT_S
            if clip_id:
                duration = sum(min(seconds, entry[3]["duration_s"]) for entry in sources)
                pick = gameplay.pick(settings, db, clip_id, duration, project_id=None, scene_id=None)
                doc = presets.clips_over_gameplay(records, pick, title=sources[0][1], country=body.country,
                                                  layout=body.layout, entry_seconds=seconds)
            elif len(records) == 1:
                doc = presets.quick_short(records, title=sources[0][1], country=body.country)
            else:
                doc = presets.from_files(records, title=sources[0][1], country=body.country, entry_seconds=seconds)
            doc["origin"]["input"] = "url"
            doc["publish_meta"]["source_links"] = [entry[2] for entry in sources]
            doc = store.create(doc)
        except (OSError, presets.PresetError, gameplay.GameplayError, InvalidProject):
            shutil.rmtree(media_dir, ignore_errors=True)
            raise JobError("Couldn’t create an editable project from these videos.") from None
        for source_id, source, extra in imports:
            importer.register(settings, db, jobs, source_id, source, extra)
        if clip_id:
            importer.ensure_registered(settings, db, jobs, doc)
        return {"project_id": doc["id"], "clip_id": clip_id}


def install(app: FastAPI, *, settings: Settings, db: Database, jobs: JobManager,
            store: ProjectStore, ai: providers.ProviderSettings) -> None:
    @app.post("/api/urls/import")
    def import_urls(body: UrlImport):
        links = [(role, getattr(body, role).strip()) for role in ("youtube", "instagram", "gameplay")
                 if getattr(body, role).strip()]
        if not links:
            raise HTTPException(422, "Add at least one video link.")
        try:
            for role, link in links:
                download.checked_url(link, None if role == "gameplay" else role)
        except download.DownloadError as error:
            raise HTTPException(422, str(error)) from None
        return {"job_id": jobs.submit("url_import", lambda ctx: _import_urls(settings, db, jobs, store, ctx, body, links),
                                      pool="media")}

    @app.get("/api/providers")
    def provider_status():
        return ai.public()

    @app.put("/api/providers")
    async def configure_providers(request: Request):
        try:
            body = providers.SettingsUpdate.model_validate(await request.json())
            return ai.update(body)
        except providers.ProviderSettingError as error:
            raise HTTPException(422, str(error)) from None
        except ValidationError as error:
            fields = [entry["loc"][0] for entry in error.errors(include_input=False) if entry["loc"]]
            message = providers.SETTING_ERRORS.get(fields[0]) if fields else None
            raise HTTPException(422, message or "The app received invalid provider settings.") from None
        except ValueError:
            raise HTTPException(422, "The app received invalid provider settings.") from None
        except OSError:
            raise HTTPException(500, "The local provider settings could not be saved.") from None

    @app.get("/api/providers/{provider}/options")
    def provider_options(provider: Literal["opencode", "elevenlabs"], kind: Literal["models", "voices"] = "models"):
        try:
            return {"options": ai.options(provider, kind)}
        except providers.ProviderError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/providers/opencode/access")
    def check_opencode_access():
        try:
            ai.check_go_access()
        except providers.ProviderError as error:
            raise HTTPException(422, str(error)) from None
        return {"ok": True}

    @app.post("/api/drafts/topic")
    def script_draft(body: DraftRequest):
        config = ai.read()
        if not body.topic.strip():
            raise HTTPException(422, "Enter a topic to draft a script.")
        if not config.get("OPENCODE_GO_API_KEY") or not config.get("OPENCODE_GO_MODEL"):
            raise HTTPException(422, "Save an OpenCode Go key and choose a writing model in AI settings.")

        def work(ctx: JobContext) -> dict:
            ctx.progress(10, "Requesting a draft from OpenCode Go")
            try:
                script = providers.script(config, body.topic.strip(), body.country, ctx.job_id)
            except providers.ProviderError as error:
                raise JobError(str(error)) from None
            ctx.cancel.check("draft script")
            ctx.progress(95, "Draft ready for review")
            return {"script": script, "country": body.country}

        return {"job_id": jobs.submit("script_draft", work, pool="media")}

    @app.post("/api/projects/{project_id}/publish-draft")
    def publish_draft(project_id: str, body: IntroRequest):
        try:
            loaded = store.load(project_id)
        except (ProjectNotFound, ValueError):
            raise HTTPException(404, "That project doesn't exist.") from None
        if loaded.doc["revision"] != body.revision:
            raise HTTPException(409, "Save or reload the latest project before writing upload details.")
        if not any(s["enabled"] for s in loaded.doc["scenes"]):
            raise HTTPException(422, "Add a scene to the timeline first.")
        config = ai.read()
        if not config.get("OPENCODE_GO_API_KEY") or not config.get("OPENCODE_GO_MODEL"):
            raise HTTPException(422, "Save an OpenCode Go API key and writing model in AI settings first.")
        job_id = jobs.submit("publish_draft", lambda ctx: publish.draft(settings, config, loaded.doc, body.notes, ctx),
                             project_id=project_id, pool="media")
        return {"job_id": job_id}

    @app.post("/api/projects/{project_id}/intro-draft")
    def intro_draft(project_id: str, body: IntroRequest):
        try:
            loaded = store.load(project_id)
        except (ProjectNotFound, ValueError):
            raise HTTPException(404, "That project doesn't exist.") from None
        if loaded.read_only or loaded.doc["revision"] != body.revision:
            raise HTTPException(409, "Save or reload the latest project before drafting an intro.")
        try:
            intro.opening_clip(loaded.doc)
        except JobError as error:
            raise HTTPException(422, str(error)) from None
        config = ai.read()
        if not config.get("OPENCODE_GO_API_KEY") or not config.get("OPENCODE_GO_MODEL"):
            raise HTTPException(422, "Save an OpenCode Go API key and writing model in AI settings first.")
        job_id = jobs.submit("intro_draft", lambda ctx: intro.draft(settings, config, loaded.doc, body.notes, ctx),
                             project_id=project_id, pool="media")
        return {"job_id": job_id}
