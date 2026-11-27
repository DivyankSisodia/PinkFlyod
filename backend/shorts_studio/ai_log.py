"""A log of every OpenCode Go API call the app makes: one JSON object per line in ``data/logs/opencode-api.jsonl``.

Each entry has the request (URL, method, headers, body) and the response (status, body) or the error, with timing.
API keys never reach the file: the Authorization header is masked and the key is scrubbed from every string.
Video frames sent to vision models are replaced by a short note with their type and size, so the log stays readable.
The file rotates at 20 MB, keeping three older files (``.1`` to ``.3``). Logging can never break the API call.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .ids import new_id

FILE_NAME = "opencode-api.jsonl"
MAX_BYTES = 20 * 1024 * 1024
KEEP = 3
_DATA_URL = re.compile(r"^data:([\w/+.-]+);base64,(.*)$", re.S)
_SECRET_HEADERS = {"authorization", "xi-api-key", "x-api-key", "api-key"}
_lock = threading.Lock()
_path: Path | None = None
log = logging.getLogger("shorts_studio.ai_log")


def configure(logs_dir: Path) -> Path:
    """Where entries go. Called once when the app starts; until then nothing is written."""
    global _path
    logs_dir.mkdir(parents=True, exist_ok=True)
    _path = logs_dir / FILE_NAME
    return _path


def path() -> Path | None:
    return _path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _scrub(value, secrets: list[str]):
    """A copy of ``value`` with secrets masked and base64 data URLs summarised."""
    if isinstance(value, str):
        m = _DATA_URL.match(value)
        if m:
            return f"<{m.group(1)} base64, {len(m.group(2)) * 3 // 4} bytes, omitted>"
        for s in secrets:
            if s:
                value = value.replace(s, "***")
        return value
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    return value


def headers(raw: dict) -> tuple[dict, list[str]]:
    """(headers safe to log, the secret values found in them)."""
    safe, secrets = {}, []
    for k, v in raw.items():
        if k.lower() in _SECRET_HEADERS:
            token = str(v).removeprefix("Bearer ").strip()
            secrets.append(token)
            safe[k] = ("Bearer ***" if str(v).startswith("Bearer ") else "***")
        else:
            safe[k] = v
    return safe, secrets


def body(raw: bytes | None):
    """A response or request body for the log: parsed JSON when it is JSON, else text (cut at 64 KB)."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        text = raw.decode("utf-8", "replace")
        return text if len(text) <= 65536 else text[:65536] + f"… ({len(text)} characters)"


def new_call_id() -> str:
    return "call_" + new_id("job")[4:]


def write(entry: dict, secrets: list[str]) -> None:
    if _path is None:
        return
    try:
        line = json.dumps({"ts": _now(), **_scrub(entry, secrets)}, ensure_ascii=False, default=str)
        with _lock:
            if _path.exists() and _path.stat().st_size + len(line) > MAX_BYTES:
                _rotate(_path)
            with _path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001 - a full disk or a locked file must not fail the API call
        log.warning("Couldn't write the OpenCode API log", exc_info=True)


def _rotate(p: Path) -> None:
    oldest = p.with_name(f"{p.name}.{KEEP}")
    oldest.unlink(missing_ok=True)
    for i in range(KEEP - 1, 0, -1):
        src = p.with_name(f"{p.name}.{i}")
        if src.exists():
            src.replace(p.with_name(f"{p.name}.{i + 1}"))
    p.replace(p.with_name(f"{p.name}.1"))
