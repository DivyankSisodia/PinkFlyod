// Delete a whole project after showing exactly what goes: its exports, saved history, and media it copied or
// downloaded that no other project uses. Everything goes to the Recycle Bin on Windows.
import { useEffect, useRef, useState } from "react"
import { api } from "../api"
import type { ProjectSummary } from "../model/types"
import { bytes } from "../ui/format"

type Preview = Awaited<ReturnType<typeof api.deletePreview>>

export function DeleteProjectDialog({ project, onClose, onDeleted }: {
  project: ProjectSummary; onClose: () => void; onDeleted: (message: string) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const d = ref.current
    d?.showModal()
    return () => d?.close()
  }, [])
  useEffect(() => {
    api.deletePreview(project.id).then(setPreview).catch((e) => setError((e as Error).message))
  }, [project.id])

  async function remove() {
    setBusy(true)
    setError("")
    try {
      const r = await api.deleteProject(project.id)
      onDeleted(`Deleted “${project.title}” and freed ${bytes(r.freed_bytes)}` +
        (r.recycle_bin ? ". It's in the Recycle Bin if you need it back." : "."))
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} className="modal-box delete-dialog" aria-labelledby="delete-title" data-testid="delete-dialog"
      onCancel={(e) => { e.preventDefault(); if (!busy) onClose() }}>
      <div className="modal-head"><h2 id="delete-title">Delete “{project.title}”?</h2>
        <button onClick={onClose} disabled={busy}>Cancel</button></div>
      {!preview && !error && <p className="hint">Checking what this would remove…</p>}
      {preview && (
        <>
          <p>This removes:</p>
          <ul className="facts">
            <li>the project, its edits and saved history</li>
            <li>{preview.exports} exported video{preview.exports === 1 ? "" : "s"}
              {preview.exports ? ` (${bytes(preview.exports_bytes)})` : ""}</li>
            {preview.media_files.length > 0 && <li>{preview.media_files.length} copied or downloaded
              file{preview.media_files.length === 1 ? "" : "s"} no other project uses ({bytes(preview.media_bytes)})</li>}
          </ul>
          <p className="hint">Kept: your own files linked from elsewhere on your computer, the gameplay library, and
            anything another project still uses. Frees about {bytes(preview.total_bytes)}. On Windows it goes to the
            Recycle Bin.</p>
        </>
      )}
      {error && <p role="alert" className="error-text">{error}</p>}
      <div className="row end">
        <button className="danger" onClick={() => void remove()} disabled={!preview || busy} data-testid="confirm-delete">
          {busy ? "Deleting…" : "Delete project"}</button>
      </div>
    </dialog>
  )
}
