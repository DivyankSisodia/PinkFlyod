# 03 — Proposed architecture

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+ (3.13.0 is installed), FastAPI, uvicorn | Matches both references; faster-whisper, edge-tts, yt-dlp and Pillow are Python. |
| Frontend | React 18 + TypeScript + Vite, zustand + immer (state and undo), dnd-kit (drag reorder), plain CSS modules | Small dependency set; no UI framework is needed for an editor this size. |
| Storage | One project = one JSON file (source of truth); SQLite (`sqlite3` stdlib, WAL) for the project index, media library, gameplay library, jobs and settings | The JSON file can be read, diffed and backed up by hand. The index can be rebuilt from the files. |
| Render | FFmpeg + ffprobe only (external processes) | Every filter needed is present in the installed 9.0.2 build. |
| Text overlays | Pillow, rasterised to PNG on the server | The preview shows the same PNGs that FFmpeg overlays, so captions, badges and cards look identical in both. |

Alternatives considered and rejected:

- **Electron or Tauri shell.** Adds a second runtime and a packaging pipeline. A local web app opened by a launcher
  does the same job; both references work this way.
- **MoviePy or Remotion as the renderer.** MoviePy re-encodes per operation and is slow on CPU. Remotion needs
  Chromium per render and a separate composition language. Either would mean a second pipeline next to FFmpeg.
- **ASS subtitles (libass) for captions.** Fine for export, but the browser cannot draw ASS identically, so preview
  text would drift from export. Pillow PNGs avoid that. libass remains available if non-Latin scripts are added later.
- **Server-rendered preview only.** Exact, but too slow for scrubbing. Used instead as an "exact frame" check (§6).

## 2. Process, ports and folders

- One Python process: `uvicorn shorts_studio.app:app --host 127.0.0.1 --port 17860`. It serves the built SPA, the
  REST API and one WebSocket. Vite dev server (development only) on `127.0.0.1:17861`. Your clipper uses 16888.
- Requests whose `Host` header is not `127.0.0.1:17860` or `localhost:17860` are refused (DNS-rebinding guard), and
  writes require a per-launch token served to the SPA.
- FFmpeg, ffprobe and Whisper run as child processes, so cancelling means terminating a process.

```
<repo root>/                     # proposed: this workspace, c:\Users\ADMIN\Desktop\Money-PinkFLyod
  backend/shorts_studio/
    app.py  config/  db/  api/  jobs/
    schema/      # pydantic models (source of truth), migrations, semantic checks
    project/     # store (atomic save, revisions), relink, presets/, compliance
    timeline/    # resolve.py (pure), layout.py, safe_area.py, ranking.py, words.py, audio_plan.py
    render/      # plan.py (graph builder), video_graph.py, audio_graph.py, raster.py, cards.py, sfx.py,
                 # ffmpeg.py, verify.py, cache.py
    media/       # probe, import, proxies, thumbnails, filmstrip, waveform, gameplay library; url_import, stock/ (Phase 3)
    speech/      # takes.py, edge.py, system.py, openai_compat.py, recording.py, align.py
    transcribe/  # whisper.py, highlights.py, cuts.py (Phase 3)
    ai/          # llm.py, draft.py, script_doctor.py, localize.py (Phase 3)
    discovery/   # youtube_suggest.py, google_trends.py, reddit_rss.py (Phase 3)
  frontend/src/  # home/, editor/, trim/, timeline/, inspector/, player/, model/ (ops + derived ranks), state/
  schema/        # project.v1.schema.json (exported from pydantic, checked in), examples/, fixtures/
  tests/         # pytest; frontend tests live next to the code (vitest)
  data/          # gitignored; override with SHORTS_STUDIO_DATA
    studio.db
    projects/<project_id>/project.json, history/rev-000042.json.gz, renders/<render_id>.mp4
    media/imports/ media/downloads/ proxies/ thumbs/ filmstrips/ waveforms/
    gameplay/<gpc_id>/…      music/      testmedia/
    cache/takes/ cache/segments/ cache/raster/
    models/whisper/          logs/
  .env                       # optional keys; never logged
```

