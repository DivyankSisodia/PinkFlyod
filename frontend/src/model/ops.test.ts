import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import Ajv2020 from "ajv/dist/2020"
import addFormats from "ajv-formats"
import { produce } from "immer"
import { describe, expect, it } from "vitest"
import * as ops from "./ops"
import type { Project } from "./types"

const root = resolve(__dirname, "../../..")
const schema = JSON.parse(readFileSync(resolve(root, "schema/project.v1.schema.json"), "utf8"))
const ajv = new Ajv2020({ allErrors: true, strict: false })
addFormats(ajv)
const validate = ajv.compile(schema)
const example = (name: string): Project =>
  JSON.parse(readFileSync(resolve(root, `schema/examples/${name}.json`), "utf8"))

function expectValid(doc: Project) {
  const ok = validate(doc)
  expect(validate.errors ?? [], JSON.stringify(validate.errors?.slice(0, 3))).toEqual([])
  expect(ok).toBe(true)
}

describe("clampTrim", () => {
  it("keeps the trim inside the source and at least a frame long", () => {
    expect(ops.clampTrim(-3, 200, 95.3, 30, null, "both")).toEqual([0, 95.3])
    expect(ops.clampTrim(50, 49, 95.3, 30, null, "out")).toEqual([50, 50.033])
  })
  it("enforces the 15 s Quick Short cap on the handle being dragged", () => {
    expect(ops.clampTrim(10, 30, 95.3, 30, 15, "out")).toEqual([15, 30])
    expect(ops.clampTrim(10, 30, 95.3, 30, 15, "in")).toEqual([10, 25])
    expect(ops.clampTrim(10, 25, 95.3, 30, 15, "both")).toEqual([10, 25])
  })
})

describe("edits keep the document valid", () => {
  it("adds a scene from a source with the same defaults as the backend", () => {
    const doc = produce(example("quick-short-13s"), (d) => {
      ops.addSceneFromSource(d, "src_01JDXLANDSCAPE", 60, 62.5)
    })
    expectValid(doc)
    expect(doc.scenes).toHaveLength(2)
  })
  it("duplicates a scene with its own trim", () => {
    let newId = ""
    const doc = produce(example("quick-short-13s"), (d) => {
      newId = ops.duplicateScene(d, "scn_01JDXQUICKMAIN")
      const copy = ops.sceneById(d, newId)
      ops.setTrim(d, copy.layers.primary.segment_id as string, 0, 5, "both")
    })
    expectValid(doc)
    const orig = ops.primarySegment(doc, doc.scenes[0])!
    const dup = ops.primarySegment(doc, doc.scenes[1])!
    expect(orig.id).not.toEqual(dup.id)
    expect([orig.seg.in_s, orig.seg.out_s]).toEqual([41.5, 54.5])
    expect([dup.seg.in_s, dup.seg.out_s]).toEqual([0, 5])
  })
  it("reorders whole scenes, so media and label travel together", () => {
    const doc = produce(example("top3-gaming-fails"), (d) => ops.moveScene(d, "scn_01JDXRANK3ROCKET", 2))
    expectValid(doc)
    expect(doc.scenes.map((s) => s.id)).toEqual(["scn_01JDXRANK2LADDER", "scn_01JDXRANK1BOSS", "scn_01JDXRANK3ROCKET"])
    expect(doc.scenes[2].layers.primary.segment_id).toBe("seg_01JDXROCKETJUMP")
    expect(doc.scenes[2].name).toBe("Rocket jump")
  })
  it("changing one scene's crop leaves the others untouched", () => {
    const before = example("top3-gaming-fails")
    const after = produce(before, (d) => ops.setReframe(d, "scn_01JDXRANK1BOSS", { x: 0.9, mode: "fit" }))
    expect(after.scenes[0]).toBe(before.scenes[0])     // structural sharing: same object
    expect(after.scenes[1]).toBe(before.scenes[1])
    expect(after.scenes[2].layers.primary.reframe.focus.x).toBe(0.9)
  })
  it("deleting a scene drops its unused trim", () => {
    const doc = produce(example("top3-gaming-fails"), (d) => ops.deleteScene(d, "scn_01JDXRANK3ROCKET"))
    expectValid(doc)
    expect(doc.segments["seg_01JDXROCKETJUMP"]).toBeUndefined()
  })
  it("clamps focus, zoom, gain and speed", () => {
    const doc = produce(example("quick-short-13s"), (d) => {
      ops.setReframe(d, "scn_01JDXQUICKMAIN", { x: 1.7, y: -2, zoom: 9 })
      ops.setPrimaryAudio(d, "scn_01JDXQUICKMAIN", { gain_db: 40 })
      ops.setSpeed(d, "scn_01JDXQUICKMAIN", 10)
    })
    expectValid(doc)
    const s = doc.scenes[0]
    expect(s.layers.primary.reframe.focus).toEqual({ x: 1, y: 0 })
    expect(s.layers.primary.reframe.zoom).toBe(4)
    expect(s.audio.primary.gain_db).toBe(12)
    expect(s.layers.primary.playback?.speed).toBe(4)
  })
  it("relinking keeps trims inside a shorter file", () => {
    const doc = produce(example("quick-short-13s"), (d) => {
      const fp = { ...d.sources["src_01JDXLANDSCAPE"].fingerprint, duration_s: 50 }
      ops.relinkSource(d, "src_01JDXLANDSCAPE", "D:/new/hike.mp4", fp)
    })
    expectValid(doc)
    expect(doc.segments["seg_01JDXLOOKOUT13"].out_s).toBe(50)
  })
  it("audience and rights edits stay valid", () => {
    const doc = produce(example("quick-short-13s"), (d) => {
      ops.setAudienceCountry(d, "BOTH")
      ops.confirmRights(d, true, "2026-11-25T12:00:00Z")
      ops.setCap(d, null)
      ops.setTitle(d, "  ")
    })
    expectValid(doc)
    expect(doc.title).toBe("Untitled short")
    expect(doc.audience.region).toBeNull()
  })
})

