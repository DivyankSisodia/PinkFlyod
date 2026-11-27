export function clock(t: number, withCentis = true): string {
  if (!Number.isFinite(t)) return "0:00"
  const sign = t < 0 ? "-" : ""
  t = Math.abs(t)
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  const cs = Math.floor((t * 100) % 100)
  return `${sign}${m}:${String(s).padStart(2, "0")}${withCentis ? "." + String(cs).padStart(2, "0") : ""}`
}

export function seconds(t: number): string {
  return `${t.toFixed(2)} s`
}

export function ago(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 1000
  if (d < 60) return "just now"
  if (d < 3600) return `${Math.floor(d / 60)} min ago`
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
}

export function bytes(n: number): string {
  if (n > 1e9) return `${(n / 1e9).toFixed(2)} GB`
  if (n > 1e6) return `${(n / 1e6).toFixed(1)} MB`
  return `${Math.round(n / 1e3)} KB`
}
