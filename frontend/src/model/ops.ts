// Pure edits on a project document. Each takes an immer draft (or a plain object) and mutates it in place;
// the editor store wraps every call so it becomes one undo step. Every scene keeps its own settings, so an edit to
// one scene never touches another.
import type { Project, Scene, Source } from "./types"
import { newId } from "./ids"

export const QUICK_SHORT_CAP_S = 15
export const QUICK_SHORT_DEFAULT_S = 13
export const QUICK_SHORT_MIN_HINT_S = 12

type Slot = "primary" | "secondary"
type Layer = NonNullable<Scene["layers"]["secondary"]>
type TextStyle = Project["captions"]["style"]["text"]

const round3 = (x: number) => Math.round(x * 1000) / 1000
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export const textStyle = (size = 84, stroke = 6, box: string | null = null, family = "Anton"): TextStyle =>
({
  font_family: family, font_size_px: size, color: "#FFFFFF", stroke_color: "#000000", stroke_px: stroke,
  box_color: box, uppercase: true
})

const reframe = () => ({ mode: "fill" as const, focus: { x: 0.5, y: 0.5 }, zoom: 1 })
const playback = () => ({ speed: 1, when_short: "freeze_last" as const, loop_crossfade_s: 0, continue_from_previous: false })
const mix = (enabled: boolean, gain = 0) => ({ enabled, gain_db: gain, duck_under_narration: false })

/** Keep a trim inside the source, at least one frame long, and under the cap. ``moved`` decides which
 *  handle gives way when the cap is hit. */
export function clampTrim(inS: number, outS: number, duration: number, fps: number, cap: number | null,
  moved: "in" | "out" | "both"): [number, number] {
  const minLen = 1 / fps
  let a = Math.max(0, Math.min(inS, duration - minLen))
  let b = Math.max(a + minLen, Math.min(outS, duration))
  if (cap !== null && b - a > cap) {
    if (moved === "in") b = a + cap
    else if (moved === "out") a = b - cap
    else b = a + cap
  }
  return [round3(a), round3(b)]
}

export function sceneById(doc: Project, id: string): Scene {
  const s = doc.scenes.find((x) => x.id === id)
  if (!s) throw new Error(`no scene ${id}`)
  return s
}

export function layerOf(scene: Scene, slot: Slot): Layer | null {
  return (slot === "primary" ? scene.layers.primary : scene.layers.secondary) as Layer | null
}

export function segmentOf(doc: Project, scene: Scene, slot: Slot = "primary") {
  const layer = layerOf(scene, slot)
  if (!layer || layer.type !== "segment" || !layer.segment_id) return null
  const seg = doc.segments[layer.segment_id]
  return seg ? { id: layer.segment_id as string, seg } : null
}

export const primarySegment = (doc: Project, scene: Scene) => segmentOf(doc, scene, "primary")

// ── trims and framing ──────────────────────────────────────────────────
export function setTrim(doc: Project, segmentId: string, inS: number, outS: number, moved: "in" | "out" | "both") {
  const seg = doc.segments[segmentId]
  const src = doc.sources[seg.source_id]
  const [a, b] = clampTrim(inS, outS, src.fingerprint.duration_s ?? 0, doc.output.fps,
    doc.output.max_duration_s ?? null, moved)
  seg.in_s = a
  seg.out_s = b
}

export function setReframe(doc: Project, sceneId: string, patch: Partial<{
  mode: "fill" | "fit" | "blur_fill";
  x: number; y: number; zoom: number
}>, slot: Slot = "primary") {
  const layer = layerOf(sceneById(doc, sceneId), slot)
  if (!layer) return
  const rf = layer.reframe
  if (patch.mode) rf.mode = patch.mode
  if (patch.x !== undefined) rf.focus.x = round3(clamp(patch.x, 0, 1))
  if (patch.y !== undefined) rf.focus.y = round3(clamp(patch.y, 0, 1))
  if (patch.zoom !== undefined) rf.zoom = round3(clamp(patch.zoom, 1, 4))
}

export function setPlayback(doc: Project, sceneId: string, slot: Slot, patch: Partial<{
  speed: number;
  when_short: "loop" | "freeze_last" | "slow_to_fit" | "black"; loop_crossfade_s: number; continue_from_previous: boolean
}>) {
  const layer = layerOf(sceneById(doc, sceneId), slot)
  if (!layer || !layer.playback) return
  const pb = layer.playback
  if (patch.speed !== undefined) pb.speed = clamp(patch.speed, 0.25, 4)
  if (patch.when_short) pb.when_short = patch.when_short
  if (patch.loop_crossfade_s !== undefined) pb.loop_crossfade_s = round3(clamp(patch.loop_crossfade_s, 0, 1))
  if (patch.continue_from_previous !== undefined) pb.continue_from_previous = patch.continue_from_previous
}

export const setSpeed = (doc: Project, sceneId: string, speed: number) => setPlayback(doc, sceneId, "primary", { speed })

