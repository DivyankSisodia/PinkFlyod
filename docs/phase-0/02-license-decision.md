# 02 — License decision (needs your choice before any code is copied)

No code from either repository has been copied into this workspace. The schema and examples under `schema/` are
new work.

## The two options

**(a) Adopt AGPL-3.0 for the whole app and reuse ViralMint code directly.**
ViralMint is AGPL-3.0-*only* (not "or later"), so Shorts Studio would be AGPL-3.0-only. Every ViralMint file keeps
its SPDX header and copyright line. MIT code from PurffleShorts can sit inside an AGPL app with its notice. If you
ever let other people use a modified version over a network (a hosted version), section 13 requires offering them the
source. You could not later relicense the app as closed or permissive without removing all ViralMint-derived code.

**(b) Use ViralMint only as a design reference, reimplement what is needed, and reuse MIT PurffleShorts code with
its notice.** The app can then use any license you like (MIT is the simplest fit).

One caveat on (b): a strict clean-room process uses two people, one who reads the original and writes a spec, and
one who implements from the spec without seeing the code. I have read ViralMint's source during this inspection,
so I cannot offer that. What I can do is implement from the functional description in `01-reference-inspection.md`,
copy no code, comments, prompts or file structure, and write my own tests. Copyright covers expression, not ideas
such as "cache a voice take under a hash of voice + text". If you need a formal clean room, the ViralMint-inspired
parts should be implemented by someone else from the spec.

## Recommendation: (b)

- What ViralMint does well is the editing model and the cutting bench, and both need to be rebuilt anyway: its
  document has one layout per project and no per-scene source audio, and its UI is JSX + MUI while this app is
  React + TypeScript.
- The parts that are expensive to get right in FFmpeg (two-stage render, ducking, two-pass loudnorm, jump cuts,
  word timing, ASS captions) are in PurffleShorts under MIT.
- (b) keeps your licensing options open at a cost I estimate at a few extra days across Phases 1–3.

## Reuse manifest under option (b)

### From PurffleShorts @ `514fd25` (MIT, © 2025 Purffle) — reuse or adapt, with notice

Each adapted file gets a header line `Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25`
and the MIT text goes in `THIRD_PARTY_NOTICES.md`.

| PurffleShorts file | What | How | Shorts Studio target | Phase |
|---|---|---|---|---|
| `purffle_shorts/ffmpeg.py` | `run` (progress parsing, timeout, kill), `probe`, `loudnorm_report`, `loudness`, `silences`, `duration` | adapt | `backend/shorts_studio/render/ffmpeg.py` | 1 |
| `purffle_shorts/render.py` | `_encode_args`, cover-crop / Ken Burns parts of `prepare_segment` | adapt | `render/video_graph.py` | 1–2 |
| `purffle_shorts/render.py` | `mix_audio` two-pass linear loudnorm, voice clean-up chain | adapt | `render/audio_graph.py` | 2 |
| `purffle_shorts/render.py` | `compose` overlay chain (`overlay … format=yuv420`, ASS pass) | adapt | `render/video_graph.py` | 1–2 |
| `purffle_shorts/timing.py` | `tokenize`, `estimate_timings`, `anchored_timings`, `transfer_timings`, `caption_chunks`, `srt` | reuse, light edits | `timeline/words.py` | 2 |
| `purffle_shorts/overlays.py` | `PillowCaptions` (one PNG per caption state + concat playlist), `_text_box`, `hook_png`, `load_font`/`_open_font`, `CapStyle` presets, `is_emphasised` | adapt (safe-area placement, shared by preview and export) | `render/raster.py` | 1–2 |
| `purffle_shorts/overlays.py` | `post_card_png` | adapt, **remove invented vote/comment counts** | `render/cards.py` | 2 |
| `purffle_shorts/overlays.py` | `write_ass` | not planned (kept as a fallback option for non-Latin scripts later) | — | — |
| `purffle_shorts/sfx.py` | synthesised whoosh / pop / hit | reuse | `render/sfx.py` | 2 |
| `purffle_shorts/tts.py` | `_edge` WordBoundary capture, `_system` OS voice, `_align_faster_whisper`, cache-key idea | adapt | `speech/edge.py`, `speech/system.py`, `speech/align.py` | 2 |
| `purffle_shorts/clipper.py` | `keep_ranges`, `retime`, `select_expr`, `audio_cut`, `sentences`, `_snap`, blur branch of `crop_filter` | adapt | `transcribe/cuts.py`, `render/video_graph.py` | 3 |
| `purffle_shorts/llm.py` | OpenAI-compatible client, JSON-schema replies with fallback, provider fallbacks | adapt | `ai/llm.py` | 3 |
| `purffle_shorts/script.py` | Script Doctor rubric and rewrite-only-if-better rule | adapt | `ai/script_doctor.py` | 3 |
| `purffle_shorts/seo.py` | YouTube search suggestions | adapt (add source, timestamp, granularity) | `discovery/youtube_suggest.py` | 3 |
| `purffle_shorts/topics.py` | Google Trends RSS, Reddit RSS fetchers | adapt (add provenance) | `discovery/google_trends.py`, `discovery/reddit_rss.py` | 3 |
| `purffle_shorts/media.py` | Pexels/Pixabay search and candidate scoring | adapt | `media/stock/*.py` | 3 |
| `purffle_shorts/envfile.py` | `.env` read/write/mask | adapt | `config/envfile.py` | 3 |

