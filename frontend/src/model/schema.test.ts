import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"
// @ts-expect-error - plain ESM helper without type declarations
import { generateTypes, OUT_FILE } from "../../scripts/types-lib.mjs"

describe("generated types", () => {
  it("match the JSON Schema (run `npm run gen:types` if this fails)", async () => {
    const current = readFileSync(resolve(__dirname, "../..", OUT_FILE), "utf8").replace(/\r\n/g, "\n")
    expect(current).toEqual(await generateTypes())
  })
})