## 3. One pipeline

```
project.json (schema_version N)
   │ migrate (vN → current) ── validate: JSON Schema + semantic checks (§4 of 04-project-schema.md)
   ▼
resolve(project, probes)  ── pure function, no I/O, deterministic
   │   → ResolvedTimeline: per scene start/end, per layer source window + crop rect + slot rect,
   │     loop/freeze joins, derived ranks, caption chunks with times and pixel boxes,
   │     overlay boxes, audio events with gain envelopes, warnings
   ├────────────► preview: GET /api/projects/{id}/timeline → browser player (canvas + WebAudio)
   └────────────► plan(timeline, profile, window?) → FFmpeg argv lists → job runner → verify → MP4
                    profiles: export (1080×1920@30, libx264 CRF 20)
                              proxy  (540×960, ultrafast)      # whole-project or range preview
                              frame  (one PNG at time t)       # "exact frame" check
```

Every format (ranking, story, quick short, gameplay, mixes of them) goes through this one path. Presets only
create documents; they have no render code.

### 3.1 Resolver rules

- Scene duration by `duration.driver`: `primary` = (out − in) / speed; `narration` = offset + take duration +
  tail pad (estimated from word count while no take exists, flagged as estimated); `fixed` = `fixed_s`.
  Scene start times are the running sum, minus crossfade overlaps. They are never stored, so editing one
  narration line moves every later scene without touching their data.
- Displayed rank: among enabled scenes with `rank.include`, in order; `descending` gives N…1, `ascending` 1…N.
- `continue_from_previous`: the layer's in point becomes the out point of the previous use of the same source,
  wrapping if `when_short = loop`.
- `when_short`: `loop` produces join times (shown in the UI and previewable), `freeze_last` holds the last frame,
  `slow_to_fit` lowers speed, `black` pads.
- Crop: from source size (after rotation), slot size, `focus` and `zoom`, compute the source crop rectangle in
  pixels, clamped inside the source. The same function is ported to TypeScript and both are tested against shared
  fixtures in `schema/fixtures/`.
- Safe area: YouTube Shorts insets scaled from 1080×1920. Captions, badges, labels, hook, title bar and cards are
  placed inside it; anything that would cross it is moved in and reported as a warning.
- Audio: one event per audible layer per scene (source audio, narration, music, SFX) with start, source offset,
  gain and fades. Ducking is a gain envelope computed from narration word times (attack/release ramps), applied in
  FFmpeg with `volume=…:eval=frame` and in the preview with WebAudio gain automation at the same points. This
  replaces a sidechain compressor so that preview and export duck identically.

### 3.2 Render plan

- **Stage 1, one encode per scene** (run in parallel, `max(1, cpu_count // 4)` at a time): inputs seeked with `-ss`,
  `trim`/`setpts`, `crop`, `scale`, layout composition (`overlay`, `vstack`-equivalent placement, blurred copy with
  `gblur`), loops (`loop`/`xfade` at joins), raster overlays for that scene (badge, label, captions, cards) via a
  concat playlist of PNGs, `fps=30`, `format=yuv420p`. Intermediate: libx264 `ultrafast` CRF 15, video only.
  Output is cached under a hash of the resolved scene spec plus source fingerprints, so changing only scene #1
  re-encodes only scene #1.
- **Audio, one pass + a measurement pass**: all audio events mixed into one 48 kHz stereo WAV (`atrim`, `adelay`,
  `volume` envelopes, `amix normalize=0`, short edge fades), then two-pass `loudnorm` (`I=-14:TP=-1.5:LRA=11`,
  `linear=true`). If no event is audible, no audio is produced.
