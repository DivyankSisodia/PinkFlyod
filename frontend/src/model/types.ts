// The project document types come from the JSON Schema (project.gen.ts).
// The timeline is the resolver's output (backend/shorts_studio/timeline/resolve.py), an API response shape.
export type { Project, Scene, Source, Segment, Visual, Reframe, Fingerprint, Take, Voice } from "./project.gen"

export interface Rect { x: number; y: number; w: number; h: number }

/** [[t, gain], ...] with t ascending; linear between points (timeline/envelope.py). */
export type Envelope = [number, number][]

export interface LoopCopy { in_s: number; len_s: number }

export interface ResolvedPip {
  inset_layer: "primary" | "secondary"
  radius: number
  border_px: number
  border_color: string
  mask: string | null
  border: string | null
}

export interface ResolvedLayer {
  slot: "primary" | "secondary"
  kind: "segment" | "image" | "color" | "text_card"
  /** The slot this layer fills, in output pixels. */
  rect: Rect
  mode: "fill" | "fit" | "blur_fill"
  bar_color: string
  source_id: string | null
  segment_id?: string
  color: string | null
  raster: string | null
  motion: "none" | "ken_burns_in" | "ken_burns_out"
  motion_zoom?: number
  pip: ResolvedPip | null
  source_size?: { w: number; h: number }
  source_in_s?: number
  offset_s?: number
  segment_len_s?: number
  read_s?: number
  speed?: number
  pad_s?: number
  when_short?: "freeze_last" | "black" | "slow_to_fit" | "loop"
  loop?: { copies: LoopCopy[]; crossfade_s: number; joins: number[] } | null
  /** Crop window in source pixels. */
  src?: Rect
  /** Where the crop lands, relative to ``rect``. */
  dst?: Rect
  blur_background?: { src: Rect; dst: Rect } | null
}

export interface ResolvedAudio {
  track: "primary" | "secondary" | "narration"
  source_id?: string
  path?: string
  start_s: number
  source_in_s: number
  read_s: number
  speed: number
  gain_db: number
  duck: Envelope | null
  copies: LoopCopy[] | null
  crossfade_s?: number
  fade_s: number
}

export interface ResolvedOverlay {
  kind: "badge" | "rank_list" | "reddit_card" | "text" | "caption" | "title_bar" | "hook" | "watermark"
  raster: string
  start_s: number
  end_s: number
}

export interface ResolvedNarration {
  take_id: string
  audio_path: string
  start_s: number
  duration_s: number
  state: "ready" | "stale"
  words: [string, number, number][]
}

export interface ResolvedScene {
  id: string
  index: number
  name: string
  rank: number | null
  start_frame: number
  frames: number
  start_s: number
  duration_s: number
  background_color: string
  layout: {
    type: "full" | "split" | "pip"
    slots: Partial<Record<"primary" | "secondary", Rect>>
    gap: (Rect & { color: string }) | null
    pip: ResolvedPip | null
  }
  layers: ResolvedLayer[]
  overlays: ResolvedOverlay[]
  audio: ResolvedAudio[]
  narration: ResolvedNarration | null
  sfx: { sound: string; at_s: number; gain_db: number }[]
  music_on: boolean
  edge_fade_s: number
}

export interface ResolvedMusic {
  source_id: string
  gain_db: number
  start_offset_s: number
  loop: boolean
  fade_in_s: number
  fade_out_s: number
  duration_s: number | null
  envelope: Envelope
}

export interface Issue {
  code: string
  message: string
  severity: "error" | "warning"
  path: string
  scene_id: string | null
}

export interface Timeline {
  resolver_version: number
  output: { width: number; height: number; fps: number }
  frames: number
  duration_s: number
  safe_area: Rect
  audible: boolean
  scenes: ResolvedScene[]
  overlays: ResolvedOverlay[]
  music: ResolvedMusic | null
  blank_raster: string
  sources: Record<string, {
    kind: string; display_name: string; w: number | null; h: number | null;
    duration_s: number | null; has_audio: boolean; status: string
  }>
  needs_rights: boolean
  issues: Issue[]
}

export interface ProjectSummary {
  id: string
  title: string
  updated_at: string
  revision: number
  preset: string | null
  scene_count: number
  poster_source_id: string | null
  missing: number | null
}

export interface VerifyReport {
  ok: boolean
  failed: string[]
  checks: { name: string; ok: boolean; expected: unknown; actual: unknown; severity: string }[]
  summary: {
    size_bytes: number; duration_s: number; width?: number; height?: number; fps?: number; frames?: number
    audio_streams: number; audio_codec?: string; loudness?: { integrated_lufs?: number; true_peak_dbfs?: number }
  }
  render_seconds?: number
  cache_hits?: number
}

export interface RenderRecord {
  id: string
  project_id: string
  revision: number
  path: string
  created_at: string
  verify: VerifyReport
  warnings: Issue[]
  exists: boolean
}

export interface Job {
  id: string
  kind: string
  project_id: string | null
  status: "queued" | "running" | "done" | "failed" | "cancelled"
  pct: number
  stage: string
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface Checkpoint { pct: number; stage: string; created_at: string }

export interface GameplayClip {
  id: string
  path: string
  display_name: string
  tags: string[]
  fingerprint: import("./project.gen").Fingerprint
  sample: boolean
  downloaded: boolean
  uses: number
  exists: boolean
  created_at: string
}

export interface VoiceOption { id: string; name: string; locale: string; gender: string }
