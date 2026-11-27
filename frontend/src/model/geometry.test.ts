import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"
import { even, place, type Mode } from "./geometry"

interface Case {
  input: { src_w: number; src_h: number; slot_w: number; slot_h: number; mode: Mode; focus_x: number; focus_y: number; zoom: number }
  output: ReturnType<typeof place>
}

const cases: Case[] = JSON.parse(readFileSync(resolve(__dirname, "../../../schema/fixtures/placement-cases.json"), "utf8"))

describe("placement parity with the Python resolver", () => {
  it("has fixtures", () => expect(cases.length).toBeGreaterThan(10))
  for (const c of cases) {
    const i = c.input
    it(`${i.src_w}x${i.src_h} -> ${i.slot_w}x${i.slot_h} ${i.mode} (${i.focus_x}, ${i.focus_y}) x${i.zoom}`, () => {
      expect(place(i.src_w, i.src_h, i.slot_w, i.slot_h, i.mode, i.focus_x, i.focus_y, i.zoom)).toEqual(c.output)
    })
  }
  it("rounds halves up like Python's even()", () => {
    expect([0, 0.9, 1.0, 1.1, 2.9, 3.0, 607.5, 656.25].map(even)).toEqual([0, 0, 2, 2, 2, 4, 608, 656])
  })
})
