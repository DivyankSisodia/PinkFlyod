# 01 — Reference inspection

Inspected on 2026-11-25. Nothing in `C:\Users\ADMIN\Desktop\clipper` was modified. Fresh read-only clones live in
`C:\Users\ADMIN\shorts-studio-refs\` (outside this workspace; safe to delete after Phase 0).

## 1. What was inspected

| Repo | Where | Revision | Date | License |
|---|---|---|---|---|
| ViralMint, upstream | `shorts-studio-refs\viralmint` (clone of `https://github.com/openclaw-easy/ViralMint`) | `f81630c6d0858b66dbf6c0154997ed58afee2ddd` | 2026-11-24 | AGPL-3.0-**only** (`LICENSE`; 193 of 194 backend `.py` files carry `SPDX-License-Identifier: AGPL-3.0-only`) |
| ViralMint, your install | `C:\Users\ADMIN\Desktop\clipper` | `da5b5c79a1ed97db010738f1c9435d1c39158b09` | 2026-10-19 | same |
| PurffleShorts | `shorts-studio-refs\purffle-shorts` (clone of `https://github.com/Chamanrajragu/purffle-shorts`) | `514fd2547227b98d951dfc1489fc8c7ce72f1b68` (v3.1.0) | 2026-11-14 | MIT, "Copyright (c) 2025 Purffle" |

Your install is 75 commits behind upstream. Upstream changed 42 files under `backend/services`, `core` and `api`
since then (for example `clip_extractor.py` was split into `clip_windows.py` and `clip_prompts.py`, and
`studio_render.py` changed by about 330 lines). Your install also has local edits to `launcher.py` and `run.py`,
plus untracked `start_clipper.py`, `tools/` (portable Node 22), `clipper.ico` and `shorts/`. Line numbers below
refer to the upstream clone.

