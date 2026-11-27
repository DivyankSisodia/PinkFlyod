"""Moved and replaced media: detection, checking a replacement, searching a folder."""
from __future__ import annotations

import shutil

from conftest import needs_ffmpeg

from shorts_studio.project.relink import check_candidate, check_sources, search_folder, used_source_ids
from shorts_studio.project import presets
from shorts_studio.testmedia import bands_video

pytestmark = needs_ffmpeg


def test_ok_missing_changed(settings, imported, tmp_path, landscape):
    own = tmp_path / "own.mp4"
    shutil.copy2(landscape, own)
    (sid, record), = imported(own)
    doc = presets.quick_short([(sid, record)])
    assert check_sources(settings, doc) == {sid: "ok"}
    moved = tmp_path / "moved" / "own.mp4"
    moved.parent.mkdir()
    own.rename(moved)
    assert check_sources(settings, doc) == {sid: "missing"}
    bands_video(own, seconds=5)            # a different file at the old path
    assert check_sources(settings, doc) == {sid: "changed"}


def test_touched_but_identical_file_is_ok(settings, imported, tmp_path, landscape):
    own = tmp_path / "own.mp4"
    shutil.copy2(landscape, own)
    (sid, record), = imported(own)
    doc = presets.quick_short([(sid, record)])
    data = own.read_bytes()
    own.write_bytes(data)                  # same bytes, new mtime
    assert check_sources(settings, doc) == {sid: "ok"}


def test_check_candidate(imported, tmp_path, landscape, landscape_silent):
    own = tmp_path / "own.mp4"
    shutil.copy2(landscape, own)
    (_sid, record), = imported(own)
    copy = tmp_path / "copy.mp4"
    shutil.copy2(own, copy)
    same = check_candidate(copy, record)
    assert same["ok"] and same["identical"] and same["compatible"]
    other = check_candidate(landscape_silent, record)
    assert other["ok"] and not other["compatible"]
    assert any("length" in r for r in other["reasons"]) and any("sound" in r for r in other["reasons"])


def test_search_folder_finds_renamed_and_moved(imported, tmp_path, landscape):
    own = tmp_path / "own.mp4"
    shutil.copy2(landscape, own)
    (sid, record), = imported(own)
    target = tmp_path / "archive" / "2026" / "renamed.mp4"
    target.parent.mkdir(parents=True)
    own.rename(target)
    (tmp_path / "archive" / "decoy.mp4").write_bytes(b"not a video")
    found = search_folder(tmp_path / "archive", {sid: record})
    assert found == {sid: str(target)}


def test_used_sources_ignore_unused_and_disabled(example):
    doc = example("top3-gaming-fails")
    assert used_source_ids(doc) == {"src_01JDXFAILROCKET", "src_01JDXFAILLADDER", "src_01JDXFAILBOSS",
                                    "src_01JDXGAMEPARKOUR", "src_01JDXMUSICLOFI"}
    doc["scenes"][0]["enabled"] = False
    doc["audio"]["music"]["enabled"] = False
    assert "src_01JDXFAILROCKET" not in used_source_ids(doc)
    assert "src_01JDXMUSICLOFI" not in used_source_ids(doc)