describe("Phase 2 edits", () => {
  const fakePick = (d: Project) => {
    const src = JSON.parse(JSON.stringify(d.sources["src_01JDXLANDSCAPE"] ?? Object.values(d.sources)[0]))
    src.origin = "gameplay_library"
    src.display_name = "gameplay.mp4"
    return {
      source_id: "src_01JDXGAMEPLAYPICK", source: src, segment_id: "seg_01JDXGAMEPLAYPICK",
      segment: {
        source_id: "src_01JDXGAMEPLAYPICK", in_s: 10, out_s: 14, label: "Gameplay", created_by: "gameplay_pick" as const,
        pick: { strategy: "random_nonrepeating" as const, seed: 7, picked_at: "2026-11-25T12:00:00Z" }
      },
    }
  }

  it("dragging an entry renumbers ranks from the order; media, label and narration travel with it", () => {
    const before = example("top3-gaming-fails")
    expect(ops.ranks(before)).toEqual({ scn_01JDXRANK3ROCKET: 3, scn_01JDXRANK2LADDER: 2, scn_01JDXRANK1BOSS: 1 })
    const after = produce(before, (d) => ops.moveSceneTo(d, "scn_01JDXRANK1BOSS", 0))
    expectValid(after)
    expect(ops.ranks(after)).toEqual({ scn_01JDXRANK1BOSS: 3, scn_01JDXRANK3ROCKET: 2, scn_01JDXRANK2LADDER: 1 })
    const boss = ops.sceneById(after, "scn_01JDXRANK1BOSS")
    expect(boss).toBe(ops.sceneById(before, "scn_01JDXRANK1BOSS"))      // the scene object itself is untouched
    expect(ops.sceneById(after, "scn_01JDXRANK2LADDER").narration?.take?.id)
      .toBe(ops.sceneById(before, "scn_01JDXRANK2LADDER").narration?.take?.id)
  })
  it("ascending order counts up and excluded scenes get no number", () => {
    const doc = produce(example("top3-gaming-fails"), (d) => {
      ops.setRanking(d, { direction: "ascending" })
      ops.setRankInclude(d, "scn_01JDXRANK2LADDER", false)
    })
    expectValid(doc)
    expect(ops.ranks(doc)).toEqual({ scn_01JDXRANK3ROCKET: 1, scn_01JDXRANK1BOSS: 2 })
  })
  it("editing a line keeps its old take (it is stale by hash) and leaves other scenes alone", () => {
    const before = example("narrated-explainer")
    const after = produce(before, (d) => ops.setNarrationText(d, "scn_01JDXLINE2", "A different second line."))
    expectValid(after)
    const line2 = ops.sceneById(after, "scn_01JDXLINE2")
    expect(line2.narration?.text).toBe("A different second line.")
    expect(line2.narration?.take?.text_sha256).toBe(ops.sceneById(before, "scn_01JDXLINE2").narration?.take?.text_sha256)
    expect(ops.sceneById(after, "scn_01JDXLINE1")).toBe(ops.sceneById(before, "scn_01JDXLINE1"))
    expect(ops.sceneById(after, "scn_01JDXLINE3")).toBe(ops.sceneById(before, "scn_01JDXLINE3"))
  })
  it("attaching a new take changes only that scene's voice and downstream timing", () => {
    const before = example("narrated-explainer")
    const take = { ...ops.sceneById(before, "scn_01JDXLINE2").narration!.take!, id: "tk_newtake01", duration_s: 4.5 }
    const after = produce(before, (d) => ops.attachTake(d, "scn_01JDXLINE2", take))
    expectValid(after)
    expect(ops.sceneFrames(after, after.scenes[1])).toBe(Math.floor((4.5 + after.scenes[1].duration.tail_pad_s +
      after.scenes[1].narration!.offset_s) * 30 + 0.5))
    expect(after.scenes[0]).toBe(before.scenes[0])
    expect(after.scenes[2]).toBe(before.scenes[2])
  })
  it("gameplay goes under a scene as a muted, looping second layer in a split", () => {
    const doc = produce(example("quick-short-13s"), (d) => ops.addGameplay(d, "scn_01JDXQUICKMAIN", fakePick(d), "split"))
    expectValid(doc)
    const s = doc.scenes[0]
    expect(s.layout.type).toBe("split")
    expect(s.layers.secondary?.segment_id).toBe("seg_01JDXGAMEPLAYPICK")
    expect(s.layers.secondary?.playback?.when_short).toBe("loop")
    expect(s.audio.secondary.enabled).toBe(false)
    expect(doc.segments["seg_01JDXLOOKOUT13"]).toBeDefined()
  })
  it("full-screen gameplay keeps a clip as a picture-in-picture inset and the scene's length", () => {
    const before = example("quick-short-13s")
    const secs = ops.sceneFrames(before, before.scenes[0])
    const doc = produce(before, (d) => ops.addGameplay(d, "scn_01JDXQUICKMAIN", fakePick(d), "full"))
    expectValid(doc)
    const s = doc.scenes[0]
    expect(s.layers.primary.segment_id).toBe("seg_01JDXGAMEPLAYPICK")
    expect(s.layers.secondary?.segment_id).toBe("seg_01JDXLOOKOUT13")
    expect(s.layout.type).toBe("pip")
    expect(s.layout.pip?.inset_layer).toBe("secondary")
    expect(ops.sceneFrames(doc, s)).toBe(secs)
  })
  it("layout changes are local to one scene; divider and PiP settings are clamped", () => {
    const before = example("top3-gaming-fails")
    const after = produce(before, (d) => {
      ops.setSplit(d, "scn_01JDXRANK1BOSS", { divider: 0.95, primary_position: "bottom" })
      ops.setLayout(d, "scn_01JDXRANK1BOSS", "pip")
      ops.setPip(d, "scn_01JDXRANK1BOSS", { width: 2, x: -1, corner_radius_px: 500 })
    })
    expectValid(after)
    const boss = ops.sceneById(after, "scn_01JDXRANK1BOSS")
    expect(boss.layout.type).toBe("pip")
    expect(boss.layout.pip).toMatchObject({ width: 0.9, x: 0, corner_radius_px: 80 })
    expect(after.scenes[0]).toBe(before.scenes[0])
    expect(after.scenes[1]).toBe(before.scenes[1])
    const back = produce(after, (d) => ops.setLayout(d, "scn_01JDXRANK1BOSS", "split"))
    expect(ops.sceneById(back, "scn_01JDXRANK1BOSS").layout.split?.divider).toBe(0.5)   // pip replaced it; defaults again
  })
  it("splits a clip scene at the playhead into two scenes with their own trims", () => {
    let second: string | null = null
    const doc = produce(example("quick-short-13s"), (d) => { second = ops.splitScene(d, "scn_01JDXQUICKMAIN", 5) })
    expectValid(doc)
    expect(second).not.toBeNull()
    const a = ops.primarySegment(doc, doc.scenes[0])!
    const b = ops.primarySegment(doc, doc.scenes[1])!
    expect([a.seg.in_s, a.seg.out_s]).toEqual([41.5, 46.5])
    expect([b.seg.in_s, b.seg.out_s]).toEqual([46.5, 54.5])
    expect(ops.totalSeconds(doc)).toBeCloseTo(13, 6)
  })
  it("muting, sound effects, music, captions and overlays stay valid", () => {
    const doc = produce(example("top3-gaming-fails"), (d) => {
      ops.muteScene(d, "scn_01JDXRANK3ROCKET")
      ops.addSfx(d, "scn_01JDXRANK3ROCKET", 1.25, "whoosh")
      ops.setMusicFields(d, { gain_db: -80 })
      ops.setDucking(d, { depth_db: -50 })
      ops.setCaptions(d, { preset: "boxed", size: 400, anchor_y: 2 })
      ops.setCaptionMode(d, "scn_01JDXRANK3ROCKET", "manual")
      ops.addCue(d, "scn_01JDXRANK3ROCKET", 0.5, 0.6, "Watch this")
      ops.setRedditCard(d, "scn_01JDXRANK2LADDER", { community: "r/gaming", author: { mode: "anonymized", name: null } })
      ops.addText(d, "scn_01JDXRANK1BOSS", "Final boss")
      ops.setTitleBar(d, "Top 3 funniest gaming fails")
      ops.setHook(d, "Number 1 is unreal", 2)
      ops.setWatermark(d, "@mychannel")
      ops.setLabel(d, "scn_01JDXRANK1BOSS", { text: "  " })
    })
    expectValid(doc)
    const rocket = ops.sceneById(doc, "scn_01JDXRANK3ROCKET")
    expect(rocket.audio.primary.enabled || rocket.audio.narration.enabled || rocket.audio.music.enabled).toBe(false)
    expect(rocket.sfx[0]).toMatchObject({ at_s: 1.25, sound: "whoosh" })
    expect(rocket.captions.manual_cues[0].end_s).toBeCloseTo(0.7, 6)       // at least 0.2 s long
    expect(doc.audio.music?.gain_db).toBe(-60)
    expect(doc.audio.ducking.depth_db).toBe(-30)
    expect(doc.captions.style.text.font_size_px).toBe(160)
    expect(ops.sceneById(doc, "scn_01JDXRANK2LADDER").overlays.reddit_card?.metrics).toEqual({ upvotes: null, comments: null })
    expect(ops.sceneById(doc, "scn_01JDXRANK1BOSS").overlays.label.text).toBeNull()
  })
  it("adds narrated and text-card scenes after the selected one", () => {
    const doc = produce(example("narrated-explainer"), (d) => {
      ops.addNarratedScene(d, "A brand new line.", "scn_01JDXLINE1")
      ops.addCardScene(d, "The end", "scn_01JDXLINE3")
    })
    expectValid(doc)
    expect(doc.scenes[1].narration?.text).toBe("A brand new line.")
    expect(doc.scenes[1].narration?.take).toBeNull()
    expect(doc.scenes[4].layers.primary.type).toBe("text_card")
    expect(doc.scenes[4].narration).toBeNull()
  })
  it("swapping and removing a second layer keeps the document valid", () => {
    const doc = produce(example("top3-gaming-fails"), (d) => {
      ops.swapLayers(d, "scn_01JDXRANK1BOSS")
      ops.setReframe(d, "scn_01JDXRANK1BOSS", { x: 0.2 }, "secondary")
      ops.removeSecondary(d, "scn_01JDXRANK1BOSS")
    })
    expectValid(doc)
    const boss = ops.sceneById(doc, "scn_01JDXRANK1BOSS")
    expect(boss.layers.secondary).toBeNull()
    expect(boss.layout.type).toBe("full")
  })
})

