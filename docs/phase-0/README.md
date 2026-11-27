# Shorts Studio — Phase 0: discovery and design

Status: **waiting for your review.** No application code has been written, and no code from either reference
repository has been copied.

| Document | Contents |
|---|---|
| [01-reference-inspection.md](01-reference-inspection.md) | Revisions and licenses inspected, four traced input→MP4 paths, module map, feature map table |
| [02-license-decision.md](02-license-decision.md) | Option (a) AGPL vs (b) reimplement, with the exact reuse manifest for each |
| [03-architecture.md](03-architecture.md) | Stack, ports, folders, the single resolve → plan → FFmpeg pipeline, preview parity, persistence, jobs, compliance, testing, phases, limitations |
| [04-project-schema.md](04-project-schema.md) | The versioned project document: blocks, derived values, semantic rules, presets, migration |
| [05-ui-sitemap.md](05-ui-sitemap.md) | Pages, editor layout, Quick Short path |
| [`../../schema/project.v1.schema.json`](../../schema/project.v1.schema.json) | JSON Schema (Draft 2020-12) |
| [`../../schema/examples/`](../../schema/examples/) | Mixed Top 3, silent countdown, 13 s Quick Short, narrated explainer |

## Decisions needed before Phase 1

1. **License:** (a) AGPL-3.0-only for the whole app, reusing ViralMint code, or (b) ViralMint as design reference
   only, MIT PurffleShorts code reused with notices. Recommended: (b), with the app under MIT.
2. **Repo location:** use this workspace (`c:\Users\ADMIN\Desktop\Money-PinkFLyod`) as the repo root, or a
   `shorts-studio\` subfolder in it.
3. **Data folder:** `data\` inside the app folder (proposed: one folder to back up or delete), or
   `%LOCALAPPDATA%\ShortsStudio`.
4. **Ports:** 17860 (app) and 17861 (dev server only). Your clipper keeps 16888.
5. **Silent exports:** MP4 with no audio stream (proposed), or a silent AAC track.
6. **Offline narration:** Edge TTS needs internet. Offline options are recording, importing, or the Windows voice.
   Is that acceptable, or do you want a local neural voice (for example Piper) evaluated in Phase 2?
7. **Captions rendered as images (Pillow) rather than libass**, so the preview matches the export. This limits
   captions to Latin-script languages for now, which fits en-US/en-CA.
8. **Safe-area insets:** top 320, bottom 400, left 60, right 180 px at 1080×1920 (from two published templates,
   not an official YouTube spec).

## Phase 0 verification

- Both repositories cloned and inspected: ViralMint `f81630c` (upstream) and `da5b5c7` (your install),
  PurffleShorts `514fd25`.
- `C:\Users\ADMIN\Desktop\clipper` checked with read-only commands only (`git log`, `git status`, `git diff --stat`,
  directory listings, reading `.env` key *names*). Its files, database and `clipper.lnk` shortcut are unchanged.
- FFmpeg 9.0.2 has every filter and encoder the design relies on (checked with `ffmpeg -filters` / `-encoders`).
- Schema check (jsonschema 4.26, Python 3.13): the schema passes the Draft 2020-12 metaschema check; all four
  examples validate; twelve invalid variants are rejected; switching #1 of the mixed example to PiP leaves #3 and #2
  byte-identical; reordering keeps an entry's media and label together.
- Google Trends RSS answered for `US`, `CA`, `US-WA` and `CA-BC` with different lists; YouTube suggestions answered
  for `gl=US` and `gl=CA` with near-identical lists.

Phase 0 has no automated test suite or rendered video yet. Those start in Phase 1.
