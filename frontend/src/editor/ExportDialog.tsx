import { useEffect, useState } from "react"
import { api } from "../api"
import { onEvent } from "../events"
import * as ops from "../model/ops"
import type { RenderRecord } from "../model/types"
import { useEditor } from "../state/editor"
import { bytes } from "../ui/format"

type Phase = { kind: "ready" } | { kind: "saving" } | { kind: "running"; jobId: string; pct: number; stage: string }
  | { kind: "done"; render: RenderRecord } | { kind: "failed"; error: string } | { kind: "cancelled" }

export function ExportDialog({ onClose }: { onClose: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const timeline = useEditor((s) => s.timeline)
  const { apply, flush, setRenders } = useEditor.getState()
  const [phase, setPhase] = useState<Phase>({ kind: "ready" })
  const errors = timeline?.issues.filter((i) => i.severity === "error") ?? []
  const warnings = timeline?.issues.filter((i) => i.severity === "warning") ?? []
  const rightsBlock = errors.some((e) => e.code === "rights_unconfirmed")
  const otherErrors = errors.filter((e) => e.code !== "rights_unconfirmed")
  const jobId = phase.kind === "running" ? phase.jobId : null

  useEffect(() => {
    if (!jobId) return
    let finished = false
    const finish = async () => {
      if (finished) return
      finished = true
      const job = await api.job(jobId)
      if (job.status === "done" && job.result) {
        const render = await api.render_(String(job.result.render_id))
        setPhase({ kind: "done", render })
        api.renders(doc.id).then((r) => setRenders(r.renders)).catch(() => undefined)
      } else if (job.status === "cancelled") setPhase({ kind: "cancelled" })
      else setPhase({ kind: "failed", error: job.error ?? "The export failed." })
    }
    const off = onEvent((e) => {
      if (!("job_id" in e) || e.job_id !== jobId) return
      if (e.type === "job.progress") setPhase((p) => (p.kind === "running" ? { ...p, pct: e.pct, stage: e.stage } : p))
      else if (e.type === "job.done" || e.type === "job.failed" || e.type === "job.cancelled") void finish()
    })
    // In case an event was missed (socket reconnecting), poll slowly too.
    const poll = setInterval(async () => {
      const job = await api.job(jobId).catch(() => null)
      if (job && ["done", "failed", "cancelled"].includes(job.status)) void finish()
      else if (job) setPhase((p) => (p.kind === "running" ? { ...p, pct: job.pct, stage: job.stage } : p))
    }, 2000)
    return () => { off(); clearInterval(poll) }
  }, [jobId, doc.id, setRenders])

  async function start() {
    setPhase({ kind: "saving" })
    const ok = await flush()
    const s = useEditor.getState()
    if (!ok || s.saveState !== "saved") {
      setPhase({ kind: "failed", error: s.saveError ?? "Save the project first." })
      return
    }
    try {
      const r = await api.render(doc.id, s.baseRevision)
      setPhase({ kind: "running", jobId: r.job_id, pct: 0, stage: "Queued" })
    } catch (e) {
      setPhase({ kind: "failed", error: (e as Error).message })
    }
  }

  const busy = phase.kind === "saving" || phase.kind === "running"
  return (
    <div className="modal" role="dialog" aria-label="Export" data-testid="export-dialog">
      <div className="modal-box export">
        <div className="modal-head">
          <h2>Export MP4</h2>
          <button onClick={onClose} disabled={busy}>Close</button>
        </div>
        <p className="hint">{doc.output.width}×{doc.output.height}, {doc.output.fps} fps, H.264
          {timeline?.audible ? `, AAC audio at ${doc.output.audio.loudness.target_lufs} LUFS` : ", no audio track"}
          {timeline ? ` · ${timeline.duration_s.toFixed(2)} s` : ""}</p>
        {timeline?.needs_rights && (
          <label className="check rights">
            <input type="checkbox" checked={doc.compliance.rights.confirmed} disabled={busy} data-testid="rights"
              onChange={(e) => apply((d) => ops.confirmRights(d, e.target.checked, new Date().toISOString().replace(/\.\d+Z$/, "Z")))} />
            I own this footage or have permission to use it in this video.
          </label>
        )}
        {otherErrors.length > 0 && <ul className="issues-list">{otherErrors.map((i, k) => <li key={k} className="error">{i.message}</li>)}</ul>}
        {warnings.length > 0 && <ul className="issues-list">{warnings.map((i, k) => <li key={k} className="warning">{i.message}</li>)}</ul>}

        {phase.kind === "running" && (
          <div className="progress" data-testid="progress">
            <div className="bar"><div style={{ width: `${phase.pct}%` }} /></div>
            <span>{phase.stage} · {Math.round(phase.pct)}%</span>
            <button onClick={() => api.cancelJob(phase.jobId)} data-testid="cancel">Cancel</button>
          </div>
        )}
        {phase.kind === "saving" && <p className="hint">Saving…</p>}
        {phase.kind === "failed" && <div className="notice error" data-testid="export-error">{phase.error}</div>}
        {phase.kind === "cancelled" && <div className="notice">Export cancelled.</div>}
        {phase.kind === "done" && <Done render={phase.render} />}

        {(phase.kind === "ready" || phase.kind === "failed" || phase.kind === "cancelled") && (
          <div className="row end">
            <button className="primary" onClick={start} disabled={otherErrors.length > 0 || rightsBlock || !timeline}
              data-testid="start-export">Export</button>
          </div>
        )}
        {!busy && <PreviousExports projectId={doc.id} />}
      </div>
    </div>
  )
}

/** Earlier exports of this project, newest first, with delete buttons. Deleted files go to the Recycle Bin. */
function PreviousExports({ projectId }: { projectId: string }) {
  const renders = useEditor((s) => s.renders)
  const { setRenders } = useEditor.getState()
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const files = renders.filter((r) => r.exists)
  const where = (recycled: boolean) => (recycled ? " (moved to the Recycle Bin)" : "")

  async function reload() {
    const r = await api.renders(projectId)
    setRenders(r.renders)
  }

  async function removeOne(id: string) {
    setBusy(id)
    setMessage(null)
    try {
      const r = await api.deleteRender(id)
      setMessage(`Deleted one export, freed ${bytes(r.freed_bytes)}${where(r.recycle_bin)}.`)
      await reload()
    } catch (e) { setMessage((e as Error).message) } finally { setBusy(null) }
  }

  async function keepLatest() {
    if (!confirm(`Delete ${files.length - 1} older export${files.length > 2 ? "s" : ""} and keep only the newest?`)) return
    setBusy("all")
    setMessage(null)
    try {
      const r = await api.pruneRenders(projectId, 1)
      setMessage(`Deleted ${r.deleted} older export${r.deleted === 1 ? "" : "s"}, freed ${bytes(r.freed_bytes)}${where(r.recycle_bin)}.`)
      await reload()
    } catch (e) { setMessage((e as Error).message) } finally { setBusy(null) }
  }

  if (!files.length && !message) return null
  return (
    <section className="previous-exports" data-testid="previous-exports">
      <div className="row between">
        <h3>Exported videos ({files.length})</h3>
        {files.length > 1 && <button onClick={() => void keepLatest()} disabled={!!busy} data-testid="keep-latest">
          {busy === "all" ? "Deleting…" : "Delete older, keep newest"}</button>}
      </div>
      <ul>
        {files.map((r, i) => (
          <li key={r.id} data-testid="export-row">
            <span><strong>{new Date(r.created_at).toLocaleString()}</strong>{i === 0 ? " · newest" : ""}
              <span className="hint"> · {r.verify.summary.duration_s.toFixed(1)} s · {bytes(r.verify.summary.size_bytes)}</span></span>
            <span className="row">
              <button onClick={() => api.openRender(r.id)}>Open</button>
              <button onClick={() => api.revealRender(r.id)}>Show in folder</button>
              <button className="danger" onClick={() => void removeOne(r.id)} disabled={!!busy}
                title="Delete this video" data-testid="delete-export">{busy === r.id ? "…" : "Delete"}</button>
            </span>
          </li>
        ))}
      </ul>
      {message && <p className="hint" role="status">{message}</p>}
    </section>
  )
}

function Done({ render }: { render: RenderRecord }) {
  const s = render.verify.summary
  return (
    <div className="done" data-testid="export-done">
      <video src={`/api/renders/${render.id}/file#t=0.5`} controls preload="auto" className="done-video" />
      <div>
        <p><strong>Checked with ffprobe</strong></p>
        <ul className="facts" data-testid="export-facts">
          <li>{s.width}×{s.height} at {s.fps} fps, {s.frames} frames</li>
          <li>{s.duration_s.toFixed(2)} s, {bytes(s.size_bytes)}</li>
          <li>{s.audio_streams ? `AAC audio, ${s.loudness?.integrated_lufs?.toFixed(1)} LUFS` : "No audio track"}</li>
          <li>Rendered in {render.verify.render_seconds} s</li>
        </ul>
        <p className="path" title={render.path}>{render.path}</p>
        <div className="row">
          <button className="primary" onClick={() => api.openRender(render.id)} data-testid="open-mp4">Open MP4</button>
          <button onClick={() => api.revealRender(render.id)}>Show in folder</button>
        </div>
      </div>
    </div>
  )
}
