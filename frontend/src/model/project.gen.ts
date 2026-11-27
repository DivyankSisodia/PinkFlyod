/* Generated from schema/project.v1.schema.json by `npm run gen:types`. Do not edit. */

/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "projectId".
 */
export type ProjectId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "timestamp".
 */
export type Timestamp = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "audience".
 */
export type Audience = ({
[k: string]: unknown
} & {
country: ("US" | "CA" | "BOTH")
/**
 * Optional ISO 3166-2 state, province or territory.
 */
region: (null | "US-AL" | "US-AK" | "US-AZ" | "US-AR" | "US-CA" | "US-CO" | "US-CT" | "US-DE" | "US-FL" | "US-GA" | "US-HI" | "US-ID" | "US-IL" | "US-IN" | "US-IA" | "US-KS" | "US-KY" | "US-LA" | "US-ME" | "US-MD" | "US-MA" | "US-MI" | "US-MN" | "US-MS" | "US-MO" | "US-MT" | "US-NE" | "US-NV" | "US-NH" | "US-NJ" | "US-NM" | "US-NY" | "US-NC" | "US-ND" | "US-OH" | "US-OK" | "US-OR" | "US-PA" | "US-RI" | "US-SC" | "US-SD" | "US-TN" | "US-TX" | "US-UT" | "US-VT" | "US-VA" | "US-WA" | "US-WV" | "US-WI" | "US-WY" | "US-DC" | "US-PR" | "US-GU" | "US-VI" | "US-AS" | "US-MP" | "CA-AB" | "CA-BC" | "CA-MB" | "CA-NB" | "CA-NL" | "CA-NS" | "CA-ON" | "CA-PE" | "CA-QC" | "CA-SK" | "CA-NT" | "CA-NU" | "CA-YT")
language: ("en-US" | "en-CA")
spelling: ("en-US" | "en-CA")
units: ("imperial" | "metric" | "both")
localization_log?: {
at: Timestamp
from_region: (string | null)
to_region: (string | null)
hunks_accepted: number
hunks_rejected: number
}[]
})
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "gameplayClipId".
 */
export type GameplayClipId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sha256".
 */
export type Sha256 = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sourceId".
 */
export type SourceId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "seconds".
 */
export type Seconds = number
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sceneId".
 */
export type SceneId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sceneDuration".
 */
export type SceneDuration = ({
[k: string]: unknown
} & {
/**
 * primary = the primary segment's length; narration = the take's length plus tail_pad_s; fixed = fixed_s.
 */
driver: ("primary" | "narration" | "fixed")
fixed_s: (number | null)
tail_pad_s: number
})
/**
 * Where the scene's layers sit. The UI's 'Blurred fill' choice is type full with the primary layer's reframe.mode = blur_fill.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "layout".
 */
export type Layout = ({
[k: string]: unknown
} & {
type: ("full" | "split" | "pip")
background_color: Color
split?: {
/**
 * Fraction of the frame height above the divider.
 */
divider: number
primary_position: ("top" | "bottom")
gap_px: number
gap_color: Color
}
pip?: {
inset_layer: ("primary" | "secondary")
x: Unit
y: Unit
width: number
aspect: ("source" | "9:16" | "1:1" | "4:3" | "16:9")
corner_radius_px: number
border_px: number
border_color: Color
}
})
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "color".
 */
export type Color = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "unit".
 */
export type Unit = number
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "visual".
 */
export type Visual = ({
[k: string]: unknown
} & {
type: ("segment" | "image" | "text_card" | "color")
segment_id?: SegmentId
source_id?: SourceId
text_card?: {
text: string
background: Color
style: TextStyle
align: ("left" | "center")
}
color?: Color
reframe: Reframe
playback?: Playback
motion?: ("none" | "ken_burns_in" | "ken_burns_out" | "pan_left" | "pan_right")
})
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "segmentId".
 */
export type SegmentId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "takeId".
 */
export type TakeId = string
/**
 * [text, start_s, end_s], relative to the start of the take.
 * 
 * @minItems 3
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "word".
 */
export type Word = never[]
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "gainDb".
 */
export type GainDb = number
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "overlayId".
 */
export type OverlayId = string
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sfxId".
 */
