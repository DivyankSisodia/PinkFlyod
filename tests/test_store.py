"""Project storage: atomic saves, revisions, history, reopen."""
from __future__ import annotations

import json

import pytest

from shorts_studio.project.store import (InvalidProject, ProjectNotFound, ProjectStore, ReadOnlyProject,
                                         RevisionConflict)


@pytest.fixture
def store(tmp_path):
    return ProjectStore(tmp_path / "projects")


def test_create_load_roundtrip(store, example):
    doc = store.create(example("quick-short-13s"))
    assert doc["revision"] == 1
    loaded = store.load(doc["id"])
    assert loaded.doc == doc and loaded.read_only is False


def test_save_increments_revision_and_keeps_history(store, example):
    doc = store.create(example("quick-short-13s"))
    doc["title"] = "Edited"
    saved = store.save(doc["id"], doc, base_revision=1)
    assert saved["revision"] == 2 and store.load(doc["id"]).doc["title"] == "Edited"
    assert store.history(doc["id"]) == [1]
    assert store.load_revision(doc["id"], 1)["title"] == "Quick Short, 13 seconds"
    assert not list(store.dir_for(doc["id"]).glob("*.tmp"))


def test_stale_revision_is_refused(store, example):
    doc = store.create(example("quick-short-13s"))
    store.save(doc["id"], {**doc, "title": "Tab A"}, base_revision=1)
    with pytest.raises(RevisionConflict) as e:
        store.save(doc["id"], {**doc, "title": "Tab B"}, base_revision=1)
    assert e.value.current == 2
    assert store.load(doc["id"]).doc["title"] == "Tab A"


def test_invalid_document_is_refused_and_file_untouched(store, example):
    doc = store.create(example("quick-short-13s"))
    bad = {**doc, "scenes": [{"id": "nope"}]}
    with pytest.raises(InvalidProject):
        store.save(doc["id"], bad, base_revision=1)
    assert store.load(doc["id"]).doc == doc


def test_created_at_cannot_be_rewritten(store, example):
    doc = store.create(example("quick-short-13s"))
    saved = store.save(doc["id"], {**doc, "created_at": "2000-01-01T00:00:00Z"}, base_revision=1)
    assert saved["created_at"] == doc["created_at"]


def test_history_is_capped(store, example):
    doc = store.create(example("quick-short-13s"))
    for rev in range(1, 56):
        doc = store.save(doc["id"], doc, base_revision=rev)
    assert len(store.history(doc["id"])) == 50


def test_newer_schema_opens_read_only(store, example):
    doc = store.create(example("quick-short-13s"))
    f = store.file_for(doc["id"])
    raw = json.loads(f.read_text(encoding="utf-8"))
    raw["schema_version"] = 7
    f.write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load(doc["id"])
    assert loaded.read_only is True
    with pytest.raises(ReadOnlyProject):
        store.save(doc["id"], doc, base_revision=1)


def test_unknown_and_malformed_ids(store):
    with pytest.raises(ProjectNotFound):
        store.load("prj_DOESNOTEXIST01")
    with pytest.raises(ProjectNotFound):
        store.load("../../etc")


def test_list_orders_by_last_edit(store, example):
    a = store.create(example("quick-short-13s"))
    b = example("silent-countdown")
    b = store.create(b)
    store.save(a["id"], a, base_revision=1)
    listed = [p["id"] for p in store.list()]
    assert listed[0] == a["id"] and set(listed) == {a["id"], b["id"]}
    assert store.list()[0]["poster_source_id"] == "src_01JDXLANDSCAPE"
