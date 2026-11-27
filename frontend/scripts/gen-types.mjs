// Generate TypeScript types from the one project schema: npm run gen:types
// The output is checked in; src/model/schema.test.ts fails if it is out of date.
import { writeFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { generateTypes, OUT_FILE } from "./types-lib.mjs"

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, "..", OUT_FILE)
writeFileSync(out, await generateTypes(), "utf8")
console.log(`wrote ${out}`)
