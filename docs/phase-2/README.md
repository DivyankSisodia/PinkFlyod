# Phase 2 — Composable presets and editor

Status: **waiting for your review.**

License stays option **(b)** (MIT app, PurffleShorts code adapted with notices, ViralMint as a design reference only),
since you said "proceed" without objecting.

## Run it

Same as Phase 1. After pulling these changes, rerun setup once (new Python packages: Pillow, edge-tts):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.venv\Scripts\python -m shorts_studio                            # http://127.0.0.1:17860
```

Everything works offline with no keys. Edge voices need internet; pick **This computer's voice (offline)** to work
without it.

## What's new

**Home**
- *Edit an existing video* now asks what to make: **Quick Short** (12–15 s), **Ranking / countdown** (each file is an
  entry; countdown or count-up), **Whole clips**, or **Clips over gameplay** (split or picture in picture).
- *Create from scratch* is enabled: **Script or story** (each sentence becomes a narrated scene), **Reddit-style post**
  (community, title, link; `u/name` becomes "the poster"; the author is hidden by default), **Ranking list** (one entry
  per line) or **Blank**. Choose the voice (Edge online or the system voice offline) and an optional gameplay
  background. *From a topic* stays disabled until Phase 3.
- A **Gameplay library** page (`#/library/gameplay`): add your own clips with tags, generate a royalty-free sample
  clip, see how often each was used, remove clips.

**Editor.** Every scene keeps its own settings, so presets mix freely in one video.
- **Layouts per scene**: full, split (divider, which layer is on top, gap) and picture in picture (inset layer, shape,
  size, position, rounded corners, border). Blurred fill is a framing mode. Each layer is framed independently: select
  *Main* or *Second* in the inspector, or drag that layer in the preview.
- **Gameplay**: *+ Gameplay background…* picks a random stretch of a library clip that avoids parts used before, as a
  split, a PiP, or a full-screen background. Its sound starts muted. When a clip is shorter than its scene it can
  loop (with a blend at the join), freeze, slow down or go black. **Preview join** renders 1.5 s either side of a loop
  join through the export pipeline.
- **Narration per scene**: edit the line, then **Generate** (Edge or system voice), **Record** (microphone) or
  **Import** a take. Editing a line marks only that scene's take as changed; regenerating redoes only that take, and
  later scenes move by the new length. **Make N missing or changed voices** does all of them in turn.
- **Captions**: word by word from the voice (the active word is highlighted), or typed cues with times; click a word
  to fix how it's shown without changing its timing. Style, size, height and words-at-once are project settings.
  Captions, badges and cards are always placed inside the Shorts safe area.
- **On screen**: rank badge (number derived from the scene order, never stored), label, Reddit-style post card
  (votes and comments only if you type them), text overlays, title bar, opening hook, watermark.
- **Sound**: per scene, each layer's own sound on/off with volume and *dip under the voice*, voice volume, music
  on/off, sound effects (whoosh, pop, hit, ding, boing, record scratch) at the playhead. Project music: a generated
  sample loop or any audio file, with automatic ducking under narration (depth adjustable).
- **Timeline**: drag scenes to reorder (ranks renumber), split at the playhead, duplicate, mute, skip, delete,
  *+ Add scene…* (part of a clip, a voice line, a text card). Cards show the rank, layout, voice state and "silent".
- **Preview**: draws every layer in its slot, PiP corners and border, loop copies, the same overlay and caption PNGs
  the export burns in, and plays clip sound, narration takes, music (with its duck envelope) and effects.

**Export**: 1080×1920, 30 fps, H.264 + AAC. Narration gets a gentle clean-up chain; the mix is brought to −14 LUFS by
measuring and applying gain with a true-peak limiter (up to 5 passes) instead of loudnorm's second pass. A
completely silent project exports with no audio stream. Unchanged scenes are reused from the segment cache.

## Verification (Windows 11 Pro, Python 3.13.0, Node 20.18, FFmpeg 9.0.2 gyan.dev, Microsoft Edge headless)

| Check | Command | Result |
|---|---|---|
| Backend tests | `.venv\Scripts\python -m pytest` | **179 passed** (2 min 8 s), including real renders, the system voice and an online Edge voice test |
| Frontend tests: placement parity, edit ops validated against the JSON Schema, preview timing maths, generated types | `cd frontend; npm test` | **51 passed** |
| TypeScript | `cd frontend; npm run typecheck` | no errors |
| Phase 1 browser walk-through (still passes on the new UI) | `.venv\Scripts\python scripts\ui_e2e.py` | **14 steps passed**, 0 console errors, 0 failed requests |
| Phase 2 browser walk-through | `.venv\Scripts\python scripts\ui_e2e_p2.py` | **12 steps passed**, 0 console errors, 0 failed requests |
| Sample renders | `.venv\Scripts\python scripts\phase2_samples.py` | **7 of 7 verified** |