export function setMotion(doc: Project, sceneId: string, slot: Slot, motion: "none" | "ken_burns_in" | "ken_burns_out") {
  const layer = layerOf(sceneById(doc, sceneId), slot)
  if (layer && layer.type === "image") layer.motion = motion
}

// ── layers ─────────────────────────────────────────────────────────────
export function setLayerToSegment(doc: Project, sceneId: string, slot: Slot, sourceId: string, inS: number, outS: number) {
  const scene = sceneById(doc, sceneId)
  const segId = newId("seg")
  doc.segments[segId] = {
    source_id: sourceId, in_s: round3(inS), out_s: round3(outS), label: "Selection",
    created_by: "manual", pick: null
  }
  const old = layerOf(scene, slot)
  const layer: Layer = {
    type: "segment", segment_id: segId, reframe: old?.reframe ?? reframe(),
    playback: old?.playback ?? playback()
  }
  setLayer(scene, slot, layer)
  pruneSegments(doc)
}

export function setLayerToImage(doc: Project, sceneId: string, slot: Slot, sourceId: string) {
  const scene = sceneById(doc, sceneId)
  setLayer(scene, slot, { type: "image", source_id: sourceId, motion: "none", reframe: reframe() })
  if (slot === "primary" && scene.duration.driver === "primary") scene.duration = { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  pruneSegments(doc)
}

export function setLayerToTextCard(doc: Project, sceneId: string, slot: Slot, text = "Your text here") {
  const scene = sceneById(doc, sceneId)
  setLayer(scene, slot, {
    type: "text_card", reframe: reframe(),
    text_card: { text, background: "#14213D", align: "center", style: textStyle(110, 0) }
  })
  if (slot === "primary" && scene.duration.driver === "primary") scene.duration = { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  pruneSegments(doc)
}

export function setLayerToColor(doc: Project, sceneId: string, slot: Slot, color = "#14213D") {
  const scene = sceneById(doc, sceneId)
  setLayer(scene, slot, { type: "color", color, reframe: reframe() })
  if (slot === "primary" && scene.duration.driver === "primary") scene.duration = { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  pruneSegments(doc)
}

export function setTextCard(doc: Project, sceneId: string, slot: Slot, patch: Partial<{ text: string; background: string }>) {
  const layer = layerOf(sceneById(doc, sceneId), slot)
  if (!layer || layer.type !== "text_card" || !layer.text_card) return
  if (patch.text !== undefined) layer.text_card.text = patch.text.slice(0, 500)
  if (patch.background) layer.text_card.background = patch.background
}

export function setColor(doc: Project, sceneId: string, slot: Slot, color: string) {
  const layer = layerOf(sceneById(doc, sceneId), slot)
  if (layer && layer.type === "color") layer.color = color
}

function setLayer(scene: Scene, slot: Slot, layer: Layer) {
  if (slot === "primary") scene.layers.primary = layer as Scene["layers"]["primary"]
  else scene.layers.secondary = layer as Scene["layers"]["secondary"]
}

export function removeSecondary(doc: Project, sceneId: string) {
  const scene = sceneById(doc, sceneId)
  scene.layers.secondary = null
  scene.layout = { type: "full", background_color: scene.layout.background_color }
  scene.audio.secondary.enabled = false
  pruneSegments(doc)
}

export function swapLayers(doc: Project, sceneId: string) {
  const scene = sceneById(doc, sceneId)
  const sec = scene.layers.secondary
  if (!sec) return
  const prim = scene.layers.primary
  scene.layers.primary = sec as Scene["layers"]["primary"]
  scene.layers.secondary = prim as Scene["layers"]["secondary"]
  const a = scene.audio.primary
  scene.audio.primary = scene.audio.secondary
  scene.audio.secondary = a
  if (scene.duration.driver === "primary" && scene.layers.primary.type !== "segment") {
    scene.duration = { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  }
}

/** Put a picked gameplay stretch under a scene: a second layer, split screen, its sound off. */
export function addGameplay(doc: Project, sceneId: string, pick: {
  source_id: string; source: Source; segment_id: string;
  segment: Project["segments"][string]
}, layout: "split" | "pip" | "full" = "split") {
  const scene = sceneById(doc, sceneId)
  doc.sources[pick.source_id] = pick.source
  doc.segments[pick.segment_id] = pick.segment
  const layer: Layer = {
    type: "segment", segment_id: pick.segment_id, reframe: reframe(),
    playback: { speed: 1, when_short: "loop", loop_crossfade_s: 0.25, continue_from_previous: true }
  }
  if (layout === "full") {
    // Gameplay becomes the main picture (a story over gameplay). A clip or image that was the main picture stays
    // as a picture-in-picture inset; a colour or text card is replaced. The scene keeps its current length.
    const secs = sceneFrames(doc, scene) / doc.output.fps
    const old = scene.layers.primary
    const oldAudio = scene.audio.primary
    scene.layers.primary = layer as Scene["layers"]["primary"]
    scene.audio.primary = mix(false, -24)
    if (scene.duration.driver === "primary") scene.duration = { driver: "fixed", fixed_s: round3(secs), tail_pad_s: 0 }
    if (old.type === "segment" || old.type === "image") {
      scene.layers.secondary = old as Scene["layers"]["secondary"]
      scene.audio.secondary = { ...oldAudio }
      setLayout(doc, sceneId, "pip")
      scene.layout.pip!.inset_layer = "secondary"
    } else if (!scene.layers.secondary) {
      scene.layout = { type: "full", background_color: scene.layout.background_color }
    }
  } else {
    scene.layers.secondary = layer as Scene["layers"]["secondary"]
    scene.audio.secondary = mix(false, -24)
    setLayout(doc, sceneId, layout)
  }
  pruneSegments(doc)
}

function pruneSegments(doc: Project) {
  const used = new Set<string>()
  for (const s of doc.scenes) for (const l of [s.layers.primary, s.layers.secondary]) if (l?.segment_id) used.add(l.segment_id)
  for (const id of Object.keys(doc.segments)) if (!used.has(id)) delete doc.segments[id]
}

// ── layout ─────────────────────────────────────────────────────────────
export function setLayout(doc: Project, sceneId: string, type: "full" | "split" | "pip" | "blur_fill") {
  const scene = sceneById(doc, sceneId)
  const bg = scene.layout.background_color
  if (type === "blur_fill") {
    scene.layout = { type: "full", background_color: bg }
    scene.layers.primary.reframe.mode = "blur_fill"
  } else if (type === "full") {
    scene.layout = { type: "full", background_color: bg }
  } else if (type === "split") {
    const prev = scene.layout.split
    scene.layout = {
      type: "split", background_color: bg,
      split: prev ?? { divider: 0.5, primary_position: "top", gap_px: 0, gap_color: "#000000" }
    }
  } else {
    const prev = scene.layout.pip
    scene.layout = {
      type: "pip", background_color: bg,
      pip: prev ?? {
        inset_layer: "primary", x: 0.5, y: 0.12, width: 0.86, aspect: "16:9", corner_radius_px: 28,
        border_px: 4, border_color: "#FFFFFF"
      }
    }
  }
}

export function setSplit(doc: Project, sceneId: string, patch: Partial<{
  divider: number; primary_position: "top" | "bottom";
  gap_px: number; gap_color: string
}>) {
  const sp = sceneById(doc, sceneId).layout.split
  if (!sp) return
  if (patch.divider !== undefined) sp.divider = round3(clamp(patch.divider, 0.2, 0.8))
  if (patch.primary_position) sp.primary_position = patch.primary_position
  if (patch.gap_px !== undefined) sp.gap_px = Math.round(clamp(patch.gap_px, 0, 60))
  if (patch.gap_color) sp.gap_color = patch.gap_color
}

export function setPip(doc: Project, sceneId: string, patch: Partial<NonNullable<Scene["layout"]["pip"]>>) {
  const p = sceneById(doc, sceneId).layout.pip
  if (!p) return
  if (patch.x !== undefined) p.x = round3(clamp(patch.x, 0, 1))
  if (patch.y !== undefined) p.y = round3(clamp(patch.y, 0, 1))
  if (patch.width !== undefined) p.width = round3(clamp(patch.width, 0.15, 0.9))
  if (patch.inset_layer) p.inset_layer = patch.inset_layer
  if (patch.aspect) p.aspect = patch.aspect
  if (patch.corner_radius_px !== undefined) p.corner_radius_px = Math.round(clamp(patch.corner_radius_px, 0, 80))
  if (patch.border_px !== undefined) p.border_px = Math.round(clamp(patch.border_px, 0, 20))
}

// ── sound ──────────────────────────────────────────────────────────────
export function setMix(doc: Project, sceneId: string, track: "primary" | "secondary" | "narration",
  patch: { enabled?: boolean; gain_db?: number; duck_under_narration?: boolean }) {
  const a = sceneById(doc, sceneId).audio[track]
  if (patch.enabled !== undefined) a.enabled = patch.enabled
  if (patch.gain_db !== undefined) a.gain_db = Math.round(clamp(patch.gain_db, -60, 12) * 10) / 10
  if (patch.duck_under_narration !== undefined) a.duck_under_narration = patch.duck_under_narration
}

export const setPrimaryAudio = (doc: Project, sceneId: string, patch: { enabled?: boolean; gain_db?: number }) =>
  setMix(doc, sceneId, "primary", patch)

export function setSceneMusic(doc: Project, sceneId: string, enabled: boolean) {
  sceneById(doc, sceneId).audio.music.enabled = enabled
}

export function muteScene(doc: Project, sceneId: string) {
  const a = sceneById(doc, sceneId).audio
  a.primary.enabled = a.secondary.enabled = a.narration.enabled = false
  a.music.enabled = false
}

export function setMusic(doc: Project, sourceId: string | null) {
  if (!sourceId) { doc.audio.music = null; return }
  doc.audio.music = {
    source_id: sourceId, enabled: true, gain_db: -16, start_offset_s: 0, fade_in_s: 0.5,
    fade_out_s: 1, loop: true
  }
  for (const s of doc.scenes) if (s.narration) s.audio.music.enabled = true
}

export function setMusicFields(doc: Project, patch: Partial<NonNullable<Project["audio"]["music"]>>) {
  const m = doc.audio.music
  if (!m) return
  if (patch.enabled !== undefined) m.enabled = patch.enabled
  if (patch.gain_db !== undefined) m.gain_db = Math.round(clamp(patch.gain_db, -60, 12) * 10) / 10
  if (patch.start_offset_s !== undefined) m.start_offset_s = round3(Math.max(0, patch.start_offset_s))
  if (patch.loop !== undefined) m.loop = patch.loop
}

export function setDucking(doc: Project, patch: Partial<Project["audio"]["ducking"]>) {
  const d = doc.audio.ducking
  if (patch.enabled !== undefined) d.enabled = patch.enabled
  if (patch.depth_db !== undefined) d.depth_db = Math.round(clamp(patch.depth_db, -30, 0))
}

export const SOUNDS = ["whoosh", "pop", "hit", "ding", "boing", "record_scratch"] as const

export function addSfx(doc: Project, sceneId: string, at: number, sound: (typeof SOUNDS)[number] = "pop") {
  sceneById(doc, sceneId).sfx.push({ id: newId("sfx"), at_s: round3(Math.max(0, at)), sound, gain_db: -10 })
}

export function setSfx(doc: Project, sceneId: string, sfxId: string, patch: Partial<{ at_s: number; sound: string; gain_db: number }>) {
  const cue = sceneById(doc, sceneId).sfx.find((s) => s.id === sfxId)
  if (!cue) return
  if (patch.at_s !== undefined) cue.at_s = round3(Math.max(0, patch.at_s))
  if (patch.sound) cue.sound = patch.sound
  if (patch.gain_db !== undefined) cue.gain_db = Math.round(clamp(patch.gain_db, -60, 12))
}

export function removeSfx(doc: Project, sceneId: string, sfxId: string) {
  const s = sceneById(doc, sceneId)
  s.sfx = s.sfx.filter((x) => x.id !== sfxId)
}

// ── narration ──────────────────────────────────────────────────────────
export function setNarrationText(doc: Project, sceneId: string, text: string) {
  const scene = sceneById(doc, sceneId)
  if (!scene.narration) {
    scene.narration = { text: "", voice: null, offset_s: 0, take: null }
    scene.audio.narration.enabled = true
  }
  scene.narration.text = text.slice(0, 600)       // the take turns stale on its own (its hash no longer matches)
}

export function removeNarration(doc: Project, sceneId: string) {
  const scene = sceneById(doc, sceneId)
  scene.narration = null
  scene.audio.narration.enabled = false
  if (scene.duration.driver === "narration") {
    scene.duration = scene.layers.primary.type === "segment" ? { driver: "primary", fixed_s: null, tail_pad_s: 0 }
      : { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  }
}

export function attachTake(doc: Project, sceneId: string, take: NonNullable<NonNullable<Scene["narration"]>["take"]>) {
  const scene = doc.scenes.find((s) => s.id === sceneId)
  if (!scene || !scene.narration) return
  scene.narration.take = take
  scene.captions.word_edits = []
}

export function setNarrationOffset(doc: Project, sceneId: string, offset: number) {
  const n = sceneById(doc, sceneId).narration
  if (n) n.offset_s = round3(clamp(offset, 0, 10))
}

/** How long an opening voice can run: the whole opening clip, within what the length cap leaves after the other
 *  scenes. Mirrors intro.room_for_voice in Python. */
export function openingVoiceRoom(doc: Project, sceneId: string): number {
  const scene = sceneById(doc, sceneId)
  const seg = primarySegment(doc, scene)
  if (!seg) return sceneFrames(doc, scene) / doc.output.fps
  let room = (seg.seg.out_s - seg.seg.in_s) / (scene.layers.primary.playback?.speed ?? 1)
  const cap = doc.output.max_duration_s
  if (cap) {
    const others = doc.scenes.filter((s) => s.enabled && s.id !== sceneId).reduce((n, s) => n + sceneFrames(doc, s), 0)
    room = Math.min(room, cap - others / doc.output.fps)
  }
  return Math.max(0.5, Math.round(room * 100) / 100)
}

/** Seconds the opening scene needs so a take of ``takeSeconds`` fits, or null when even the whole clip is too short. */
export function openingSceneSeconds(doc: Project, sceneId: string, takeSeconds: number): number | null {
  const current = sceneFrames(doc, sceneById(doc, sceneId)) / doc.output.fps
  const room = openingVoiceRoom(doc, sceneId)
  if (takeSeconds > room + 0.001) return null
  return round3(Math.min(room, Math.max(current, takeSeconds + 0.25)))
}

/** The opening voice line at 0:00. The opening scene grows when the line is longer than it (the clip keeps playing),
 *  so the AI is free to write the hook the video needs instead of one sized to the current trim. */
export function addOpeningVoice(doc: Project, sceneId: string, text: string, take: NonNullable<NonNullable<Scene["narration"]>["take"]>,
  openingSeconds: number, duck: boolean) {
  const scene = sceneById(doc, sceneId)
  const current = sceneFrames(doc, scene) / doc.output.fps
  if (scene.duration.driver === "narration" || (scene.duration.driver === "fixed" && openingSeconds > current + 1e-3)) {
    setDuration(doc, sceneId, "fixed", openingSeconds)
  }
  setNarrationText(doc, sceneId, text)
  scene.narration!.voice = { provider: "elevenlabs", voice_id: take.voice_id ?? "", rate_pct: take.rate_pct ?? 0, model_id: take.model_id }
  setNarrationOffset(doc, sceneId, 0)
  attachTake(doc, sceneId, take)
  scene.audio.narration.enabled = true
  scene.audio.primary.duck_under_narration = duck
}

export function setDuration(doc: Project, sceneId: string, driver: "primary" | "narration" | "fixed", fixed?: number) {
  const scene = sceneById(doc, sceneId)
  if (driver === "fixed") scene.duration = { driver, fixed_s: round3(clamp(fixed ?? scene.duration.fixed_s ?? 3, 0.2, 180)), tail_pad_s: 0 }
  else scene.duration = { driver, fixed_s: null, tail_pad_s: driver === "narration" ? 0.25 : 0 }
}

export function setVoice(doc: Project, patch: Partial<Project["voice"]>) {
  if (patch.provider) doc.voice.provider = patch.provider
  if (patch.voice_id !== undefined) doc.voice.voice_id = patch.voice_id
  if (patch.rate_pct !== undefined) doc.voice.rate_pct = Math.round(clamp(patch.rate_pct, -50, 100))
  if (doc.voice.provider !== "elevenlabs") delete doc.voice.model_id
  else if (patch.model_id !== undefined) doc.voice.model_id = patch.model_id
}

/** The name the API serves a take's audio under: /api/takes/<key>.wav */
export function takeFileName(audioPath: string): string {
  return audioPath.split("/").pop() ?? ""
}

// ── captions ───────────────────────────────────────────────────────────
export function setCaptionMode(doc: Project, sceneId: string, mode: Scene["captions"]["mode"]) {
  sceneById(doc, sceneId).captions.mode = mode
}

export function setWordEdit(doc: Project, sceneId: string, index: number, text: string) {
  const c = sceneById(doc, sceneId).captions
  c.word_edits = c.word_edits.filter((w) => w.index !== index)
  if (text.trim()) c.word_edits.push({ index, text: text.trim().slice(0, 60) })
}

export function addCue(doc: Project, sceneId: string, start: number, end: number, text = "Caption") {
  sceneById(doc, sceneId).captions.manual_cues.push({ start_s: round3(start), end_s: round3(Math.max(end, start + 0.2)), text })
}

export function setCue(doc: Project, sceneId: string, index: number, patch: Partial<{ start_s: number; end_s: number; text: string }>) {
  const cue = sceneById(doc, sceneId).captions.manual_cues[index]
  if (!cue) return
  if (patch.start_s !== undefined) cue.start_s = round3(Math.max(0, patch.start_s))
  if (patch.end_s !== undefined) cue.end_s = round3(Math.max(cue.start_s + 0.05, patch.end_s))
  if (patch.text !== undefined) cue.text = patch.text.slice(0, 200)
}

export function removeCue(doc: Project, sceneId: string, index: number) {
  sceneById(doc, sceneId).captions.manual_cues.splice(index, 1)
}

export function setCaptions(doc: Project, patch: Partial<{
  enabled: boolean; default_mode: Project["captions"]["default_mode"];
  anchor_y: number; preset: Project["captions"]["style"]["preset"]; size: number; uppercase: boolean; max_words: number
}>) {
  const c = doc.captions
  if (patch.enabled !== undefined) c.enabled = patch.enabled
  if (patch.default_mode) c.default_mode = patch.default_mode
  if (patch.anchor_y !== undefined) c.anchor_y = round3(clamp(patch.anchor_y, 0, 1))
  if (patch.preset) {
    c.style.preset = patch.preset
    c.style.active_color = patch.preset === "minimal" ? null : (c.style.active_color ?? "#FFE11A")
    c.style.text.box_color = patch.preset === "boxed" ? "#7C3AED" : null
  }
  if (patch.size !== undefined) c.style.text.font_size_px = Math.round(clamp(patch.size, 32, 160))
  if (patch.uppercase !== undefined) c.style.text.uppercase = patch.uppercase
  if (patch.max_words !== undefined) c.style.max_words = Math.round(clamp(patch.max_words, 1, 8))
}

// ── overlays and ranking ───────────────────────────────────────────────
export function setRanking(doc: Project, patch: Partial<{
  enabled: boolean; direction: "descending" | "ascending";
  position: "top_left" | "top_center" | "top_right"; reveal: "current_only" | "list_build_up"; format: string
}>) {
  const r = doc.ranking
  if (patch.enabled !== undefined) {
    r.enabled = patch.enabled
    if (patch.enabled) for (const s of doc.scenes) { s.rank.include = true; s.overlays.rank_badge.visible = true }
  }
  if (patch.direction) r.direction = patch.direction
  if (patch.position) r.badge.position = patch.position
  if (patch.reveal) r.reveal = patch.reveal
  if (patch.format && patch.format.includes("{n}")) r.badge.format = patch.format.slice(0, 16)
}

export function setRankInclude(doc: Project, sceneId: string, include: boolean) {
  const s = sceneById(doc, sceneId)
  s.rank.include = include
  s.overlays.rank_badge.visible = include
}

export function setLabel(doc: Project, sceneId: string, patch: { visible?: boolean; text?: string | null }) {
  const l = sceneById(doc, sceneId).overlays.label
  if (patch.visible !== undefined) l.visible = patch.visible
  if (patch.text !== undefined) l.text = patch.text === null || patch.text.trim() === "" ? null : patch.text.slice(0, 80)
}

export function setRedditCard(doc: Project, sceneId: string, patch: Partial<NonNullable<Scene["overlays"]["reddit_card"]>> | null) {
  const scene = sceneById(doc, sceneId)
  if (patch === null) { scene.overlays.reddit_card = null; return }
  const cur = scene.overlays.reddit_card ?? {
    community: "r/stories", title: scene.narration?.text?.slice(0, 300) ?? "Title",
    author: { mode: "hidden" as const, name: null }, source_url: null, show_metrics: false,
    metrics: { upvotes: null, comments: null }, start_s: 0, end_s: null
  }
  scene.overlays.reddit_card = {
    ...cur, ...patch, author: { ...cur.author, ...(patch.author ?? {}) },
    metrics: { ...cur.metrics, ...(patch.metrics ?? {}) }
  }
}

export function addText(doc: Project, sceneId: string, text = "Text") {
  sceneById(doc, sceneId).overlays.texts.push({
    id: newId("ovl"), text, start_s: 0, end_s: null,
    anchor: { x: 0.5, y: 0.2 }, style: textStyle(72, 6, "#000000B3")
  })
}

export function setText(doc: Project, sceneId: string, id: string, patch: Partial<{
  text: string; start_s: number;
  end_s: number | null; x: number; y: number
}>) {
  const t = sceneById(doc, sceneId).overlays.texts.find((x) => x.id === id)
  if (!t) return
  if (patch.text !== undefined) t.text = patch.text.slice(0, 200)
  if (patch.start_s !== undefined) t.start_s = round3(Math.max(0, patch.start_s))
  if (patch.end_s !== undefined) t.end_s = patch.end_s === null ? null : round3(Math.max(t.start_s + 0.1, patch.end_s))
  if (patch.x !== undefined) t.anchor.x = round3(clamp(patch.x, 0, 1))
  if (patch.y !== undefined) t.anchor.y = round3(clamp(patch.y, 0, 1))
}

export function removeText(doc: Project, sceneId: string, id: string) {
  const o = sceneById(doc, sceneId).overlays
  o.texts = o.texts.filter((t) => t.id !== id)
}

export function setTitleBar(doc: Project, text: string | null) {
  if (text === null || !text.trim()) { doc.overlays.title_bar = null; return }
  doc.overlays.title_bar = doc.overlays.title_bar
    ? { ...doc.overlays.title_bar, text: text.slice(0, 80) }
    : { text: text.slice(0, 80), position: "top", background: "#000000B3", style: textStyle(60, 0) }
}

export function setHook(doc: Project, text: string | null, duration?: number) {
  if (text === null || !text.trim()) { doc.overlays.hook = null; return }
  const cur = doc.overlays.hook
  doc.overlays.hook = {
    text: text.slice(0, 80), start_s: cur?.start_s ?? 0, duration_s: duration ?? cur?.duration_s ?? 2.5,
    anchor_y: cur?.anchor_y ?? 0.12, style: cur?.style ?? textStyle(88, 6, "#000000B3")
  }
}

export function setWatermark(doc: Project, text: string | null, opacity?: number) {
  if (text === null || !text.trim()) { doc.overlays.watermark = null; return }
  doc.overlays.watermark = {
    text: text.slice(0, 40),
    opacity: round3(clamp(opacity ?? doc.overlays.watermark?.opacity ?? 0.6, 0.1, 1)),
  }
}

// ── scenes ─────────────────────────────────────────────────────────────
export function renameScene(doc: Project, sceneId: string, name: string) {
  sceneById(doc, sceneId).name = name.slice(0, 80)
}

export function setTitle(doc: Project, title: string) {
  doc.title = (title.trim() || "Untitled short").slice(0, 120)
}

export function setCap(doc: Project, cap: number | null) {
  doc.output.max_duration_s = cap
}

export function setAudienceCountry(doc: Project, country: "US" | "CA" | "BOTH") {
  const ca = country === "CA"
  doc.audience.country = country
  doc.audience.region = null
  doc.audience.language = ca ? "en-CA" : "en-US"
  doc.audience.spelling = ca ? "en-CA" : "en-US"
  doc.audience.units = ca ? "metric" : country === "BOTH" ? "both" : "imperial"
}

export function confirmRights(doc: Project, confirmed: boolean, at: string) {
  doc.compliance.rights.confirmed = confirmed
  doc.compliance.rights.confirmed_at = confirmed ? at : null
}

export function moveScene(doc: Project, sceneId: string, delta: number) {
  const i = doc.scenes.findIndex((s) => s.id === sceneId)
  moveSceneTo(doc, sceneId, i + delta)
}

/** Drag and drop: the whole scene moves, so its clip, trim, label, narration and sound settings go with it. */
export function moveSceneTo(doc: Project, sceneId: string, index: number) {
  const i = doc.scenes.findIndex((s) => s.id === sceneId)
  const j = clamp(index, 0, doc.scenes.length - 1)
  if (i < 0 || i === j) return
  const [scene] = doc.scenes.splice(i, 1)
  doc.scenes.splice(j, 0, scene)
}

export function toggleScene(doc: Project, sceneId: string) {
  const s = sceneById(doc, sceneId)
  s.enabled = !s.enabled
}

export function deleteScene(doc: Project, sceneId: string) {
  doc.scenes = doc.scenes.filter((s) => s.id !== sceneId)
  pruneSegments(doc)
}

/** A copy with new ids, including its own copies of its trims, so editing one never changes the other. */
export function duplicateScene(doc: Project, sceneId: string): string {
  const i = doc.scenes.findIndex((s) => s.id === sceneId)
  const copy: Scene = JSON.parse(JSON.stringify(doc.scenes[i]))
  copy.id = newId("scn")
  copy.name = `${copy.name} (copy)`.slice(0, 80)
  for (const slot of ["primary", "secondary"] as const) {
    const layer = layerOf(copy, slot)
    if (layer && layer.type === "segment" && layer.segment_id) {
      const segId = newId("seg")
      doc.segments[segId] = JSON.parse(JSON.stringify(doc.segments[layer.segment_id]))
      layer.segment_id = segId
    }
  }
  copy.sfx = copy.sfx.map((s) => ({ ...s, id: newId("sfx") }))
  copy.overlays.texts = copy.overlays.texts.map((t) => ({ ...t, id: newId("ovl") }))
  doc.scenes.splice(i + 1, 0, copy)
  return copy.id
}

/** Split a clip scene at scene-local time ``t``: two scenes, each with its own trim and its own copy of every
 *  setting. Narration stays with the first part. Returns the new scene's id, or null if it can't be split. */
export function splitScene(doc: Project, sceneId: string, t: number): string | null {
  const scene = sceneById(doc, sceneId)
  const p = primarySegment(doc, scene)
  if (!p || scene.duration.driver !== "primary") return null
  const speed = scene.layers.primary.playback?.speed ?? 1
  const cut = round3(p.seg.in_s + t * speed)
  const minLen = 1 / doc.output.fps
  if (cut - p.seg.in_s < minLen || p.seg.out_s - cut < minLen) return null
  const newId_ = duplicateScene(doc, sceneId)
  const second = sceneById(doc, newId_)
  second.name = `${scene.name} (2)`.slice(0, 80)
  doc.segments[p.id].out_s = cut
  const p2 = primarySegment(doc, second)!
  doc.segments[p2.id].in_s = cut
  second.narration = null
  second.audio.narration.enabled = false
  second.captions.manual_cues = scene.captions.manual_cues.filter((c) => c.start_s >= t)
    .map((c) => ({ ...c, start_s: round3(c.start_s - t), end_s: round3(c.end_s - t) }))
  scene.captions.manual_cues = scene.captions.manual_cues.filter((c) => c.start_s < t)
    .map((c) => ({ ...c, end_s: Math.min(c.end_s, round3(t)) }))
  second.sfx = second.sfx.filter((s) => s.at_s >= t).map((s) => ({ ...s, at_s: round3(s.at_s - t) }))
  scene.sfx = scene.sfx.filter((s) => s.at_s < t)
  return newId_
}

/** A new scene using ``sourceId`` from ``inS`` to ``outS``; mirrors defaults.scene_from_segment in Python. */
export function addSceneFromSource(doc: Project, sourceId: string, inS: number, outS: number, name?: string): string {
  const src = doc.sources[sourceId]
  const segId = newId("seg")
  doc.segments[segId] = {
    source_id: sourceId, in_s: round3(inS), out_s: round3(outS), label: "Selection",
    created_by: "manual", pick: null
  }
  const ranked = doc.ranking.enabled
  const scene: Scene = {
    id: newId("scn"),
    name: (name ?? src.display_name.replace(/\.[^.]+$/, "")).slice(0, 80),
    enabled: true,
    duration: { driver: "primary", fixed_s: null, tail_pad_s: 0 },
    layout: { type: "full", background_color: "#000000" },
    layers: { primary: { type: "segment", segment_id: segId, reframe: reframe(), playback: playback() }, secondary: null },
    narration: null,
    audio: {
      primary: mix(Boolean(src.fingerprint.has_audio)), secondary: mix(false, -20), narration: mix(false),
      music: { enabled: false }
    },
    captions: { mode: "inherit", manual_cues: [], word_edits: [] },
    overlays: { rank_badge: { visible: ranked }, label: { visible: ranked, text: null }, reddit_card: null, texts: [] },
    rank: { include: ranked },
    transition_in: { type: "cut", duration_s: 0 },
    sfx: [],
  }
  doc.scenes.push(scene)
  return scene.id
}

/** A new narrated scene over a coloured background (for stories and explainers). */
export function addNarratedScene(doc: Project, text: string, afterId?: string): string {
  const scene: Scene = {
    id: newId("scn"), name: text.slice(0, 40) || "New line", enabled: true,
    duration: { driver: "narration", fixed_s: null, tail_pad_s: 0.25 },
    layout: { type: "full", background_color: "#000000" },
    layers: { primary: { type: "color", color: "#14213D", reframe: reframe() }, secondary: null },
    narration: { text: text.slice(0, 600), voice: null, offset_s: 0, take: null },
    audio: { primary: mix(false), secondary: mix(false, -24), narration: mix(true), music: { enabled: true } },
    captions: { mode: "inherit", manual_cues: [], word_edits: [] },
    overlays: { rank_badge: { visible: doc.ranking.enabled }, label: { visible: false, text: null }, reddit_card: null, texts: [] },
    rank: { include: doc.ranking.enabled },
    transition_in: { type: "cut", duration_s: 0 },
    sfx: [],
  }
  const i = afterId ? doc.scenes.findIndex((s) => s.id === afterId) : -1
  if (i >= 0) doc.scenes.splice(i + 1, 0, scene)
  else doc.scenes.push(scene)
  return scene.id
}

/** A new 3 s text card scene (an intro, an outro or a chapter title). */
export function addCardScene(doc: Project, text: string, afterId?: string): string {
  const id = addNarratedScene(doc, text, afterId)
  const scene = sceneById(doc, id)
  scene.narration = null
  scene.audio.narration.enabled = false
  scene.duration = { driver: "fixed", fixed_s: 3, tail_pad_s: 0 }
  setLayerToTextCard(doc, id, "primary", text)
  scene.rank.include = false
  scene.overlays.rank_badge.visible = false
  return id
}

export function addSources(doc: Project, sources: Record<string, Source>) {
  for (const [id, s] of Object.entries(sources)) doc.sources[id] = s
}

export function relinkSource(doc: Project, sourceId: string, path: string, fingerprint: Source["fingerprint"]) {
  const s = doc.sources[sourceId]
  s.path = path
  s.fingerprint = fingerprint
  const dur = fingerprint.duration_s ?? 0
  for (const seg of Object.values(doc.segments)) {
    if (seg.source_id !== sourceId || !dur) continue
    seg.out_s = round3(Math.min(seg.out_s, dur))
    seg.in_s = round3(Math.min(seg.in_s, Math.max(0, seg.out_s - 1 / doc.output.fps)))
  }
}

/** Scene durations as the resolver computes them (whole frames), for instant UI feedback. */
export function sceneFrames(doc: Project, scene: Scene): number {
  const fps = doc.output.fps
  const p = primarySegment(doc, scene)
  const speed = scene.layers.primary.playback?.speed ?? 1
  const d = scene.duration
  if (d.driver === "fixed" && d.fixed_s) return Math.max(1, Math.floor(d.fixed_s * fps + 0.5))
  if (d.driver === "narration" && scene.narration) {
    const take = scene.narration.take
    const secs = take ? scene.narration.offset_s + take.duration_s + d.tail_pad_s
      : scene.narration.offset_s + Math.max(1, scene.narration.text.split(/\s+/).filter(Boolean).length / 2.7) + d.tail_pad_s
    return Math.max(1, Math.floor(secs * fps + 0.5))
  }
  if (p) return Math.max(1, Math.floor(((p.seg.out_s - p.seg.in_s) / speed) * fps + 0.5))
  return Math.floor(3 * fps + 0.5)
}

export function totalSeconds(doc: Project): number {
  return doc.scenes.filter((s) => s.enabled).reduce((n, s) => n + sceneFrames(doc, s), 0) / doc.output.fps
}

/** Displayed rank numbers, derived from order (never stored); mirrors resolve.ranks in Python. */
export function ranks(doc: Project): Record<string, number> {
  if (!doc.ranking.enabled) return {}
  const entries = doc.scenes.filter((s) => s.enabled && s.rank.include).map((s) => s.id)
  const n = entries.length
  return Object.fromEntries(entries.map((id, i) => [id, doc.ranking.direction === "descending" ? n - i : i + 1]))
}
