// Pure time maths for the preview, mirroring render/plan.py: which source second a layer shows at a scene-local
// time (including loop copies), and the gain a sound has at a moment (gain, duck envelope, edge fades).
import type { Envelope, ResolvedAudio, ResolvedLayer, ResolvedMusic, ResolvedScene, Timeline } from "../model/types"

export const dbToGain = (db: number) => Math.pow(10, db / 20)

/** Same as timeline/envelope.py evaluate(). */
export function evalEnvelope(points: Envelope | null | undefined, t: number): number {
  if (!points || !points.length) return 1
  if (t <= points[0][0]) return points[0][1]
  const last = points[points.length - 1]
  if (t >= last[0]) return last[1]
  let i = 1
  while (i < points.length && points[i][0] <= t) i++
  const [t0, g0] = points[i - 1]
  const [t1, g1] = points[i]
  return t1 <= t0 ? g0 : g0 + ((g1 - g0) * (t - t0)) / (t1 - t0)
}

export function sceneAt(tl: Timeline, t: number): ResolvedScene | null {
  if (!tl.scenes.length) return null
  const f = Math.min(tl.frames - 1, Math.max(0, Math.floor(t * tl.output.fps + 1e-6)))
  return tl.scenes.find((s) => s.start_frame <= f && f < s.start_frame + s.frames) ?? tl.scenes[tl.scenes.length - 1]
}

export interface LayerTime {
  /** Source second to show. */
  mediaT: number
  /** Past the end of the selection (frozen, black, or silent). */
  inTail: boolean
  /** Nothing to draw (when_short = black, in the tail). */
  hidden: boolean
  /** Which loop copy is showing (0 when not looping). */
  copy: number
}

/** The source time a clip layer shows at scene-local time ``local``. */
export function layerTime(layer: ResolvedLayer, local: number, fps: number): LayerTime {
  const speed = layer.speed ?? 1
  const s = Math.max(0, local * speed)
  const loop = layer.loop
  if (loop && loop.copies.length) {
    // Copy k starts where copy k-1 ends minus the crossfade (the export overlaps them by that much).
    let start = 0
    let k = 0
    for (let j = 1; j < loop.copies.length; j++) {
      const next = start + loop.copies[j - 1].len_s - loop.crossfade_s
      if (s < next) break
      start = next
      k = j
    }
    const c = loop.copies[k]
    return { mediaT: c.in_s + Math.min(s - start, Math.max(0, c.len_s - 1 / fps)), inTail: false, hidden: false, copy: k }
  }
  const read = layer.read_s ?? 0
  const inTail = s >= read - 1e-3
  const mediaT = (layer.source_in_s ?? 0) + Math.min(s, Math.max(0, read - 1 / fps))
  return { mediaT, inTail, hidden: inTail && layer.when_short === "black", copy: 0 }
}

/** Gain (linear) of a scene's own sound event at scene-local ``local``; 0 when it isn't sounding. */
export function eventGain(ev: ResolvedAudio, local: number, sceneDur: number): number {
  const rel = local - ev.start_s
  const end = Math.min(sceneDur - ev.start_s, ev.read_s / (ev.speed || 1))
  if (rel < 0 || rel >= end) return 0
  let g = dbToGain(ev.gain_db) * evalEnvelope(ev.duck, local)
  const f = ev.fade_s
  if (f > 0) g *= Math.min(1, rel / f, (end - rel) / f)
  return Math.max(0, g)
}

/** Music gain at timeline time ``t``: level, the per-scene gate and ducking envelope, and its fades. */
export function musicGain(m: ResolvedMusic, t: number, total: number): number {
  let g = dbToGain(m.gain_db) * evalEnvelope(m.envelope, t)
  if (m.fade_in_s > 0) g *= Math.min(1, t / m.fade_in_s)
  if (m.fade_out_s > 0) g *= Math.min(1, Math.max(0, (total - t) / m.fade_out_s))
  return Math.max(0, g)
}

/** Where in the music file timeline time ``t`` falls, or null once a non-looping track has run out. */
export function musicOffset(m: ResolvedMusic, t: number): number | null {
  const pos = m.start_offset_s + t
  const d = m.duration_s ?? 0
  if (!d) return null
  if (m.loop) return pos % d
  return pos < d ? pos : null
}

/** Ken Burns: the crop window shrinks (zoom in) or grows (zoom out) about its centre over the scene. */
export function kenBurnsScale(layer: ResolvedLayer, local: number, dur: number): number {
  if (layer.motion === "none" || !layer.motion_zoom) return 1
  const p = Math.min(1, Math.max(0, local / Math.max(dur, 1e-6)))
  const z = layer.motion_zoom
  return layer.motion === "ken_burns_in" ? 1 + (z - 1) * p : z - (z - 1) * p
}
