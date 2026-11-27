"""Where things live and which address the app binds to.

Every path is derived from one data folder (``data/`` in the repo by default, or ``SHORTS_STUDIO_DATA``),
so the app never touches another install's files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "project.v1.schema.json"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17860


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "media" / "imports"

    @property
    def derived_dir(self) -> Path:
        """Posters, filmstrips and preview proxies."""
        return self.data_dir / "media" / "derived"

    @property
    def segment_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "segments"

    @property
    def scratch_dir(self) -> Path:
        return self.data_dir / "cache" / "scratch"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def raster_dir(self) -> Path:
        return self.data_dir / "cache" / "raster"

    @property
    def sfx_dir(self) -> Path:
        return self.data_dir / "cache" / "sfx"

    @property
    def takes_dir(self) -> Path:
        """Voice takes, including your recordings: project data, never pruned like the caches."""
        return self.data_dir / "takes"

    @property
    def gameplay_dir(self) -> Path:
        return self.data_dir / "gameplay"

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "music"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.projects_dir, self.imports_dir, self.derived_dir, self.segment_cache_dir,
                  self.scratch_dir, self.logs_dir, self.raster_dir, self.sfx_dir, self.takes_dir, self.gameplay_dir,
                  self.music_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_media_path(self, path: str) -> Path:
        """A source path from a project: absolute, or ``data:`` relative to the data folder."""
        if path.startswith("data:"):
            return (self.data_dir / path[len("data:"):]).resolve()
        return Path(path)

    def to_project_path(self, path: Path) -> str:
        """Store files inside the data folder as ``data:`` paths so the folder can be moved."""
        path = path.resolve()
        try:
            rel = path.relative_to(self.data_dir.resolve())
        except ValueError:
            return path.as_posix()
        return "data:" + rel.as_posix()


def load_settings() -> Settings:
    data = Path(os.environ.get("SHORTS_STUDIO_DATA") or (REPO_ROOT / "data")).resolve()
    host = os.environ.get("SHORTS_STUDIO_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SHORTS_STUDIO_PORT", DEFAULT_PORT))
    return Settings(data_dir=data, host=host, port=port)
