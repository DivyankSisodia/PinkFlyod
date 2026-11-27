// Same layout as backend/shorts_studio/ids.py: prefix + 10 chars of milliseconds + 16 random chars (Crockford base32).
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

function encode(value: bigint, length: number): string {
  let out = ""
  for (let i = 0; i < length; i++) {
    out = ALPHABET[Number(value % 32n)] + out
    value /= 32n
  }
  return out
}

export function newId(prefix: "src" | "seg" | "scn" | "ovl" | "sfx"): string {
  const ms = BigInt(Date.now()) & ((1n << 48n) - 1n)
  const bytes = new Uint8Array(10)
  crypto.getRandomValues(bytes)
  let rnd = 0n
  for (const b of bytes) rnd = (rnd << 8n) | BigInt(b)
  return `${prefix}_${encode(ms, 10)}${encode(rnd, 16)}`
}