### Phase 2 browser walk-through (`test-output\phase-2\ui\report.json`)

| Part | What the test does in the UI | What it checks |
|---|---|---|
| A. Silent countdown | Ranking from 3 silent 4 s clips (red, green, blue); drag red from the first card to the end | Cards read #3 #2 #1 before and after; red is now #1; the badge is drawn in the preview; export has **no audio stream**, 360 frames; frames 0/119 green, 120/239 blue, 240/359 red |
| B. Narrated explainer | Script → 3 scenes, system voice; make all voices; edit line 2; regenerate it | Lines 1 and 3 keep the same take id and identical scene JSON; line 2's take is new; line 3 starts 2.467 s later; line 2's caption words match the new text (16 caption states inside the scene); export −14.1 LUFS |
| C. Gameplay | Library: add a 4 s clip with tags, generate the 60 s sample; *Clips over gameplay* with a 10 s clip | Gameplay sound off; joins at 3.75 s and 7.50 s; *Preview join* returns a 3 s MP4; preview top half shows the clip; export 300 frames, −14.0 LUFS, only the top clip's sound; then PiP at 60 % width: the inset centre is the clip in preview and export |
| D. Mixed Top 3 | Ranking from 3 clips; #2 gets a voice line (system voice, clip ducked); #1 gets a gameplay split; sample music; export; move #1's divider to 0.62; export again | #3 and #2 identical in the saved document; 2 of 3 scene segments reused from the cache; mid-scene frames of #3 and #2 identical (mean difference 0.0), #1 differs (33.2); both exports −14.0 LUFS |

### Files to look at

