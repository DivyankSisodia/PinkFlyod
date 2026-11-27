import { useState } from "react"
import * as ops from "../model/ops"
import { useEditor, type SaveState } from "../state/editor"

const LABEL: Record<SaveState, string> = {
  saved: "Saved", dirty: "Unsaved changes", saving: "Saving…", error: "Not saved — retrying",
  conflict: "Changed in another tab", readonly: "Read-only",
}

export function TopBar({ onExport, onUpload }: { onExport: () => void; onUpload: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const saveState = useEditor((s) => s.saveState)
  const saveError = useEditor((s) => s.saveError)
  const canUndo = useEditor((s) => s.past.length > 0)
  const canRedo = useEditor((s) => s.future.length > 0)
  const timeline = useEditor((s) => s.timeline)
  const { apply, undo, redo } = useEditor.getState()
  const [title, setTitle] = useState<string | null>(null)
  const errors = timeline?.issues.filter((i) => i.severity === "error").length ?? 0
  const warnings = timeline?.issues.filter((i) => i.severity === "warning").length ?? 0

  return (
    <header className="topbar">
      <a href="#/" className="back" title="All projects">← Projects</a>
      <input className="title-input" value={title ?? doc.title} aria-label="Project title" data-testid="title"
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => { if (title !== null) apply((d) => ops.setTitle(d, title)); setTitle(null) }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
      <span className={`save ${saveState}`} title={saveError ?? ""} data-testid="save-state">{LABEL[saveState]}</span>
      {saveState === "conflict" && <button onClick={() => location.reload()}>Reload</button>}
      <span className="grow" />
      <button onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)" data-testid="undo">↶ Undo</button>
      <button onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Y)" data-testid="redo">↷ Redo</button>
      <span className="issues" title={timeline?.issues.map((i) => i.message).join("\n")}>
        {errors > 0 && <span className="badge err">{errors} to fix</span>}
        {warnings > 0 && <span className="badge warn">{warnings} note{warnings > 1 ? "s" : ""}</span>}
      </span>
      <a href="#/activity" className="back" target="_blank" rel="noopener" title="Open job activity in a new tab">Activity</a>
      <button onClick={onUpload} disabled={saveState === "readonly"} data-testid="upload-details"
        title="Title, description and YouTube tags">Upload details</button>
      <button className="primary" onClick={onExport} disabled={saveState === "readonly"} data-testid="export">Export MP4</button>
    </header>
  )
}