Your install uses port **16888**, `viralmint.db` (+ WAL) in its root, `storage\` for media and Whisper models,
`.env` in its root, and the desktop shortcut `C:\Users\ADMIN\Desktop\clipper.lnk`. Shorts Studio will not read,
write or reuse any of these.

The `clipper\shorts\` folder contains six videos you built by hand (countdowns such as `Top-5-Cat-Fails`,
`Baby-Prank-Reactions-Wait-For-1st`). Each has an `edit-plan.json` with rank, label, source in/out and output
times, a hand-written `.ass` overlay for rank numbers and labels, and a `verification` note with ffprobe and
loudness results. Neither app supports this workflow directly, which is the clearest evidence for the Ranking
preset.

## 2. Traced path: ViralMint Smart Video Studio (script → MP4)

1. `POST /studio/projects` → `api/studio.py:122 create_project` → `services/studio_store.py:187 create_project`.
   `studio_doc.lines_for_new_project` splits the script into sentence lines and `studio_doc.make_scene` (426)
   gives each scene a stable `uid`. `studio_doc.validate_doc` (750) cleans the document, which is stored as
   `VideoProject.doc_json` in SQLite (`DOC_VERSION = 1`).
2. Edits: `PATCH /studio/projects/{id}` (426) → `studio_store.write_ops` (339, revision check) →
   `studio_ops.apply_ops` (66). Ops: `set_line`, `insert_scene`, `remove_scene`, `reorder_scenes`,
   `split_scene`, `merge_scenes`, `bind_visual`, `set_visual_fields`, `clear_visual`, `set_setting`, …
   Changing a line marks its voice `stale` (`_stale_voice`, 104).
3. Voice: `POST /studio/projects/{id}/voice` → `core/tasks/studio.py:94 run_studio_voice` →
   `voice_take_service.ensure_take` (176). A take is cached under `take_key` (84), a SHA-256 of
   provider, model, voice, instructions and text. Only changed lines are re-voiced.
4. Render: `POST /studio/projects/{id}/render` (680) → `core/tasks/studio.py:326 run_studio_render` →
   `services/studio_render.py:332 render`:
   blockers (`studio_checks.checks_for`) → takes (`resolve_take`) → scene duration = take + tail gap →
   `studio_doc.second_shots` → visuals (`stock_file`, `visual_file`) → per scene
   `stock_video_service.trim_and_normalize_clip` (510) / `fit_clip` / `ffmpeg_service.generate_single_kenburns_clip` (958) →
   `audio_utils.concat_audio` (narration) → word timings via `voice_take_service.take_details` (Whisper) →
   `caption_service.generate_captions_ass` (1254) → `ffmpeg_service.stitch_with_style` (200) →
   `music_service.mix_audio` (162, fixed music level, `amix`, no ducking) → `render_post.add_sfx` →
   `render_post.deliver_loudness` (115, one linear gain to −14 LUFS) → `ffmpeg_service.add_audio_to_video` (245) →
   `caption_service.burn_captions` (1371) → `_final_encode` → `render_post.finish_video` (auto-zoom) →
   `output_validator.validate_output` (240, ffprobe) → `_persist` (855).
5. Progress goes through `job_helper.update_job_status` and `core/ws_manager.py:68 send_progress`; cancel is a flag
   on the Job row polled by `gate()`.

Observations: the soundtrack is narration + music + SFX only, so a clip's own sound is never in the mix. The
layout is one full-frame visual per scene. A render makes about 4–6 encode generations (normalise, stitch, merge,
burn, final, finish).

## 3. Traced path: ViralMint Clip Studio (long video → vertical clips)

`POST /downloaded/{video_id}/extract-clips` (`api/downloaded.py:1110`) → `core/task_runner.py:1176` →
`services/clip_extractor.py:219 extract_viral_clips` → `_load_or_transcribe_segments` (697, `whisper_service.transcribe`
337, faster-whisper) → manual ranges `clip_windows._build_manual_clip_windows` (75) or AI `_select_clip_windows`
(1012) + `clip_windows._snap_to_sentence_boundaries` (321) → `_process_clips_parallel` (1234) →
`ffmpeg_service.extract_clip` (407, blur-fill when landscape) → `_remove_silence_and_fillers` (1555) →
`_burn_clip_captions` (1758). The cutting bench UI is `frontend/src/components/clip/bench/*`
(`SourceBench.jsx`, `Timeline.jsx`, `RangeRail.jsx`, `InOutFrames.jsx`).

Clip Studio and Smart Video Studio are separate pipelines with separate data models, and each of the 22 tools
in `core/tool_runners.py` runs its own FFmpeg commands.

## 4. Traced path: PurffleShorts `make --script examples/reddit-story.json`

`cli.py` → `pipeline.py:337 Studio.make` → `produce` (379):
`_speak` (270) → `tts.synthesize` (408) / `synthesize_lines` (449); `_edge` (92) captures Edge TTS `WordBoundary`
events; voice cache keyed by a SHA-256 of engine, voice, rate and text (352) →
`timing.scene_timeline` (186, scene k starts at its first spoken word) → `timing.split_shots` (219, long scenes cut on
pauses) → `media.background_item` (53, one random stretch of `BACKGROUND_VIDEO`) or `media.Visuals.for_scenes`
(Pexels/Pixabay/AI images) → `timing.caption_chunks` (270) → `overlays.post_card_png` (750) →
`overlays.build_overlays` (945) → `sfx.events_for` (117) → `render.render_video` (387):
`prepare_segment` (59) per shot in a thread pool (cover-crop, colour grade, `-an`, `-stream_loop -1` when short,
intermediate `ultrafast crf 15`) → `compose` (240): `xfade`/`concat`, `vstack` for split, PNG/ASS overlays,
`mix_audio` (182: `sidechaincompress` ducking, two-pass `loudnorm` with `linear=true`), one final libx264 encode →
`ffmpeg.probe` (173) size/duration check → cover, SRT, `metadata.json`, SQLite history.

## 5. Traced path: PurffleShorts `clip episode.mp4`

`clipper.py:553 make_clips` → `fetch_source` (96, yt-dlp for URLs) → `transcribe` (118, faster-whisper) →
`sentences` (141) → `pick_clips` (215, LLM) with `_snap` (200) → `render_clip` (504): `crop_filter` (492:
centre / blur / face), `keep_ranges` (381, jump cuts on frame boundaries), `retime` (422), `select_expr` (439),
`audio_cut` (446), `zoom_plan` (464) → `render.compose`.

Observations: one FFmpeg render core (`render.compose`) serves both stories and clips. Split is fixed at 50/50
(`split_sizes`, 424). There is no picture-in-picture. Scene footage is always muted; only the clipper keeps source
sound. Background stretches are random, not tracked for repeats, and looping has no join preview. The Reddit post
card draws vote and comment counts derived from the title text (decoration, not real data). There is no editable
project document beyond `script.json`, no undo, and no relink.

## 6. Modules by responsibility

| Responsibility | ViralMint (AGPL-3.0-only) | PurffleShorts (MIT) |
|---|---|---|
| Clipping | `services/clip_extractor.py`, `clip_windows.py`, `clip_caption_timing.py`, `filler_words.py`, `ffmpeg_service.extract_clip`; UI `components/clip/bench/*` | `clipper.py` (`keep_ranges`, `retime`, `select_expr`, `audio_cut`, `crop_filter`, `zoom_plan`, face crop) |
| Transcription | `services/whisper_service.py` (faster-whisper, model download/progress, unload) | `clipper.transcribe`, `tts._align_faster_whisper` |
| Scene timing | `studio_doc.scene_seconds`, `derive_timeline`, `second_shots` | `timing.py` (`scene_timeline`, `split_shots`, `estimate_timings`, `anchored_timings`, `transfer_timings`) |
| Narration | `edge_tts_service.py`, `openai_tts_service.py`, `voice_take_service.py` (take cache + states), `studio_audio.py` / `own_audio.py` (your own recording) | `tts.py` (Edge, OpenAI, ElevenLabs, Kokoro, Coqui, OS voice, silent; cache; two-voice lines) |
| Captions | `caption_service.py` (ASS styles, emoji, CJK), `safe_zones.py` (TikTok-derived insets) | `overlays.py` (`write_ass`, Pillow captions, `CapStyle`, hook, CTA, post card, chat screen, emoji) |
| Gameplay composition | none | `media.background_item`, `render.split_sizes`, `render.compose` (`vstack`) |
| Rendering | `studio_render.py`, `ffmpeg_service.py`, `stock_video_service.trim_and_normalize_clip`, `music_service.mix_audio`, `render_post.py`, `output_validator.py` | `render.py` (`prepare_segment`, `compose`, `mix_audio`), `ffmpeg.py` (`run` with progress, `probe`, `loudnorm_report`, `silences`) |

## 7. Feature map against Shorts Studio requirements

`✔` has it · `◐` partly · `✘` no

| Requirement | ViralMint | PurffleShorts | Shorts Studio plan |
|---|---|---|---|
| Local file import | ✔ upload into project | ✔ `media/` folder | Native file picker (reference in place) + drag-drop upload |
| URL import (yt-dlp) | ✔ `download/engine.py` | ✔ `clipper.fetch_source` | Phase 3, with rights gate |
| In/out trim bench with filmstrip | ✔ Clip Studio bench | ✘ (CLI times) | Phase 1 basic, Phase 3 transcript lane |
| Local transcription | ✔ | ✔ | Phase 3, faster-whisper on CPU |
| Suggested highlights, reviewed before use | ✔ AI picks as editable blocks | ◐ LLM picks, no review | Phase 3, suggestions land as unplaced segments |
| One project document for every format | ✘ two separate models | ✘ `script.json` only | **One versioned JSON document** |
| Stable scene IDs | ✔ `uid` | ✘ list index | ✔ `scn_…` |
| Per-scene layout (full/split/PiP/blur) | ✘ one full-frame visual | ◐ project-wide full/split 50/50 | ✔ per scene, adjustable divider, PiP |
| Per-scene source audio toggle | ✘ | ✘ | ✔ per layer |
| Narration per line, edit one line → re-voice one take | ✔ | ◐ cache makes it cheap, but whole video re-rendered | ✔ take per scene + render cache per scene |
| Record / import own voice | ✔ whole recording split into scenes | ✘ | ✔ per scene (Phase 2) |
| Music ducking | ✘ fixed level | ✔ sidechain | ✔ deterministic envelope (same in preview and export) |
| −14 LUFS | ✔ linear gain | ✔ two-pass linear loudnorm | ✔ two-pass, verified with `ebur128` after render |
| Silent export | ✘ validator expects audio | ◐ skips normalising silence | ✔ no audio stream (or silent AAC by choice) |
| Word-synced captions | ✔ | ✔ | ✔ |
| YouTube Shorts safe area | ◐ TikTok-derived | ✘ fixed fractions | ✔ YouTube Shorts insets, enforced by the resolver |
| Ranking / countdown | ✘ (you did it by hand) | ✘ | ✔ derived ranks |
| Reddit post card | ✘ | ◐ invented vote counts | ✔ real fields only, usernames hidden by default |
| Gameplay library, tags, non-repeating picks | ✘ | ◐ random file + start | ✔ Phase 2 |
| Loop with join preview | ✘ | ◐ silent loop | ✔ crossfade + preview of the join |
| Undo / redo | ✔ snapshot stack | ✘ | ✔ |
| Autosave / reopen | ✔ | ✘ | ✔ |
| Relink moved media | ✘ ("add it again") | ✘ | ✔ fingerprint-checked relink |
| Preview/export parity | ◐ "captions, grade and motion are approximations" (`SequencePlayer.jsx`) | ✘ no preview | ✔ shared resolved timeline + exact-frame check |
| Background jobs, WebSocket progress, cancel | ✔ | ✔ live progress + cancel (per README; push mechanism not traced) | ✔ |
| Open finished MP4 | ✔ library | ✔ library | ✔ "Open MP4" / "Show in folder" |
| BYOK + OpenAI-compatible + Ollama | ✔ | ✔ 12 providers | ✔ Phase 3 |
| Script draft + retention rewrite | ◐ planner/assist | ✔ Script Doctor | Phase 3 (adapt Script Doctor) |
| Stock footage (Pexels/Pixabay) | ✔ | ✔ | Phase 3 |
| Trends with provenance | ◐ no geo labels | ◐ `TRENDS_GEO`, no provenance | Phase 3, source + timestamp + true granularity |
| US/CA localization diff | ✘ | ✘ | Phase 3 |
| Rights confirmation | ✘ (LEGAL.md text) | ✘ | ✔ stored on the project, gates render |
| Reused-content warning | ✘ | ✘ | ✔ non-blocking |
| Keys encrypted, never logged | ✔ Fernet | ◐ `.env`, `redact()` in logs | ✔ |
| One-click Windows launcher | ✔ tray launcher | ✔ desktop builds | Phase 4 |
| Publishing / scheduling / analytics | ✔ | ✔ | Out of scope (extension point kept) |

## 8. Findings that shape the design

- Both apps assemble video with plain FFmpeg on the CPU, and FFmpeg 9.0.2 here has every filter needed
  (`loudnorm`, `ebur128`, `ass` with libass/harfbuzz/fribidi, `xfade`, `vstack`, `overlay`, `boxblur`, `gblur`,
  `zoompan`, `sidechaincompress`, `silencedetect`). No other render engine is needed.
- PurffleShorts' two-stage render (prepared segments, then one final encode) gives one lossy generation that matters
  and is the right core. ViralMint's 4–6 generations should not be copied.
- ViralMint's best ideas are in the editing model: stable scene IDs, op-based edits with a revision check, voice
  states (`none / generating / ready / stale / failed`), and a cutting bench. These are design ideas and can be
  implemented independently.
- Neither app has per-scene layout or per-scene source audio. Both are required for the mixed "Top 3" example, so
  the data model must be new rather than a merge of the two.
- faster-whisper 1.2.1 and ctranslate2 4.8.3 already run on Python 3.13.0 on this machine (your clipper venv).
  CPU: Ryzen 7 5800X, 32 GB RAM. An RTX 4060 is present but will not be required.
- Google Trends' RSS returns different lists for `geo=US`, `US-WA`, `CA` and `CA-BC` (checked today), so
  state/province labels are real for that source. YouTube search suggestions only take a country hint (`gl=US`/`CA`)
  and return near-identical lists for both, so they must be labelled "country hint, not geo-filtered".