Not reused: `pipeline.py` (autopilot), `youtube.py`, `crosspost.py`, `analytics.py`, `autopilot.py`, `studio.py` and
`web/*` (stdlib server + vanilla JS), `mcp_server.py`, `planner.py`, `history.py`.

### From ViralMint @ `f81630c` (AGPL-3.0-only) — design reference only, reimplemented

| ViralMint file | Idea taken | Shorts Studio target | Phase |
|---|---|---|---|
| `services/studio_doc.py`, `studio_ops.py`, `studio_store.py` | Stable scene IDs; edits checked against a revision number | `project/store.py`, schema | 1 |
| `frontend/.../studio/useStudioProject.js` | Undo/redo as document snapshots | `frontend/src/state/history.ts` | 1 |
| `frontend/.../clip/bench/*` | In/out handles, first/last frame of the cut, filmstrip | `frontend/src/trim/*` | 1 |
| `services/output_validator.py` | Check the output with ffprobe before calling it done | `render/verify.py` | 1 |
| `core/ws_manager.py`, `agents/job_helper.py` | Job progress over WebSocket, cancel flag | `jobs/*` | 1 |
| `services/voice_take_service.py` | Voice states (none/generating/ready/stale/failed) | derived staleness in `speech/takes.py` | 2 |
| `services/safe_zones.py` | Insets as data, one place to change them | `timeline/safe_area.py` (YouTube Shorts numbers) | 2 |
| `services/clip_windows.py` | Snap cuts to sentence boundaries | `transcribe/highlights.py` | 3 |
| `services/whisper_service.py` | Model download progress, unload when idle | `transcribe/whisper.py` | 3 |
| `download/*` | yt-dlp progress and clear failure messages | `media/url_import.py` | 3 |
| `core/crypto.py` | Encrypt stored keys at rest | `config/secrets.py` (Fernet via `cryptography`) | 3 |

## Additional files reused under option (a)

If you choose (a), these ViralMint files would be adapted directly instead of reimplemented, keeping their AGPL
headers: `services/output_validator.py`, `services/voice_take_service.py`, `services/whisper_service.py`,
`services/clip_windows.py`, `services/safe_zones.py`, `core/crypto.py`, `core/ws_manager.py`,
`download/opts.py`, `download/progress.py`, `download/classify.py`. The bench UI (`components/clip/bench/*`) would
be ported from JSX + MUI to TypeScript. All of them depend on ViralMint's settings, SQLAlchemy models and job
helpers, so "reuse" here still means editing each file.

## Third-party dependencies (both options)

| Package | Version seen | License | Note |
|---|---|---|---|
| FFmpeg (gyan.dev full build) | 9.0.2 | GPL-3.0 (with libx264) | Called as a separate program, not linked. If Phase 4 bundles it, its license and source offer must ship too. |
| faster-whisper / ctranslate2 | 1.2.1 / 4.8.3 | MIT | |
| edge-tts | 7.3.1 | LGPL-3.0 | Imported unmodified; fine in an MIT or AGPL app. Needs internet. |
| yt-dlp | 2026.10.21 | Unlicense | Phase 3 |
| FastAPI / uvicorn / pydantic | 0.141 / 0.52 / 2.14 | MIT / BSD-3 / MIT | |
| cryptography | 50.0.2 | Apache-2.0 or BSD-3 | |
| Pillow | 12.3.0 | MIT-CMU | |
| React 18, Vite, zustand, immer, dnd-kit | — | MIT | |
| Caption fonts (Anton, Inter) | — | SIL OFL 1.1 | Bundled from Google Fonts with `OFL.txt` |
