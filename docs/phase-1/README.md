# Phase 1 — Walking skeleton (core offline loop)

Status: **waiting for your review.**

## Decisions taken (you said "next phase" without choosing; these were the Phase 0 recommendations)

- License option **(b)**: ViralMint used only as a design reference; PurffleShorts (MIT) code adapted with notices;
  Shorts Studio is MIT (`LICENSE`, `THIRD_PARTY_NOTICES.md`). If you want AGPL instead, say so before Phase 2.
- Repo root = this workspace. Data folder = `data\` here (override with `SHORTS_STUDIO_DATA`).
- Ports 17860 (app) and 17861 (Vite dev server only). Silent exports have no audio stream.

One change from the Phase 0 design: the **JSON Schema file stays the single definition** of the project format
instead of being exported from pydantic models. Python validates with it; the TypeScript types are generated from it
(`frontend/src/model/project.gen.ts`) and a test fails if they drift. Pydantic models would have been a second copy.

## Run it

Windows (tested):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # once: venv, backend, frontend build
.venv\Scripts\python -m shorts_studio                            # opens http://127.0.0.1:17860
```

macOS (written, not tested here; needs `brew install python@3.12 node ffmpeg`):

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
(cd frontend && npm ci && npm run build)
.venv/bin/python -m shorts_studio
```

The one-click launcher and desktop shortcut are Phase 4. Your clipper install (port 16888, its own database and
`clipper.lnk`) is untouched.

## What works in this phase

- **Home**: "What do you want to make?" with *Edit an existing video* (Choose files… links files in place; Copy files
  in… or drag-and-drop copies them into `data\media\imports`), ownership and audience choice, recent projects.
  *Create from scratch* is shown but disabled until Phase 2.
- **Quick Short preset**: first 13 s of the first video, cover-cropped to 9:16, length capped at 15 s.
- **Trim bench**: source player, filmstrip rail with in/out handles, I/O keys, frame stepping, exact entry,
  "13.00 s of max 15 s", a hint below 12 s, "Add a part…" to add more scenes from any source.
- **Framing**: fill (crop) / fit (bars) / blurred fill, focus sliders, zoom, or drag the picture in the preview.
- **Preview**: canvas player at 540×960 using the same placement math as the export, Shorts safe-area guide,
  original sound with volume, and **Check exact frame**, which renders the current frame through the export graph.
- **Editing**: scene strip (select, reorder, duplicate, skip, delete), speed, sound on/off and gain, title,
  cap toggle, audience; undo/redo (Ctrl+Z / Ctrl+Y).
- **Persistence**: autosave 0.8 s after an edit, atomic writes, revision checks (a second tab can't overwrite the
  first), last 50 revisions kept in `history\`, reopen from recent projects.
- **Relink**: missing or changed files are flagged on open; *Relink…* checks the new file against the stored
  fingerprint (length, size, sound); *Search a folder…* finds moved or renamed files by name or size + content hash.
- **Export**: one background job per render with live progress over WebSocket and Cancel; per-scene segments are
  cached by content, then one final H.264 encode; sound mixed and normalised to −14 LUFS (two-pass loudnorm); the
  file is checked with ffprobe and ebur128 before it counts as done; Open MP4 and Show in folder.
- **Gates**: the 15 s cap, missing media, and the rights checkbox when footage is marked "someone else's" all block
  export; a non-blocking reused-content note appears for mostly third-party footage with nothing added.

## Verification (Windows 11 Pro, Python 3.13.0, Node 20.18, FFmpeg 9.0.2 gyan.dev, Microsoft Edge headless)

| Check | Command | Result |
|---|---|---|
| Backend tests: schema, presets, placement, resolver, render-graph builder, store, relink, API, real renders, dialog | `.venv\Scripts\python -m pytest` | **117 passed** (45 s) |
| Frontend tests: placement parity with Python fixtures, edit ops validated against the JSON Schema, generated types current | `cd frontend; npm test` | **32 passed** |
| TypeScript | `cd frontend; npm run typecheck` | no errors |
| Browser walk-through | `.venv\Scripts\python scripts\ui_e2e.py` | **14 steps passed**, 0 console errors, 0 failed requests |
| Sample renders | `.venv\Scripts\python scripts\phase1_samples.py` | **4 of 4 verified**, 4K HEVC proxy built |

Render tests that check pixels, not just metadata:

- Crop: with focus 0.25, the centre of the exported frame shows the source band at x = 480 (yellow) and the left edge
  shows band 0 (red).
- Trim accuracy: a marker sweeps across the source at 240 px/s; on the first, middle and last exported frames of a
  4–17 s trim it sits where source times 4.000, 10.500 and 16.967 s put it, within one frame.
- Fit shows bars above and the full source width; blurred fill has a non-black background.
- The exact-frame PNG and the exported frame agree (same band, mean channel difference < 8).
- Silent project → no audio stream; source without sound → no audio stream; 2× speed → half the frames; a cancelled
  render leaves no partial files; an over-cap project and a missing file are refused.

The browser walk-through (`test-output\phase-1\ui\report.json`) covers: home screen → copy a 1920×1080 file in →
editor opens → trim out to 25 s is held at 15.00 s → trim 4–17 s (13.00 s) → focus 0.25, and the preview canvas
centre turns yellow (same as the export) → undo/redo → play → exact frame → export → reload and reopen from the
home screen (crop 0.25 and trim 4.000/17.000 kept) → move the file away → reopen shows it missing → relink →
export again → *Choose files…* references the file in place.

### Files to look at

| File | What it is | ffprobe |
|---|---|---|
| `test-output\phase-1\ui\ui-quick-short-13s.mp4` | exported through the UI | 1080×1920, 30/1, 390 frames, 13.000 s, H.264 + AAC, −14.0 LUFS |
| `test-output\phase-1\ui\ui-quick-short-13s-after-relink.mp4` | re-exported after the source was moved and relinked | same |
| `test-output\phase-1\samples\qs-13s-landscape-audio.mp4` | 1080p source, 4–17 s, fill, focus 0.25, sound | 1080×1920, 30 fps, 390 frames, 13.0 s, AAC, −14.0 LUFS, true peak −6.1 dBFS |
| `test-output\phase-1\samples\qs-13s-landscape-silent.mp4` | same trim, focus 0.75, sound off | 1080×1920, 30 fps, 390 frames, 13.0 s, **no audio stream** |
| `test-output\phase-1\samples\qs-13s-4k-hevc-blur-fill.mp4` | 3840×2160 HEVC source, 2–15 s, blurred fill | 1080×1920, 30 fps, 390 frames, 13.0 s, AAC, −14.0 LUFS |
| `test-output\phase-1\samples\qs-15s-cap-fit.mp4` | 1080p source, 0–15 s (the cap), fit | 1080×1920, 30 fps, 450 frames, 15.0 s, AAC, −14.0 LUFS |

Also in those folders: first/middle/last frames (`samples\frames\*.png`), full ffprobe output (`samples\*.ffprobe.json`),
`samples\summary.json`, and UI screenshots (`ui\screens\1-home.png` … `7-missing-media.png`). All footage is generated
by FFmpeg (colour bands, a `testsrc` strip, a sweeping marker, a tone with beeps), so there is nothing to license.

## Reuse manifest

**PurffleShorts @ `514fd25` (MIT, © 2025 Purffle)** — adapted, with a header line in each file:

| Shorts Studio file | Adapted from | What |
|---|---|---|
| `backend/shorts_studio/render/ffmpeg.py` | `purffle_shorts/ffmpeg.py` | finding ffmpeg/ffprobe, `run()` with `-progress pipe:1` parsing and kill on cancel/timeout, `loudnorm_report()`. Changed: a per-job cancel token instead of a global flag, no console windows on Windows, ffprobe JSON passthrough, new `ebur128_summary()` |
| `backend/shorts_studio/render/plan.py` | `purffle_shorts/render.py` | fast intermediate encode settings (`_encode_args`), cover-crop chain (`prepare_segment`), two-pass `loudnorm` with measured values and `linear=true` (`mix_audio`) |

Not used yet (planned per Phase 0): `timing.py`, `overlays.py`, `sfx.py`, `tts.py`, `clipper.py`, `llm.py`,
`script.py`, `seo.py`, `topics.py`, `media.py`, `envfile.py`.

**ViralMint @ `f81630c` (AGPL-3.0-only)** — no code, comments or prompts copied. Ideas reimplemented: stable scene IDs;
saves checked against a revision number; undo/redo as document snapshots; a trim bench with in/out handles over a
filmstrip; checking the output with ffprobe before reporting success; job progress over a WebSocket with cancel.

Everything else is new: the schema and its checks, presets, store, relink, resolver, placement math (Python and
TypeScript), render engine and cache, verification, jobs, API, and the whole frontend.

## Known limitations

- **Only the Quick Short path is complete.** Split/PiP layouts, narration, music, captions, hook/title bar, rank badges,
  Reddit cards, SFX, transitions, moving crops (keyframes), text cards and looping clips are in the schema but not
  rendered yet. A document that uses them (for example `schema/examples/top3-gaming-fails.json`) shows one warning
  per feature ("arrives in Phase 2") and renders without it. Looping falls back to freezing the last frame.
- **Native dialogs** (*Choose files…*, *Relink…*, *Search a folder…*): the server side, Tk start-up and the UI flow
  are tested, but in the browser test the dialog's answer was supplied by intercepting `/api/dialog`. Nobody has
  clicked the real Windows dialog yet. The dialog can open behind the browser window.
- The **rights checkbox** and **reused-content note** are tested in the resolver and API tests, not in the browser test.
- **Preview vs export**: crops, timing and which sound plays come from the same data and math. Blurred fill uses canvas
  blur in the preview and `gblur` in the export, so the background looks slightly different. The preview plays sound
  at its original level (the export is normalised to −14 LUFS) and without the 20 ms edge fades. Two scenes from the
  same file share one video element, so the preview may hitch briefly at the cut.
- **4K/HEVC sources**: the trim bench and preview use a 1280-wide H.264 proxy once it's built. Before that they try
  the original, which may not play in a browser without HEVC support.
- Still images can't be added from the UI yet. When they can, EXIF rotation needs handling (FFmpeg ignores it).
- libx264 only; a hardware encoder in a document shows a warning and libx264 is used.
- Undo history lasts for the session; on-disk revision history exists but has no restore UI yet.
- Python 3.13.0 can't find Tcl/Tk inside a venv on Windows; `media/dialog_proc.py` points it at the base install
  (fixed upstream in 3.13.1).
- Tested on Windows only. macOS instructions are untested.

## Repo state

`git init` was run; nothing is committed. Generated output (`data\`, `test-output\`, `frontend\dist`, `node_modules`,
`.venv`) is git-ignored. The Phase 0 reference clones remain in `C:\Users\ADMIN\shorts-studio-refs` (outside the repo).