- **Stage 2, the one final encode**: concat or `xfade` the scene segments, overlay project-wide rasters (title bar,
  hook, watermark), mux the soundtrack, libx264 CRF 20 `-pix_fmt yuv420p -r 30 -movflags +faststart`, AAC 192 kb/s
  48 kHz. Silent projects get no audio stream (or a silent AAC track if `when_silent = silent_aac`).
- **Verify** (`render/verify.py`) before the job reports success: ffprobe width, height, SAR, frame rate, codec,
  pixel format, duration (±1 frame of the resolved total), audio stream present exactly when expected, and
  `ebur128` integrated loudness within ±1 LU of −14 when audio exists. Failures fail the job with the numbers.
- Progress: FFmpeg `-progress pipe:1` `out_time_us` against the expected duration, weighted by stage.

## 4. Narration and partial regeneration

- A take belongs to one scene and records `text_sha256`, voice and timing. It is stale when the scene's text or
  effective voice no longer match (derived, not stored).
- Providers: Edge TTS (free, **needs internet**, native word timings), OS voice (Windows SAPI / macOS `say`, offline),
  OpenAI-compatible TTS (BYOK), recorded in the browser (MediaRecorder → WAV), imported file. Recorded/imported
  and OS-voice takes get word timings from faster-whisper when the model is installed, otherwise from
  `anchored_timings` (pauses pinned with `silencedetect`).
- Take audio is cached under a hash of provider, voice, rate and text, so regenerating an unchanged line is free.
- Editing one line: that scene's take turns stale → a job regenerates only that take → the editor attaches it →
  the resolver recomputes scene times. Other scenes' data is untouched, and only the edited scene's Stage 1
  segment and the audio pass are re-rendered (later scenes' video segments are reused because their content did
  not change, only their start time).

## 5. Persistence, autosave, undo, relink

- Single writer: the open editor owns the document. Background jobs produce artifacts (takes, transcripts, renders)
  and announce them; the editor attaches them. If no editor is open, the server applies pending results on next open.
- Save: `PUT /api/projects/{id}` with the whole document and `base_revision`. The server validates, writes
  `project.json.tmp`, flushes, `os.replace`s it over `project.json`, increments `revision`, and keeps the previous
  revision gzipped in `history/` (last 50). A mismatched `base_revision` (second tab) returns 409 and the second tab
  becomes read-only.
- Autosave: 800 ms after the last edit, on window blur and on `beforeunload` (`sendBeacon`). The top bar shows
  "Saved", "Saving…" or "Not saved: <reason>".
- Undo/redo: client-side stack of immutable snapshots (immer structural sharing), 200 steps, grouped per gesture
  (one crop drag = one step).
- Relink: on open, every source is checked (exists, size, mtime, `sample_sha256`). Missing sources are listed with
  their last path; "Relink" opens a picker and compares the new file's fingerprint (duration and dimensions must
  match; hash mismatch warns but is allowed). "Search a folder" relinks every missing file found by name +
  fingerprint. Rendering is blocked while a used source is missing; editing is not.
- Migrations: `schema_version` is an integer. Each `vN → vN+1` step is a pure function with fixture tests. A
  document from a newer app version opens read-only.

## 6. Preview

- The player draws each frame on a 540×960 canvas from the resolved timeline: one `<video>` per visible source
  (proxy file if the browser cannot decode the original), `drawImage` with the resolver's crop and slot rectangles,
  blurred fill via canvas `filter: blur()`, raster overlays drawn as the same PNGs the export uses, and WebAudio for
  every audio event with the same gain envelopes.
- Safe-area guide overlay toggle (Shorts UI silhouette), timecode, scene boundaries, loop-join markers.
- **Exact frame**: renders the current time through the export graph (`frame` profile) and shows it beside the live
  preview. **Preview range** renders 2–5 s around the playhead or a loop join (`proxy` profile).
- Known gaps: canvas blur and FFmpeg `gblur` differ slightly; loudness normalisation is not applied live (the
  preview applies the gain measured on the last render, if any).
