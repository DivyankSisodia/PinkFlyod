import { describe, expect, it } from "vitest"
import type { ResolvedAudio, ResolvedLayer, ResolvedMusic } from "../model/types"
import { evalEnvelope, eventGain, kenBurnsScale, layerTime, musicGain, musicOffset } from "./timing"

const base: ResolvedLayer = {
  slot: "secondary", kind: "segment", rect: { x: 0, y: 960, w: 1080, h: 960 }, mode: "fill", bar_color: "#000000",
  source_id: "src_x", color: null, raster: null, motion: "none", pip: null, source_size: { w: 1920, h: 1080 },
  source_in_s: 10, read_s: 4, speed: 1, pad_s: 0, when_short: "freeze_last", loop: null,
}

describe("layerTime", () => {
  it("plays the selection, then freezes on its last frame", () => {
    expect(layerTime(base, 1.5, 30)).toMatchObject({ mediaT: 11.5, inTail: false, hidden: false })
    const tail = layerTime(base, 6, 30)
    expect(tail.inTail).toBe(true)
    expect(tail.mediaT).toBeCloseTo(10 + 4 - 1 / 30, 9)
  })
  it("hides the layer in the tail when the scene asks for black", () => {
    expect(layerTime({ ...base, when_short: "black" }, 6, 30).hidden).toBe(true)
  })
  it("maps loop copies the way the export concatenates them (each overlaps the last by the crossfade)", () => {
    // Same numbers as the resolver for a 3.75 s stretch in a 10 s scene with a 0.25 s crossfade:
    // copies start at 0, 3.5, 7.0 in the scene and joins land at 3.5 and 7.0.
    const looped: ResolvedLayer = {
      ...base, read_s: 10, when_short: "loop",
      loop: { copies: [{ in_s: 10, len_s: 3.75 }, { in_s: 10, len_s: 3.75 }, { in_s: 10, len_s: 3.75 }],
        crossfade_s: 0.25, joins: [3.5, 7] },
    }
    expect(layerTime(looped, 1, 30)).toMatchObject({ copy: 0, mediaT: 11 })
    expect(layerTime(looped, 3.6, 30).copy).toBe(1)
    expect(layerTime(looped, 3.6, 30).mediaT).toBeCloseTo(10.1, 9)
    expect(layerTime(looped, 7.25, 30).copy).toBe(2)
    expect(layerTime(looped, 7.25, 30).mediaT).toBeCloseTo(10.25, 9)
  })
  it("speed scales source time", () => {
    expect(layerTime({ ...base, speed: 2, read_s: 8 }, 1.5, 30).mediaT).toBe(13)
  })
})

describe("gains", () => {
  it("evaluates envelopes like timeline/envelope.py", () => {
    const env: [number, number][] = [[0, 1], [1, 1], [1.2, 0.25], [2, 0.25], [2.4, 1]]
    expect(evalEnvelope(env, -1)).toBe(1)
    expect(evalEnvelope(env, 1.1)).toBeCloseTo(0.625, 9)
    expect(evalEnvelope(env, 1.5)).toBe(0.25)
    expect(evalEnvelope(env, 9)).toBe(1)
    expect(evalEnvelope(null, 3)).toBe(1)
  })
  it("a clip's sound has its gain, duck and edge fades, and is silent after it runs out", () => {
    const ev: ResolvedAudio = {
      track: "primary", source_id: "src_x", start_s: 0, source_in_s: 10, read_s: 4, speed: 1, gain_db: -6,
      duck: [[0, 1], [2, 1], [2.1, 0.5], [4, 0.5]], copies: null, fade_s: 0.05,
    }
    expect(eventGain(ev, 1, 6)).toBeCloseTo(Math.pow(10, -6 / 20), 9)
    expect(eventGain(ev, 3, 6)).toBeCloseTo(Math.pow(10, -6 / 20) * 0.5, 9)
    expect(eventGain(ev, 0.025, 6)).toBeCloseTo(Math.pow(10, -6 / 20) * 0.5, 9)
    expect(eventGain(ev, 4.5, 6)).toBe(0)
  })
  it("music follows its envelope and fades, and loops from its offset", () => {
    const m: ResolvedMusic = {
      source_id: "src_m", gain_db: -20, start_offset_s: 2, loop: true, fade_in_s: 0.5, fade_out_s: 1,
      duration_s: 8, envelope: [[0, 1], [5, 1], [5.25, 0], [10, 0]],
    }
    expect(musicGain(m, 0.25, 10)).toBeCloseTo(0.1 * 0.5, 9)
    expect(musicGain(m, 2, 10)).toBeCloseTo(0.1, 9)
    expect(musicGain(m, 6, 10)).toBe(0)
    expect(musicOffset(m, 7)).toBe(1)
    expect(musicOffset({ ...m, loop: false }, 7)).toBeNull()
  })
  it("Ken Burns zoom runs across the scene", () => {
    const img = { ...base, kind: "image" as const, motion: "ken_burns_in" as const, motion_zoom: 1.15 }
    expect(kenBurnsScale(img, 0, 4)).toBe(1)
    expect(kenBurnsScale(img, 4, 4)).toBeCloseTo(1.15, 9)
    expect(kenBurnsScale({ ...img, motion: "ken_burns_out" }, 0, 4)).toBeCloseTo(1.15, 9)
  })
})
