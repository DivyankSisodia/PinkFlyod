# 05 — UI sitemap

```
/                               Home: "What do you want to make?"
├── [Edit an existing video]    → /new/edit
├── [Create from scratch]       → /new/create
├── Start from a preset         Quick Short · Ranking · Story/Explainer · Gameplay   (both paths accept a preset)
└── Recent projects             thumbnail, title, length, last edited, "missing media" badge, open / duplicate / delete

/new/edit                       Import
├── Choose files…               native dialog (reference in place) · or drop files (copied into the app)
├── Paste a video URL           Phase 3 · yt-dlp · marks the source "someone else's" → rights box before export
├── Ownership for this batch    My recording · Licensed · Someone else's
├── Preset                      Quick Short (default for one file) · Ranking (default for several files) · Blank
└── → opens the editor with the Trim bench on the first source

/new/create                     Start from an idea
├── Topic                       one line → optional AI draft (Phase 3) → editable scenes
├── Paste a script or story     sentence split into scenes · Reddit mode: source link, title, strip usernames
├── Blank                       one empty scene
├── Preset                      Story/Explainer (default) · Ranking · Gameplay · Quick Short
├── Script Doctor               optional retention rewrite pass, shown as a diff you accept or reject (Phase 3)
└── → opens the editor

/p/:projectId                   Editor (same for both entry paths)
├── Top bar                     title · Saved/Saving… · undo/redo · audience chip (US/CA/Both + region)
│                               · warnings (missing media, safe area, reused content) · Export
├── Left panel (tabs)
│   ├── Media                   sources with origin/ownership, missing → Relink / Search a folder, + Add media
│   ├── Selections              segments not yet on the timeline (from the Trim bench or suggested highlights)
│   ├── Gameplay                library picker: tags, preview, "Random stretch" (non-repeating)
│   ├── Text & cards            text card, Reddit card, hook, title bar presets
│   └── Stock                   Pexels / Pixabay search with attribution (Phase 3, needs a key)
├── Centre: Player              9:16 canvas preview · safe-area guide · play/scrub · J/K/L · exact-frame check
│                               · preview range (renders 2–5 s through the export pipeline) · loop-join markers
├── Bottom: Timeline
│   ├── Scene strip             cards in order with rank badge, name, duration; drag to reorder; right-click:
│   │                           split at playhead, duplicate, disable, delete
│   └── Lanes                   Primary · Secondary · Narration · Source audio · Music · Captions · SFX
│                               (mute toggles per lane per scene; drag SFX; caption cue handles)
├── Right: Inspector (for the selection)
│   ├── Scene                   name, duration driver (clip / narration / fixed), transition, rank include
│   ├── Layout                  Full · Split (divider slider, top/bottom) · Picture-in-picture (drag inset) · Blurred fill
│   ├── Layer                   source + trim (opens Trim bench), reframe (fill/fit/blur, drag focus, zoom,
│   │                           keyframes), speed, when shorter: loop / freeze / slow / black, loop crossfade
│   ├── Audio                   per track: on/off, gain, duck under narration · music track, ducking depth
│   ├── Narration               line text, take state (none / ready / stale / generating), Generate · Record ·
│   │                           Import · voice override, play take
│   ├── Captions                mode, cue editor, word fixes, style (project-wide)
│   ├── Overlays                rank badge, label, Reddit card fields (username hidden / anonymised / shown,
│   │                           source link, metrics only if you type them), text overlays
│   └── Project                 output (1080×1920, 30 fps, CRF), loudness target, when silent, length cap,
│                               safe-area insets, audience, rights confirmation
├── Trim bench (overlay)        source player · filmstrip · in/out handles with first/last frame · I/O keys ·
│                               exact timecode entry · length readout with the 15 s Quick Short cap ·
│                               "Add selection" / "Add to timeline" · transcript lane + suggested highlights (Phase 3)
└── Export dialog               pre-flight checks (rights box, missing media, length cap, safe area,
                                reused-content note) → Render · live progress (WebSocket) · Cancel ·
                                Open MP4 · Show in folder · render history with ffprobe summary

/library/gameplay               upload / tag / delete clips · preview · usage history per clip · sample clips
                                (generated, royalty-free) with a reminder to use your own or licensed footage
/discover                       Phase 3 · trends per source with source, collected-at time and true granularity
                                · editorial suggestions in a separate, differently styled list
/settings
├── General                     data folder (read-only path, "Open folder"), port, autosave interval
├── Audience defaults           country, region, spelling, units
├── Voices                      Edge TTS (online), OS voice (offline), OpenAI-compatible TTS (key), default per audience
├── AI                          OpenAI-compatible base URL / model / key, Ollama preset, test connection
├── Stock                       Pexels key, Pixabay key
├── Transcription               model size, download / remove model, CPU threads
├── Render                      encoder (libx264 default; hardware encoders optional), preset, parallel scenes
└── About                       version, licenses, third-party notices
/jobs (drawer, any page)        running and recent jobs with progress, cancel, open result
```

## Editor wireframe

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Top 3 funniest gaming fails   Saved ✓   ↶ ↷   🇺🇸🇨🇦 Both   ⚠ 1   [ Export ]                     │
├──────────────┬──────────────────────────────────────────┬───────────────────────────────────┤
│ Media        │              ┌──────────┐                │ Scene: Tutorial boss wipe  (#1)     │
│ Selections   │              │ TITLE BAR│                │ Layout: ( ) Full (•) Split ( ) PiP  │
│ Gameplay     │              │ #1       │                │         ( ) Blurred fill            │
│ Text & cards │              │  clip    │                │ Divider ────●──── 55 %              │
│ Stock        │              │──────────│ ← divider      │ Primary: boss-wipe.mp4 3.2–9.0 s    │
│              │              │ gameplay │                │   Fill · focus ⊕ · zoom 1.1         │
│  rocket…mp4  │              │ CAPTIONS │                │ Secondary: parkour-run-01 (loop)    │
│  ladder…mp4  │              │          │                │ Audio: clip ● on  gameplay ○ off    │
│  boss-…mp4   │              └──────────┘                │        narration —  music ○ off     │
│              │      ▶ 00:09.4 / 00:14.2   [exact frame]  │                                     │
├──────────────┴──────────────────────────────────────────┴───────────────────────────────────┤
│ [#3 Rocket jump 4.7s] [#2 Ladder betrayal 3.7s] [#1 Tutorial boss wipe 5.8s]   + scene        │
│ Primary    ▇▇▇▇▇▇▇▇▇▇▇▇ ▇▇▇▇▇▇▇▇▇▇ ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇                                             │
│ Secondary                          ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ ↻                                          │
│ Narration              ▂▃▅▃▂▂▅▃▂                                                              │
│ Music      ░░░░░░░░░░░ ░░░▁▁▁▁░░ ░░░░░░░░░░░░░░░░  (off on #3/#1, ducked on #2)                │
│ Captions               [HE TRUSTED][THE LADDER]                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Quick Short path (fewest steps, fully offline)

Home → **Edit an existing video** → Choose file → (Quick Short is preselected for one file) → Trim bench opens with a
13 s selection at the playhead, capped at 15 s → Add to timeline → drag the crop focus in the player → optional hook
text / captions / mute → **Export** → progress → **Open MP4**. Nothing in this path calls the network.