describe("upload details", () => {
  it("saves title, description and tags with the project, newest title first, without duplicates", () => {
    const at = "2026-11-27T07:00:00Z"
    const doc = produce(example("quick-short-13s"), (d) => {
      ops.setPublishMeta(d, { title: "First idea #shorts", titleKind: "editorial", at })
      ops.setPublishMeta(d, {
        title: "My own title #shorts", titleKind: "user", description: "Line one.\n\n#shorts",
        tags: ["gta 6", " GTA 6 ", "", "surprise gift", "x".repeat(150)], at
      })
      ops.setPublishMeta(d, { title: "First idea #shorts", titleKind: "editorial", at })
    })
    expectValid(doc)
    const pm = doc.publish_meta!
    expect(pm.title_drafts!.map((t) => t.text)).toEqual(["First idea #shorts", "My own title #shorts"])
    expect(pm.tags).toEqual(["gta 6", "surprise gift", "x".repeat(100)])
    expect(pm.description).toBe("Line one.\n\n#shorts")
  })
})

describe("opening voice", () => {
  const take = (seconds: number) => ({
    ...example("narrated-explainer").scenes[0].narration!.take!, id: "tk_openinghook1", duration_s: seconds,
  })
  const trimmed = () => produce(example("quick-short-13s"), (d) => {
    ops.setDuration(d, "scn_01JDXQUICKMAIN", "fixed", 3)            // a 3 s opening scene over a 13 s clip
  })
  it("a hook longer than the opening scene extends it, up to the whole clip", () => {
    const before = trimmed()
    expect(ops.openingVoiceRoom(before, "scn_01JDXQUICKMAIN")).toBe(13)
    const seconds = ops.openingSceneSeconds(before, "scn_01JDXQUICKMAIN", 5.2)!
    expect(seconds).toBeCloseTo(5.45, 6)
    const after = produce(before, (d) => ops.addOpeningVoice(d, "scn_01JDXQUICKMAIN",
      "Watch how this mom surprises her son with GTA 6", take(5.2), seconds, true))
    expectValid(after)
    expect(ops.sceneFrames(after, after.scenes[0])).toBe(Math.floor(5.45 * 30 + 0.5))
    expect(after.scenes[0].narration?.take?.duration_s).toBe(5.2)
  })
  it("a short hook leaves the opening scene as it was", () => {
    const before = trimmed()
    expect(ops.openingSceneSeconds(before, "scn_01JDXQUICKMAIN", 2)).toBe(3)
  })
  it("a take longer than the whole opening clip is refused", () => {
    expect(ops.openingSceneSeconds(trimmed(), "scn_01JDXQUICKMAIN", 14)).toBeNull()
  })
})

describe("frame-accurate durations match the resolver", () => {
  it("quantises to whole frames", () => {
    const doc = produce(example("quick-short-13s"), (d) => { d.segments["seg_01JDXLOOKOUT13"].out_s = 41.5 + 12.345 })
    expect(ops.sceneFrames(doc, doc.scenes[0])).toBe(370)
    expect(ops.totalSeconds(example("silent-countdown"))).toBeCloseTo(315 / 30, 9)
  })
})