export type SfxId = string

/**
 * One document describes one vertical video. Timeline positions are never stored: the resolver derives them from scene order and scene durations. Displayed ranks, take staleness and safe-area pixel rectangles are also derived, never stored. See docs/phase-0/04-project-schema.md for the semantic rules JSON Schema cannot express.
 */
export interface Project {
schema: "shorts-studio.project"
schema_version: 1
app_version?: string
id: ProjectId
title: string
created_at: Timestamp
updated_at: Timestamp
/**
 * Incremented by the server on every accepted save. Saves must name the revision they were based on.
 */
revision: number
origin: Origin
output: Output
audience: Audience
compliance: Compliance
voice: Voice
/**
 * Media files the project uses, keyed by source id.
 */
sources: {
[k: string]: Source
}
/**
 * In/out selections on a source, keyed by segment id. A segment has no timeline position.
 */
segments: {
[k: string]: Segment
}
/**
 * Timeline order. Reordering moves whole scene objects, so everything a scene owns moves with it.
 * 
 * @maxItems 100
 */
scenes: Scene[]
ranking: Ranking
audio: ProjectAudio
captions: CaptionSettings
overlays: ProjectOverlays
publish_meta?: PublishMeta
/**
 * Reserved for later integrations (publishing, scheduling, analytics). Unknown keys are kept on load and save.
 */
extensions?: {

}
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "origin".
 */
export interface Origin {
entry: ("edit_existing" | "create_from_scratch")
/**
 * The starting preset. Informational only: it never changes how the document renders.
 */
preset: ("quick_short" | "ranking" | "story" | "gameplay" | "blank")
input: ("files" | "url" | "topic" | "script" | "reddit_post" | "blank")
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "output".
 */
export interface Output {
width: number
height: number
fps: (24 | 25 | 30 | 50 | 60)
video: {
codec: "h264"
encoder: ("libx264" | "h264_nvenc" | "h264_qsv" | "h264_amf" | "h264_videotoolbox")
crf: number
preset: ("ultrafast" | "superfast" | "veryfast" | "faster" | "fast" | "medium" | "slow")
}
audio: {
codec: "aac"
bitrate_kbps: (128 | 160 | 192 | 256 | 320)
sample_rate: (44100 | 48000)
loudness: {
enabled: boolean
target_lufs: number
true_peak_dbtp: number
lra: number
}
}
/**
 * What the MP4 contains when every audio track is off.
 */
when_silent: ("omit_audio_stream" | "silent_aac")
/**
 * Hard cap on the rendered length. The Quick Short preset sets 15.
 */
max_duration_s: (number | null)
safe_area: SafeArea
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "safeArea".
 */
export interface SafeArea {
profile: ("youtube_shorts" | "custom")
/**
 * Insets are measured on this frame and scaled to the output size.
 * 
 * @minItems 2
 */
reference_px: never[]
insets_px: {
top: number
bottom: number
left: number
right: number
}
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "compliance".
 */
export interface Compliance {
/**
 * Required before rendering when any used source is url_download or ownership third_party/unknown.
 */
rights: {
confirmed: boolean
confirmed_at: (null | Timestamp)
statement_version: number
}
reused_content_warning: {
dismissed_at: (null | Timestamp)
}
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "voice".
 */
export interface Voice {
provider: ("edge" | "system" | "elevenlabs" | "openai_compatible" | "none")
model_id?: string
voice_id: string
rate_pct: number
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "source".
 */
export interface Source {
kind: ("video" | "image" | "audio")
origin: ("local_file" | "url_download" | "stock" | "ai_image" | "gameplay_library" | "generated" | "recording")
ownership: ("own" | "licensed" | "third_party" | "unknown")
/**
 * Absolute path, or a 'data:' path inside the app data folder.
 */
path: string
display_name: string
/**
 * Where a downloaded, stock or AI source came from.
 */
url?: (string | null)
attribution?: (null | Attribution)
gameplay_clip_id?: (null | GameplayClipId)
transcript?: (null | {
path: string
model: string
language: string
created_at: Timestamp
})
fingerprint: Fingerprint
imported_at: Timestamp
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "attribution".
 */
export interface Attribution {
provider: string
author: (string | null)
license: string
page_url: (string | null)
}
/**
 * Used to detect moved or replaced files and to check a relink target.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "fingerprint".
 */
export interface Fingerprint {
size_bytes: number
/**
 * Seconds since the Unix epoch.
 */
mtime: number
/**
 * SHA-256 of the first and last 1 MiB.
 */
sample_sha256: Sha256
duration_s: (number | null)
width: (number | null)
height: (number | null)
fps: (number | null)
rotation: (0 | 90 | 180 | 270)
has_audio: boolean
video_codec?: (string | null)
audio_codec?: (string | null)
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "segment".
 */
export interface Segment {
source_id: SourceId
in_s: Seconds
out_s: Seconds
label: string
created_by: ("manual" | "highlight_suggestion" | "gameplay_pick" | "whole_source")
pick: (null | {
strategy: "random_nonrepeating"
seed: number
picked_at: Timestamp
})
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "scene".
 */
export interface Scene {
id: SceneId
name: string
/**
 * false = skipped at render, kept in the project.
 */
enabled: boolean
duration: SceneDuration
layout: Layout
layers: {
primary: Visual
secondary: (null | Visual)
}
narration: (null | Narration)
audio: SceneAudio
captions: SceneCaptions
overlays: SceneOverlays
rank: {
/**
 * false for intro/outro scenes in a ranking.
 */
include: boolean
}
transition_in: {
type: ("cut" | "crossfade" | "fade_through_black")
duration_s: number
}
/**
 * @maxItems 40
 */
sfx: SfxCue[]
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "textStyle".
 */
export interface TextStyle {
font_family: string
font_size_px: number
color: Color
stroke_color: Color
stroke_px: number
box_color: (null | Color)
uppercase: boolean
}
/**
 * How a source fills its slot. fill = cover-crop; fit = whole picture with bars; blur_fill = whole picture over a blurred copy of itself.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "reframe".
 */
export interface Reframe {
mode: ("fill" | "fit" | "blur_fill")
/**
 * Centre of the crop window in normalised source coordinates.
 */
focus: {
x: Unit
y: Unit
}
/**
 * 1 = the smallest window that covers the slot.
 */
zoom: number
bar_color?: Color
/**
 * Optional moving crop. Times are relative to the segment's in point.
 */
keyframes?: {
at_s: Seconds
x: Unit
y: Unit
zoom: number
}[]
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "playback".
 */
export interface Playback {
speed: number
/**
 * What happens when the scene lasts longer than the segment.
 */
when_short: ("loop" | "freeze_last" | "slow_to_fit" | "black")
loop_crossfade_s: number
/**
 * Start where the previous scene's use of the same source ended, so one gameplay stretch runs continuously across scenes.
 */
continue_from_previous: boolean
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "narration".
 */
export interface Narration {
text: string
/**
 * null = the project voice.
 */
voice: (null | Voice)
offset_s: number
take: (null | Take)
}
/**
 * A take is stale when text_sha256 no longer matches the narration text, or its voice no longer matches the scene's effective voice. Staleness is derived, never stored.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "take".
 */
export interface Take {
id: TakeId
method: ("tts" | "recorded" | "imported")
provider: (string | null)
model_id?: string
voice_id: (string | null)
rate_pct: (number | null)
text_sha256: Sha256
audio_path: string
duration_s: number
words: Word[]
timing: ("native" | "aligned" | "estimated")
created_at: Timestamp
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sceneAudio".
 */
export interface SceneAudio {
primary: MixToggle
secondary: MixToggle1
narration: MixToggle2
music: {
enabled: boolean
}
}
/**
 * The primary layer's own sound.
 */
export interface MixToggle {
enabled: boolean
gain_db: GainDb
duck_under_narration: boolean
}
/**
 * The secondary layer's own sound (for example gameplay).
 */
export interface MixToggle1 {
enabled: boolean
gain_db: GainDb
duck_under_narration: boolean
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "mixToggle".
 */
export interface MixToggle2 {
enabled: boolean
gain_db: GainDb
duck_under_narration: boolean
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sceneCaptions".
 */
export interface SceneCaptions {
mode: ("inherit" | "off" | "narration_words" | "source_transcript" | "manual")
/**
 * Scene-relative times.
 */
manual_cues: Cue[]
/**
 * Display-only corrections to timed words (for example a misheard transcript word).
 */
word_edits: {
index: number
text: string
}[]
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "cue".
 */
export interface Cue {
start_s: Seconds
end_s: Seconds
text: string
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sceneOverlays".
 */
export interface SceneOverlays {
rank_badge: {
visible: boolean
}
label: {
visible: boolean
/**
 * null = the scene name.
 */
text: (string | null)
}
reddit_card: (null | RedditCard)
/**
 * @maxItems 20
 */
texts: TextOverlay[]
}
/**
 * Vote and comment counts appear only when the user typed them in; the app never invents them.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "redditCard".
 */
export interface RedditCard {
community: string
title: string
author: {
mode: ("hidden" | "anonymized" | "shown")
name: (string | null)
}
source_url: (string | null)
show_metrics: boolean
metrics: {
upvotes: (number | null)
comments: (number | null)
}
start_s: Seconds
/**
 * null = until the narration finishes reading the title.
 */
end_s: (number | null)
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "textOverlay".
 */
export interface TextOverlay {
id: OverlayId
text: string
start_s: Seconds
/**
 * null = end of scene.
 */
end_s: (number | null)
/**
 * Position inside the safe area (0,0 = its top-left corner).
 */
anchor: {
x: Unit
y: Unit
}
style: TextStyle
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "sfxCue".
 */
export interface SfxCue {
id: SfxId
/**
 * Scene-relative, so the effect moves with its scene.
 */
at_s: number
sound: (("whoosh" | "pop" | "hit" | "ding" | "boing" | "record_scratch") | SourceId)
gain_db: GainDb
}
/**
 * Displayed rank numbers are derived from scene order, never stored.
 * 
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "ranking".
 */
export interface Ranking {
enabled: boolean
/**
 * descending = countdown (N first, 1 last); ascending = 1 first.
 */
direction: ("descending" | "ascending")
badge: {
format: string
position: ("top_left" | "top_center" | "top_right")
style: TextStyle
}
/**
 * current_only = one badge per entry; list_build_up = a numbered list that fills in as entries play.
 */
reveal: ("current_only" | "list_build_up")
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "projectAudio".
 */
export interface ProjectAudio {
music: (null | MusicTrack)
/**
 * Music (and any layer with duck_under_narration) dips while narration is speaking.
 */
ducking: {
enabled: boolean
depth_db: number
attack_ms: number
release_ms: number
}
/**
 * Short fade at every scene cut, so cuts don't click.
 */
edge_fade_ms: number
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "musicTrack".
 */
export interface MusicTrack {
source_id: SourceId
enabled: boolean
gain_db: GainDb
start_offset_s: Seconds
fade_in_s: number
fade_out_s: number
loop: boolean
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "captionSettings".
 */
export interface CaptionSettings {
enabled: boolean
default_mode: ("narration_words" | "source_transcript" | "off")
style: {
preset: ("bold" | "boxed" | "clean" | "karaoke" | "minimal")
text: TextStyle
active_color: (null | Color)
emphasis_color: (null | Color)
max_words: number
max_chars: number
}
/**
 * Vertical position inside the safe area (0 = its top, 1 = its bottom).
 */
anchor_y: number
/**
 * @maxItems 100
 */
emphasis_words: string[]
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "projectOverlays".
 */
export interface ProjectOverlays {
hook: (null | {
text: string
start_s: Seconds
duration_s: number
anchor_y: Unit
style: TextStyle
})
title_bar: (null | {
text: string
position: ("top" | "bottom")
background: (null | Color)
style: TextStyle
})
watermark: (null | {
text: string
opacity: Unit
})
}
/**
 * This interface was referenced by `Project`'s JSON-Schema
 * via the `definition` "publishMeta".
 */
export interface PublishMeta {
title_drafts?: {
text: string
/**
 * editorial = generated suggestion, shown apart from observed trend data.
 */
kind: ("user" | "editorial")
created_at: Timestamp
}[]
description?: string
/**
 * @maxItems 60
 */
tags?: string[]
source_links?: string[]
}
