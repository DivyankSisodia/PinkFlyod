// Same algorithm, operation for operation, as backend/shorts_studio/timeline/geometry.py.
// Both are checked against schema/fixtures/placement-cases.json (geometry.test.ts, tests/test_geometry.py).
import type { Rect } from "./types"

export type Mode = "fill" | "fit" | "blur_fill"

export const even = (x: number): number => 2 * Math.floor(x / 2 + 0.5)
export const evenFloor = (x: number): number => 2 * Math.floor(x / 2)
const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v)

export function place(srcW: number, srcH: number, slotW: number, slotH: number, mode: Mode,
                      focusX: number, focusY: number, zoom: number): { src: Rect; dst: Rect } {
  const s = mode === "fill" ? Math.max(slotW / srcW, slotH / srcH) * zoom : Math.min(slotW / srcW, slotH / srcH) * zoom
  const dw = Math.min(srcW * s, slotW)
  const dh = Math.min(srcH * s, slotH)
  const cw = dw / s
  const ch = dh / s
  const x0 = clamp(focusX * srcW - cw / 2, 0, srcW - cw)
  const y0 = clamp(focusY * srcH - ch / 2, 0, srcH - ch)

  const dwI = Math.max(2, Math.min(even(dw), evenFloor(slotW)))
  const dhI = Math.max(2, Math.min(even(dh), evenFloor(slotH)))
  const cwI = Math.max(2, Math.min(even(cw), evenFloor(srcW)))
  const chI = Math.max(2, Math.min(even(ch), evenFloor(srcH)))
  const xI = Math.max(0, Math.min(even(x0), evenFloor(srcW - cwI)))
  const yI = Math.max(0, Math.min(even(y0), evenFloor(srcH - chI)))
  const dx = even((slotW - dwI) / 2)
  const dy = even((slotH - dhI) / 2)
  return { src: { x: xI, y: yI, w: cwI, h: chI }, dst: { x: dx, y: dy, w: dwI, h: dhI } }
}
