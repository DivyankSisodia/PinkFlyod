import { useState } from "react"
import { api, type Ownership } from "../api"
import * as ops from "../model/ops"
import type { Source } from "../model/types"
import { useEditor } from "../state/editor"
import type { TrimTarget } from "../trim/TrimBench"
import { Thumb } from "../ui/Thumb"
import { clock } from "../ui/format"

const OWN_LABEL: Record<string, string> = { own: "mine", licensed: "licensed", third_party: "someone else's", unknown: "unknown" }

export function MediaPanel({ onTrim }: { onTrim: (t: TrimTarget) => void }) {
  const doc = useEditor((s) => s.doc)!
  const savedStatuses = useEditor((s) => s.statuses)
  const timeline = useEditor((s) => s.timeline)
  const { apply, setStatuses, flush, bumpMedia } = useEditor.getState()
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [ownership, setOwnership] = useState<Ownership>("own")
  // The resolver checks the current document's paths, so a relink shows as fixed straight away.
  const statuses: Record<string, string> = { ...savedStatuses }
  for (const [id, s] of Object.entries(timeline?.sources ?? {})) statuses[id] = s.status
  const missing = Object.entries(doc.sources).filter(([id]) => statuses[id] && statuses[id] !== "ok")

  async function addMedia() {
    setMessage(null)
    setBusy("Choose files…")
    try {
      const { paths } = await api.dialog("open_files", "Add media")
      if (!paths.length) return
      setBusy("Reading files…")
      const r = await api.addSources(doc.id, paths, ownership)
      apply((d) => ops.addSources(d, r.sources))
      setStatuses({ ...statuses, ...Object.fromEntries(Object.keys(r.sources).map((k) => [k, "ok"])) })
      if (r.errors.length) setMessage(r.errors.map((e) => e.error).join(" "))
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function relink(id: string, source: Source) {
    setMessage(null)
    setBusy("Choose the file…")
    try {
      const { paths } = await api.dialog("open_file", `Find ${source.display_name}`)
      if (!paths.length) return
      setBusy("Checking the file…")
      const r = await api.relinkCheck(paths[0], source)
      if (!r.ok) { setMessage(r.error ?? "That file can't be used."); return }
      if (!r.compatible && !confirm(`This file is different from the original: ${r.reasons?.join("; ")}.\n\nUse it anyway? Check your trims afterwards.`)) return
      apply((d) => ops.relinkSource(d, id, r.project_path as string, r.fingerprint!))
      setStatuses({ ...statuses, [id]: "ok" })
      await flush()          // the server serves media by source id from the saved project
      bumpMedia(id)
      setMessage(r.identical ? "Relinked: same file, new location." : "Relinked.")
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function searchFolder() {
    setMessage(null)
    setBusy("Choose a folder…")
    try {
      const { paths } = await api.dialog("open_folder", "Where are the missing files?")
      if (!paths.length) return
      setBusy("Searching…")
      const r = await api.relinkSearch(paths[0], Object.fromEntries(missing))
      const found = Object.entries(r.found)
      apply((d) => { for (const [id, f] of found) ops.relinkSource(d, id, f.project_path, f.fingerprint) })
      setStatuses({ ...statuses, ...Object.fromEntries(found.map(([id]) => [id, "ok"])) })
      await flush()
      for (const [id] of found) bumpMedia(id)
      setMessage(`Found ${found.length} of ${missing.length} missing file${missing.length > 1 ? "s" : ""}.`)
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <aside className="panel left" data-testid="media-panel">
      <div className="panel-head">
        <h3>Media</h3>
        <button onClick={addMedia} disabled={!!busy}>+ Add</button>
      </div>
      <label className="small">New files are
        <select value={ownership} onChange={(e) => setOwnership(e.target.value as Ownership)}>
          <option value="own">my own</option><option value="licensed">licensed</option>
          <option value="third_party">someone else's</option>
        </select>
      </label>
      {missing.length > 0 && (
        <div className="notice error small" data-testid="missing-notice">
          {missing.length} file{missing.length > 1 ? "s are" : " is"} missing or changed.
          <button onClick={searchFolder} disabled={!!busy}>Search a folder…</button>
        </div>
      )}
      <ul className="media-list">
        {Object.entries(doc.sources).map(([id, s]) => {
          const st = statuses[id] ?? "ok"
          return (
            <li key={id} className={`media-item ${st}`} data-testid="media-item">
              <div className="media-thumb">{st === "ok" && <Thumb sourceId={id} />}</div>
              <div className="media-meta">
                <strong title={s.path}>{s.display_name}</strong>
                <span>{s.kind}{s.fingerprint.duration_s ? ` · ${clock(s.fingerprint.duration_s, false)}` : ""}
                  {s.fingerprint.width ? ` · ${s.fingerprint.width}×${s.fingerprint.height}` : ""} · {OWN_LABEL[s.ownership]}</span>
                {st !== "ok" && <span className="badge err">{st === "missing" ? "Missing" : "Changed"}</span>}
                <div className="row">
                  {st !== "ok" && <button onClick={() => relink(id, s)} disabled={!!busy} data-testid="relink">Relink…</button>}
                  {st === "ok" && s.kind === "video" &&
                    <button onClick={() => onTrim({ sourceId: id, segmentId: null })}>Add a part…</button>}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      {busy && <p className="hint">{busy}</p>}
      {message && <p className="hint" data-testid="media-message">{message}</p>}
    </aside>
  )
}
