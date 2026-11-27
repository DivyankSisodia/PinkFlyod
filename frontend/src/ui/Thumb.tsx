import { useEffect, useState } from "react"
import { api, filmstripUrl, posterUrl } from "../api"
import { useEditor } from "../state/editor"

/** A poster or filmstrip shown only once the background job has made it for the current file version
 *  (no requests for images that don't exist yet; reloads when a relink or a finished job bumps the version). */
export function Thumb({ sourceId, kind = "poster", className }: {
  sourceId: string; kind?: "poster" | "filmstrip"; className?: string
}) {
  const version = useEditor((s) => s.mediaVersion[sourceId] ?? 0)
  const [readyFor, setReadyFor] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    api.mediaInfo(sourceId)
      .then((info) => { if (alive && (kind === "poster" ? info.has_poster : info.has_filmstrip)) setReadyFor(version) })
      .catch(() => undefined)
    return () => { alive = false }
  }, [sourceId, kind, version])
  if (readyFor !== version) return <div className={`${className ?? ""} thumb-pending`} aria-hidden />
  const src = kind === "poster" ? posterUrl(sourceId, String(version)) : filmstripUrl(sourceId, String(version))
  return <img className={className} src={src} alt="" draggable={false} />
}