- Proxies: 540-wide H.264 with keyframes every 0.5 s, generated in the background for sources the browser can't play
  or for files over 1080p, so scrubbing stays responsive.

## 7. Jobs and the "Open MP4" button

- In-process job queue: one render at a time by default; take generation and proxy jobs in parallel (limit 3).
- WebSocket `/api/ws` messages: `job.progress {job_id, kind, pct, stage, eta_s}`, `job.done {job_id, result}`,
  `job.failed {job_id, error}`, `job.cancelled {job_id}`, `artifact.ready {project_id, scene_id, take}`.
- `POST /api/jobs/{id}/cancel` terminates the FFmpeg process, removes partial files and marks the job cancelled.
- `POST /api/renders/{id}/open` and `/reveal` call `os.startfile` (Windows) or `open` / `open -R` (macOS) on the
  rendered file. Only render IDs are accepted, never paths.

## 8. Media import and the gameplay library

- Local import: a native file dialog opened by the backend (tkinter 8.6, present) returns absolute paths, so files
  are referenced in place and can be relinked. Drag-and-drop into the browser uploads a copy into `data/media/imports`.
- Each import is probed (ffprobe: duration, size, fps, rotation, codecs, audio) and fingerprinted; thumbnails,
  a filmstrip and a waveform are generated in the background.
- Ownership is asked once per import batch: "My recording", "Licensed", "Someone else's". URL downloads are
  "Someone else's" unless you change it.
- Gameplay library: files copied into `data/gameplay/<gpc_id>/`, with tags and a usage table
  `(clip_id, in_s, out_s, project_id, scene_id, used_at)`. "Random stretch" picks a start whose range does not overlap
  earlier uses of that clip; when none is left, it picks the least recently used. The pick is stored in the segment
  (with its seed), so preview and re-export stay identical. Shipped samples are generated by FFmpeg (procedural
  patterns), not third-party footage, with a reminder to use your own recordings or licensed footage.

## 9. Compliance

- Rights gate: rendering is blocked when any used source is `url_download` or ownership `third_party`/`unknown`
  until the project's rights box is ticked. The box text is versioned; the tick stores time and statement version.
- Reused-content warning (non-blocking): shown when more than 60 % of the rendered time is third-party footage in
  scenes with no narration, no captions, no ranking and no text overlays. It suggests adding commentary,
  narration, ranking or captions and links to
  [YouTube's monetization policies](https://support.google.com/youtube/answer/87047), which review reused content
  such as clips and compilations. It never claims anything about monetization or reach.
- Reddit-style stories: source URL stored on the card; on paste, `u/name` mentions in the text are replaced with
  "the poster" (reviewable), and the card's author is hidden unless you choose otherwise. No invented vote counts.

## 10. Audience, localization and discovery (Phase 3)

- Audience setting (US / CA / Both, optional state or province) sets defaults you can see and change: voice list
  order (`en-US-*` or `en-CA-*`), spelling (color/colour), units (mi/km, °F/°C), date format.
- Localization proposes a diff (spelling, units, place names you choose, e.g. Seattle → Vancouver) shown hunk by
  hunk; nothing changes until you accept. Rule-based offline; an LLM can suggest extra hunks when configured.
- Every trend item shows source, collection time and true granularity: Google Trends RSS `geo=US`/`CA` →
  country; `geo=US-WA`/`CA-BC` → state/province; YouTube suggestions → "country hint (gl=US), not geo-filtered";
  Reddit/RSS → "no geographic data". Editorial suggestions (LLM or rules) use a different visual style and label.
  The UI never estimates views or reach.

## 11. Keys and security

- Keys come from `.env` or are stored encrypted in SQLite (Fernet; key file in `data/` with user-only ACL).
  The settings API is write-only for keys and returns masked values. A logging filter redacts anything that looks
  like a stored key, `Authorization` headers and `api_key=` query strings.
- Untrusted input: file paths come from the native dialog or are resolved under `data/`; FFmpeg is always called
  with argument lists, never a shell string; text placed in filter graphs is escaped or passed via files.
- Bound to `127.0.0.1`. No telemetry.

## 12. Testing and verification

- **Schema**: JSON Schema checks on examples and fixtures; pydantic ↔ JSON Schema equality test; semantic checks;
  migration fixtures.
- **Presets and ops**: ranking reorder keeps media and label together and recomputes ranks (asc/desc); Quick Short
  cap; gameplay pick non-repetition and determinism; narrated single-line regeneration leaves other scenes
  byte-identical; changing #1's layout leaves #3 and #2 byte-identical (both already checked against the Phase 0
  schema, see `README.md`).
