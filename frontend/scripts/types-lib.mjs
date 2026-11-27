import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { compile } from "json-schema-to-typescript"

const here = dirname(fileURLToPath(import.meta.url))
export const SCHEMA_FILE = resolve(here, "..", "..", "schema", "project.v1.schema.json")
export const OUT_FILE = "src/model/project.gen.ts"

export async function generateTypes() {
  const schema = JSON.parse(readFileSync(SCHEMA_FILE, "utf8"))
  schema.title = "Project"
  const banner = "/* Generated from schema/project.v1.schema.json by `npm run gen:types`. Do not edit. */"
  const ts = await compile(schema, "Project", {
    bannerComment: banner,
    additionalProperties: false,
    unreachableDefinitions: true,
    strictIndexSignatures: false,
    maxItems: -1,
    format: false,
  })
  return ts.replace(/\r\n/g, "\n")
}