UI exports (`test-output\phase-2\ui\`):

| File | ffprobe / measurements |
|---|---|
| `A-silent-ranking-reordered.mp4` | 1080×1920, 30/1, 360 frames, 12.0 s, **no audio stream** |
| `B-narrated-explainer-line-edited.mp4` | 1080×1920, 30/1, 398 frames, 13.27 s, AAC, −14.1 LUFS |
| `C-split-looping-muted-gameplay.mp4` | 1080×1920, 30/1, 300 frames, 10.0 s, AAC, −14.0 LUFS |
| `C-pip-gameplay.mp4` | 1080×1920, 30/1, 300 frames, 10.0 s, AAC |
| `D-mixed-top3.mp4`, `D-mixed-top3-after-editing-1.mp4` | 1080×1920, 30/1, AAC, −14.0 LUFS each |

Screenshots are in `ui\screens\` (A1 … D2) and the frames the test compared are in `ui\frames\`; `ui\contact-sheet.png`
shows eight of them side by side.

Sample renders (`test-output\phase-2\samples\`), made from FFmpeg-generated footage, the offline Windows voice and the
generated music loop:

| File | What | Frames | Sound | LUFS / true peak | Notes |
|---|---|---|---|---|---|
| `silent-countdown-reordered.mp4` | 3-entry countdown, reordered, title bar | 360 (12.0 s) | **none** | – | order green, blue, red = #3 #2 #1 |
| `narrated-explainer-line-edited.mp4` | 3 narrated lines (en-CA), music ducked, line 2 edited | 417 (13.9 s) | AAC | −14.1 / −1.7 dBTP | takes unchanged for lines 1 and 3; line 2 went from 83 to 155 frames; 2 cached segments |
| `split-looping-muted-gameplay.mp4` | 10 s clip over a 4 s gameplay clip that loops | 300 (10.0 s) | AAC | −13.9 / −6.0 | joins at 3.75 s and 7.5 s, gameplay muted |
| `pip-over-gameplay.mp4` | clip as a rounded PiP over the sample gameplay | 300 (10.0 s) | AAC | −13.9 / −6.0 | stretch 47.391–57.391 s of the sample |
| `mixed-top3.mp4` | #3 original sound, #2 narrated + ducked + captions, #1 over gameplay, music | 520 (17.33 s) | AAC | −14.0 / −2.0 | |
| `mixed-top3-after-editing-1.mp4` | the same after moving only #1's divider | 520 (17.33 s) | AAC | −14.0 / −2.0 | #3 and #2 unchanged in the document; segment keys same for #3 and #2; 2 cache hits |
| `reddit-story-over-gameplay.mp4` | post card read first, story over gameplay, text card outro | 484 (16.13 s) | AAC | −14.2 / −1.8 | 1 username replaced |

Each has a `.ffprobe.json`; `frames\` holds the last frame of every scene and the first frame of the next, and
`<name>-boundaries.png` puts them side by side. `summary.json` has the per-scene layouts, sounds and overlays.

I looked at the frames and screenshots: the badges, labels and title bar sit inside the safe area, the active caption
word is yellow, splits and the PiP inset land where the inspector says, the Reddit card shows the title without vote
counts, and every boundary frame belongs to the right scene.

## Bugs found and fixed while testing

- **Windows voice word timings were late** by a factor of 22050/16000: SAPI reports word positions as if the audio
  were 16 kHz. The voice is now written at 16 kHz, so captions line up with the speech. Takes made before the fix are
  regenerated automatically (the take format version changed). There is a regression test that checks the word after
  a sentence pause starts inside that pause.
- **The system voice list was always empty**: Windows PowerShell exits with code 2 when `-` is passed as an argument
  value. The *Speaker* list now shows David and Zira.
- Importing an **audio file** queued a poster job that failed in the background; audio files no longer get one.
- Adding a **missing file to the gameplay library** crashed the request; it now reports the file as not found.
- Loudness came out at −15.4 LUFS on speech with loudnorm's second pass (it switches to dynamic mode when peaks are
  limited); replaced with measured gain + limiter (results above: −13.9 to −14.2).

## Reuse manifest

**PurffleShorts @ `514fd25` (MIT, © 2025 Purffle)**, adapted with a header in each file (Phase 1 files listed in
`docs/phase-1/README.md`):

| Shorts Studio file | Adapted from | What |
|---|---|---|
| `backend/shorts_studio/timeline/words.py` | `purffle_shorts/timing.py` | `tokenize`, `norm`, `estimate_timings`, `anchored_timings`, `transfer_timings`, `caption_chunks`. Changed: English tokenizer, words stored as `[text, start, end]` |
| `backend/shorts_studio/render/raster.py` | `purffle_shorts/overlays.py` | font loading with variable weights, caption style presets, word-highlight caption states drawn with Pillow, the post card layout. Changed: everything is clamped to the safe area, cards never invent counts, images are keyed by a hash of their spec |
| `backend/shorts_studio/render/sfx.py` | `purffle_shorts/sfx.py` | whoosh, pop and hit synthesis. Changed: fixed seeds, three more effects |
| `backend/shorts_studio/speech/engines.py` | `purffle_shorts/tts.py` | Edge TTS with word-boundary events, the OS voice as the offline fallback |
| `backend/shorts_studio/render/plan.py` (additions) | `purffle_shorts/render.py` | Ken Burns `zoompan`, `xfade` chaining for loop joins, PNG playlists through the concat demuxer, `VOICE_CHAIN` for narration |

**ViralMint @ `f81630c` (AGPL-3.0-only)**: still no code, comments or prompts copied. Ideas reimplemented in Phase 2:
voice states per line (missing / ready / changed) with regeneration of just one line; the Shorts safe zone treated as
data that every overlay is placed against.

New in this phase: the resolver's layouts, loops and overlay specs, the gain envelopes for ducking, the take store,
the gameplay library with non-repeating picks, the new presets, the creative API, and the whole Phase 2 UI
(inspector sections, preview player, scene strip drag and drop, home forms, library, gameplay picker).

New third-party assets: the **Anton** and **Inter** fonts (SIL OFL 1.1, in `assets/fonts/` with their license texts);
**edge-tts** (LGPL-3.0) as a pip dependency. See `THIRD_PARTY_NOTICES.md`.

## Known limitations

- **Not rendered yet** (each shows a warning and is skipped): transitions other than a cut, pan motions on stills,
  moving crops (keyframes), Ken Burns on fitted stills, captions from a clip's own speech (Phase 3), non-libx264
  encoders.
- **Preview vs export**: positions, timing, overlays and captions come from the same data and the same PNGs. The
  preview doesn't apply the narration clean-up chain or the −14 LUFS normalisation, uses canvas blur instead of
  `gblur`, and cuts straight between loop copies where the export blends them (use *Preview join* for the exact join).
  A Ken Burns zoom in the preview is an approximation of `zoompan`.
- **Recording from the microphone** is built (MediaRecorder → upload) but not tested automatically: the headless
  browser has no microphone. The upload path it uses is tested through the API with a WAV file. Recorded and imported
  takes get estimated word timing, pinned to pauses.
- Edge voices need internet. The system voice is Windows SAPI (David, Zira); it sounds dated. macOS `say` is wired but
  untested; Linux has no offline voice yet.
- No per-scene voice choice in the UI (the format supports it); no style controls for text overlays beyond position
  and timing; no music start-offset control.
- Gameplay usage is recorded when a stretch is picked; deleting the scene doesn't free that stretch for later picks.
- Native file dialogs are still answered by intercepting `/api/dialog` in the browser tests.
- Tested on Windows only. Fonts live in `assets/fonts` next to the code, so the app must run from the repo (as now);
  packaging is Phase 4.

## Repo state

Nothing is committed yet (`git init` only). New scripts: `scripts/ui_e2e_p2.py`, `scripts/phase2_samples.py`.
Generated output stays in git-ignored `test-output\` and `data\`. Clipper (`C:\Users\ADMIN\Desktop\clipper`) is
unchanged: same commit `da5b5c7`, same local edits as before, `viralmint.db` and `clipper.lnk` last written
23-10-2026.