- **Render-graph builder**: golden tests of the generated argv/filter graphs for fixture timelines (no FFmpeg needed),
  plus a filter-graph syntax check with `ffmpeg -filter_complex … -f null` on tiny `lavfi` inputs.
- **Real renders** (marked `@render`): owned test media made with FFmpeg `lavfi` (`testsrc2` with burned timecode,
  coloured fields, `sine` tones) and an offline voice; each render is verified with ffprobe + `ebur128`, and frames at
  scene boundaries are extracted and checked by pixel sampling (crop position, split divider, badge inside the
  safe area) and saved for you to look at.
- Frontend: vitest for ops, derived ranks and crop math against the shared fixtures.

## 13. Phase plan

| Phase | Delivers |
|---|---|
| 1 | Repo skeleton, pydantic schema + export, project store (atomic save, revisions, history), relink, media import + probe + proxy + filmstrip, resolver (full layout, fill/fit/blur, one segment per scene), render plan + job + WebSocket + cancel + verify, home screen, editor shell with canvas preview, trim bench (in/out, 12–15 s Quick Short cap), crop/reframe, export dialog with Open MP4, undo/redo, autosave. Proof: landscape → 13 s vertical MP4, verified with ffprobe, reopened. |
| 2 | Ranking, story (takes: Edge / OS voice / record / import; single-line regeneration), gameplay library + split/PiP/loops with join preview, music + ducking + −14 LUFS, raster captions in the safe area, Reddit card, SFX, scene split/duplicate/mute, mixed-format editing, rights gate, reused-content warning. |
| 3 | yt-dlp import, faster-whisper transcription + highlight review, BYOK/Ollama drafting + Script Doctor, Pexels/Pixabay, US/CA localization diff and discovery with provenance. |
| 4 | One-click Windows launcher (`Shorts Studio.lnk` → `pythonw` launcher, starts the server if needed, opens the browser), macOS `start.command` instructions, sample editable project, the five final verification renders and the persistence regression test. |

## 14. Known limitations and risks

- Edge TTS needs an internet connection. Fully offline narration means recording, importing, or the OS voice
  (Windows SAPI voices sound robotic compared with Edge).
- Whisper needs a one-time model download (a few hundred MB for `small`, less for `base`). Your clipper install already
  has a faster-whisper model in `clipper\storage\models\whisper`; I can copy it (read-only) in Phase 3 if you allow.
- The safe-area insets are not an official YouTube specification. They are the larger of two published 1080×1920
  templates ([Kreatli](https://kreatli.com/safe-zone-checker/youtube-safe-zone-checker): top 309, bottom 380, sides 49;
  [Fooh](https://fooh.com/tools/safe-zones/youtube-shorts): top 234, bottom 366, left 53, right 174), rounded up to
  top 320, bottom 400, left 60, right 180. That leaves an 840×1200 safe box. They are editable per project.
- Browser decoding: HEVC, ProRes, some VP9/AV1 files need a proxy before they preview; export always uses the original.
- English only (en-US, en-CA). French-Canadian voices and spelling are not planned.
- macOS will be documented and launch-tested only if you have a Mac available; all testing here is on Windows 11 Pro.
