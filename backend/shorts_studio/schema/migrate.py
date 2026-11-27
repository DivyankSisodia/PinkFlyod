"""Schema migrations. Each step is a pure function vN -> vN+1; there are none yet (version 1 is current)."""
from __future__ import annotations

import copy
from collections.abc import Callable

CURRENT_VERSION = 1

_STEPS: dict[int, Callable[[dict], dict]] = {
    # 1: migrate_v1_to_v2,
}


class MigrationError(Exception):
    pass


def migrate(doc: dict) -> tuple[dict, bool]:
    """Return (document at CURRENT_VERSION, read_only). A newer document opens read-only, unchanged."""
    version = doc.get("schema_version")
    if not isinstance(version, int):
        raise MigrationError("This file is not a Shorts Studio project (no schema_version).")
    if version > CURRENT_VERSION:
        return doc, True
    out = copy.deepcopy(doc)
    while out["schema_version"] < CURRENT_VERSION:
        step = _STEPS.get(out["schema_version"])
        if step is None:
            raise MigrationError(f"No migration from schema version {out['schema_version']}.")
        out = step(out)
    return out, False
