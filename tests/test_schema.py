"""The project schema: examples, structural rejections, semantic rules, migration."""
from __future__ import annotations

import pytest

from shorts_studio.schema import MigrationError, migrate, schema_issues, semantic_issues, validate_document

EXAMPLES = ["top3-gaming-fails", "silent-countdown", "quick-short-13s", "narrated-explainer"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_are_valid(example, name):
    assert validate_document(example(name)) == []


def _codes(issues):
    return {i.code for i in issues}


REJECTIONS = {
    "split layout without split settings": lambda d: d["scenes"][2]["layout"].pop("split"),
    "country BOTH with a region": lambda d: d["audience"].update(region="US-WA"),
    "US with a Canadian region": lambda d: d["audience"].update(country="US", region="CA-BC"),
    "segment layer without segment_id": lambda d: d["scenes"][0]["layers"]["primary"].pop("segment_id"),
    "unknown scene property": lambda d: d["scenes"][0].update(rank_number=3),
    "stored rank list": lambda d: d["ranking"].update(ranks=[3, 2, 1]),
    "malformed scene id": lambda d: d["scenes"][0].update(id="scene-1"),
    "divider out of range": lambda d: d["scenes"][2]["layout"]["split"].update(divider=0.95),
    "badge format without {n}": lambda d: d["ranking"]["badge"].update(format="RANK"),
    "schema_version 2": lambda d: d.update(schema_version=2),
    "cap over 180 s": lambda d: d["output"].update(max_duration_s=200),
    "fixed duration without seconds": lambda d: d["scenes"][0]["duration"].update(driver="fixed", fixed_s=None),
}


@pytest.mark.parametrize("name", list(REJECTIONS))
def test_structural_rejections(example, name):
    doc = example("top3-gaming-fails")
    REJECTIONS[name](doc)
    assert schema_issues(doc), name


def test_semantic_missing_segment_reference(example):
    doc = example("quick-short-13s")
    doc["scenes"][0]["layers"]["primary"]["segment_id"] = "seg_01JDXNOSUCHSEG"
    assert "missing_reference" in _codes(semantic_issues(doc))


def test_semantic_segment_past_end_and_empty(example):
    doc = example("quick-short-13s")
    seg = doc["segments"]["seg_01JDXLOOKOUT13"]
    seg["out_s"] = 200.0
    assert "segment_past_end" in _codes(semantic_issues(doc))
    seg["in_s"], seg["out_s"] = 10.0, 10.01
    assert "empty_segment" in _codes(semantic_issues(doc))


def test_semantic_split_needs_secondary(example):
    doc = example("top3-gaming-fails")
    doc["scenes"][2]["layers"]["secondary"] = None
    assert "layout_needs_secondary" in _codes(semantic_issues(doc))


def test_semantic_duplicate_scene_ids(example):
    doc = example("silent-countdown")
    doc["scenes"][1]["id"] = doc["scenes"][0]["id"]
    assert "duplicate_id" in _codes(semantic_issues(doc))


def test_semantic_image_layer_must_use_image(example):
    doc = example("narrated-explainer")
    doc["scenes"][0]["layers"]["primary"]["source_id"] = "src_01JDXSTOCKDRIZZLE"
    assert "wrong_kind" in _codes(semantic_issues(doc))


def test_semantic_narration_driver_needs_text(example):
    doc = example("narrated-explainer")
    doc["scenes"][0]["narration"]["text"] = "   "
    assert "driver_needs_narration" in _codes(semantic_issues(doc))


def test_migrate_current_is_identity(example):
    doc = example("quick-short-13s")
    migrated, read_only = migrate(doc)
    assert migrated == doc and read_only is False


def test_migrate_newer_opens_read_only(example):
    doc = example("quick-short-13s")
    doc["schema_version"] = 99
    migrated, read_only = migrate(doc)
    assert read_only is True and migrated["schema_version"] == 99


def test_migrate_rejects_non_project():
    with pytest.raises(MigrationError):
        migrate({"hello": "world"})
