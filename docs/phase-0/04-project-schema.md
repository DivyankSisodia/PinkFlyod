# 04 — Project document, schema version 1

Files:

- `schema/project.v1.schema.json`: JSON Schema (Draft 2020-12)
- `schema/examples/top3-gaming-fails.json`: the mixed example (#3 original audio, #2 narrated, #1 gameplay split)
- `schema/examples/silent-countdown.json`: three entries, every audio track off
- `schema/examples/quick-short-13s.json`: 13 s from a 4K landscape source, 15 s cap, moving crop
- `schema/examples/narrated-explainer.json`: three narrated lines, image + stock + text card, localized to CA-BC

In Phase 1 the pydantic models become the source of truth. The JSON Schema is exported from them and checked in,
and a test fails if the two drift. TypeScript types are generated from the exported schema.

## 1. Building blocks

| Block | Where | Notes |
|---|---|---|
| Sources | `sources{src_id → source}` | File path, origin (local file, URL download, stock, AI image, gameplay library, generated, recording), ownership, fingerprint for relink, attribution, transcript reference. |
| Segments | `segments{seg_id → segment}` | `source_id` + `in_s`/`out_s` on the source. No timeline position. A trim-bench selection is a segment before it is placed in a scene. |
| Scenes | `scenes[]` | Stable `id`. Array order is timeline order. A scene owns its layout, layers, narration, per-scene audio switches, caption mode, overlays, rank inclusion, transition and SFX. |
| Layouts | `scene.layout` | `full`, `split` (divider 0.2–0.8, primary top or bottom, gap), `pip` (inset layer, position, width, aspect, border). "Blurred fill" in the UI = `full` + primary `reframe.mode = blur_fill`. |
| Layers | `scene.layers.primary`, `.secondary` | Each is a segment, image, text card or colour, with its own `reframe` (fill / fit / blur_fill, focus, zoom, optional keyframes) and `playback` (speed, loop / freeze / slow / black, loop crossfade, continue from previous). |
| Audio tracks | `scene.audio` + `audio.music` + `scene.sfx` + `scene.narration` | Primary sound, secondary sound (gameplay), narration and music each switch on or off per scene, with gain. Ducking settings are project-wide; layers opt in with `duck_under_narration`. |
| Captions | `captions` (style, position) + `scene.captions` (mode, manual cues, word edits) | Modes: inherit, off, narration words, source transcript, manual timed cues. |
| Overlays | `overlays` (hook, title bar, watermark) + `scene.overlays` (rank badge, label, Reddit card, text) + `ranking` | Badge style and direction live in `ranking`; whether a scene shows it lives in the scene. |
| Compliance | `compliance` | Rights confirmation (with time and statement version) and the reused-content warning dismissal. |
| Audience | `audience` | Country, optional region, language, spelling, units, log of applied localizations. |

## 2. Values that are derived, never stored

Storing these would let them go out of sync with the data they come from.

- Scene start/end times and total duration (from order, `duration.driver`, segment lengths, take durations, crossfades).
- Displayed rank numbers (from order, `rank.include`, `ranking.direction`).
- Whether a take is stale (`take.text_sha256` vs. the current text; take voice vs. the effective voice).
- Safe-area pixel rectangle (from `output.safe_area` scaled to the output size).
- Whether a source is missing (checked against the file system on open).
- Whether the project needs rights confirmation (from the sources actually used by enabled scenes).

## 3. Semantic rules (checked in code, not expressible in JSON Schema)

1. Every `segment.source_id`, `visual.source_id`, `visual.segment_id`, `music.source_id` and SFX `source_id` exists.
2. `in_s < out_s ≤ source.duration_s`; `out_s − in_s ≥ 1/fps`.
3. Scene IDs are unique; source and segment keys are unique by construction.
4. `layout.type = split` or `pip` requires `layers.secondary ≠ null`; `full` ignores `secondary` (kept, not rendered,
   so switching layouts back and forth loses nothing).
5. Image layers reference `kind = image` sources; segment layers reference `kind = video` sources; music references
   `kind = audio` or `video` with audio.
6. `duration.driver = narration` requires `narration` with non-empty text; `primary` requires a segment primary layer.
7. Total resolved duration ≤ `output.max_duration_s` when set (Quick Short: 15). The trim bench enforces it while
   dragging; the validator blocks export if it is exceeded.
8. Total resolved duration ≤ 180 s (YouTube Shorts maximum); a warning above 60 s.
9. Rendering requires `compliance.rights.confirmed = true` when any used source has `origin = url_download` or
   `ownership ∈ {third_party, unknown}`.
10. Rendering requires every used source to be present with a matching fingerprint (or relinked).
11. Manual caption cues and text overlays: `start_s < end_s ≤ scene duration` (checked after resolving).
12. Overlay boxes are placed inside the safe area; the resolver moves them in and reports a warning if needed.

## 4. How the presets build documents

Presets are functions `preset(input) → document`. After creation the document is ordinary and every field is
editable; `origin.preset` is only a label.

| Preset | Creates |
|---|---|
| Quick Short | One scene, `driver = primary`, primary = one segment (12–15 s), `reframe.mode = fill` with focus at the centre, `output.max_duration_s = 15`, ranking off, captions off, voice `none`, primary audio on. Hook text optional. No network calls. |
| Ranking | One scene per entry with `rank.include = true`, `ranking.enabled = true`, direction from the wizard, badge + label visible. Entry order = array order, so dragging a scene moves its segment, crop, label, audio switches and narration together, and the badge numbers update because they are derived. Optional intro/outro scenes use `rank.include = false`. |
| Story / Explainer | One scene per line (sentence-split script, or Reddit post: title line + body lines), `driver = narration`, primary = image / stock / text card / your footage, captions `narration_words`, music on with ducking. Reddit input adds a `reddit_card` on the first scene with usernames hidden. |
| Gameplay | Scenes with `layout = split` (divider 0.5) or `pip`; primary = your foreground clip / story card / text card; secondary = a gameplay-library segment picked at random without repeats, `when_short = loop` with a 0.25 s crossfade, `continue_from_previous = true` on later scenes so one stretch runs continuously, secondary audio off (or −24 dB). |

Mixing is free because a scene never depends on what preset made it. The mixed example is a Ranking document whose
#2 scene has narration and whose #1 scene uses the Gameplay layout:

| Scene (order) | Rank shown | Layout | Primary | Secondary | Audio |
|---|---|---|---|---|---|
| `scn_01JDXRANK3ROCKET` | #3 | full | rocket-jump segment, fill | — | primary on 0 dB, music off |
| `scn_01JDXRANK2LADDER` | #2 | full | ladder segment, blur_fill | — | narration on, primary −6 dB ducked, music on (ducked) |
| `scn_01JDXRANK1BOSS` | #1 | split 0.55, primary top | boss-wipe segment, fill, zoom 1.1 | parkour gameplay, loop | primary on, gameplay off, music off |

Changing #1's layout writes only `scenes[2].layout`. The Phase 0 check below confirmed that #3 and #2 serialise
byte-identically before and after switching #1 to PiP, and in Phase 1+ the render cache guarantees their Stage 1
segments are reused.

## 5. Editing operations (frontend `model/ops.ts`, mirrored by server-side validation)

Each operation is a pure function `(doc, args) → doc` and one undo step.

- Scenes: add, duplicate (new IDs for the scene, its segments, overlays and SFX; the duplicate's take is kept since
  the text is the same), delete, reorder, split at playhead (the segment is split in two: `in…t` and `t…out`, each
  scene keeps its own copy of crop/audio/overlay settings; narration stays with the first half unless you move it),
  enable/disable, rename.
- Layers: set visual, replace source keeping trim length, set reframe (crop drag, zoom), set playback, swap
  primary/secondary.
- Layout: set type, divider, PiP rectangle.
- Audio: toggle and gain per track per scene; music track; ducking; SFX add/move/delete.
- Captions: mode, manual cues, word edits, style.
- Narration: set text (marks the take stale), attach take (from a finished job), set voice override.
- Ranking: enable, direction, badge style, reveal mode.
- Project: title, output, audience, rights confirmation.

## 6. Versioning and migration

- `schema` is the constant `"shorts-studio.project"`; `schema_version` is an integer, `1` now.
- On open: if `schema_version < current`, run `migrate_v1_to_v2`, `migrate_v2_to_v3`, … in order (pure functions
  with fixture tests), save the original as `history/pre-migration-v1.json`, then validate.
- If `schema_version > current`, the project opens read-only with "This project was saved by a newer Shorts Studio".
- Unknown keys under `extensions` are preserved; unknown keys anywhere else are a validation error.

## 7. Phase 0 schema check (run on 2026-11-25)

Run with jsonschema 4.26 on Python 3.13:

- The schema passes the Draft 2020-12 metaschema check.
- All four example documents validate.
- Twelve invalid variants of the mixed example are rejected: split layout without split settings; country `BOTH`
  with a region; `US` with a Canadian region; segment layer without `segment_id`; unknown scene property; a stored
  rank list; malformed scene ID; divider 0.95; badge format without `{n}`; `schema_version` 2; cap over 180 s;
  fixed duration without seconds.
- Switching #1 to PiP leaves the document valid and #3/#2 byte-identical.
- Moving the first entry to the end keeps its segment and label together and the document stays valid.
