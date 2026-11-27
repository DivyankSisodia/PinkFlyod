from __future__ import annotations

import functools
import json

from jsonschema import Draft202012Validator

from ..config import SCHEMA_PATH
from .issues import Issue
from .semantic import semantic_issues


@functools.lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _pointer(path) -> str:
    return "/" + "/".join(str(p) for p in path) if path else ""


def schema_issues(doc: dict, limit: int = 20) -> list[Issue]:
    out = []
    for err in _validator().iter_errors(doc):
        out.append(Issue("schema", err.message[:300], "error", _pointer(err.absolute_path)))
        if len(out) >= limit:
            break
    return out


def validate_document(doc: dict) -> list[Issue]:
    """Structure first; semantic checks only make sense on a structurally valid document."""
    issues = schema_issues(doc)
    if issues:
        return issues
    return semantic_issues(doc)
