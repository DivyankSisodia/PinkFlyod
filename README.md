# Shorts Studio

A local-first YouTube Shorts studio for one creator: bring in footage, frame it vertically, preview it, and export
a 1080×1920 MP4. One versioned JSON project format, one FFmpeg render pipeline, no GPU or API keys needed.

The studio supports rankings, per-scene voice takes, looping gameplay, captions, music ducking, and mixed formats.
See `docs/phase-0/` for the design and `docs/phase-1/README.md` and `docs/phase-2/README.md` for earlier verification.

## Quick start (Windows)

Needs Python 3.11+, Node.js 18+ and FFmpeg (`winget install Gyan.FFmpeg`).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.venv\Scripts\python -m shorts_studio
```

The app opens at http://127.0.0.1:17860 and keeps everything in `data\` (set `SHORTS_STUDIO_DATA` to move it).

## URL imports and optional AI

- **New short** imports public YouTube videos and Instagram Reels into editable scenes. Add a gameplay link to use a split-screen or picture-in-picture layout. The first selection is up to 13 seconds per foreground clip and can be retrimmed in the editor.
- **Gameplay library** accepts a public YouTube, Reel, direct MP4, or direct WebM link and saves the video under `data/gameplay/`. The importer accepts individual videos up to 512 MiB. Sites may restrict downloads for some links.
- **AI settings** lets you save an OpenCode Go key and writing model, and an ElevenLabs key, voice model, and speaker. Keys are written to `data/.env` on this computer. Existing projects keep the voice choices saved in their documents.
- **Local files & scripts → From a topic** sends the topic to your chosen OpenCode Go model and returns an editable narration draft. In the editor, use **Voice** to choose ElevenLabs and generate takes with caption timings. Local editing and rendering remain available without either key.
- **Activity** shows recent jobs, their timestamped checkpoints, and any error messages. Open a completed draft, project, or downloaded gameplay from its job. The app asks you to confirm rights at export when the project uses downloaded footage.

## Tests

```powershell
.venv\Scripts\python -m pytest                 # backend, including real FFmpeg renders
cd frontend; npm test; npm run typecheck       # frontend
.venv\Scripts\python scripts\ui_e2e.py         # Phase 1 browser walk-through (pip install -e ".[ui-test]", needs Edge)
.venv\Scripts\python scripts\ui_e2e_p2.py      # Phase 2 browser walk-through
.venv\Scripts\python scripts\phase1_samples.py # sample renders into test-output\phase-1\samples
.venv\Scripts\python scripts\phase2_samples.py # sample renders into test-output\phase-2\samples
```

## License

MIT. Portions adapted from PurffleShorts (MIT); bundled fonts Anton and Inter (SIL OFL 1.1); see
`THIRD_PARTY_NOTICES.md`.
