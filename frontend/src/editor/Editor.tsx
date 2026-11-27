import { useEffect, useState } from "react"
import { api } from "../api"
import { onEvent } from "../events"
import { Player } from "../player/Player"
import { saveOnUnload, useEditor } from "../state/editor"
import { TrimBench, type TrimTarget } from "../trim/TrimBench"
import { ExportDialog } from "./ExportDialog"
import { GameplayPicker } from "./GameplayPicker"
import { Inspector } from "./Inspector"
import { IntroDialog } from "./IntroDialog"
import { MediaPanel } from "./MediaPanel"
import { SceneStrip } from "./SceneStrip"
import { TopBar } from "./TopBar"

export function Editor({ projectId }: { projectId: string }) {
  const doc = useEditor((s) => s.doc)
  const [error, setError] = useState<string | null>(null)
  const [trim, setTrim] = useState<TrimTarget | null>(null)
  const [exporting, setExporting] = useState(false)
  const [introOpen, setIntroOpen] = useState(false)
  const [picking, setPicking] = useState<string | null>(null)
  const selected = useEditor((s) => s.selectedSceneId)

  useEffect(() => {
    useEditor.getState().load(projectId).catch((e) => setError(e.message))
    const off = onEvent((e) => {
      if (e.type === "media.updated") useEditor.getState().bumpMedia(e.source_id)
    })
    const unload = () => saveOnUnload()
    window.addEventListener("beforeunload", unload)
    return () => {
      off()
      window.removeEventListener("beforeunload", unload)
      void useEditor.getState().flush().finally(() => useEditor.getState().close())
    }
  }, [projectId])

  // Re-check media whenever the window regains focus (a file may have been moved meanwhile).
  useEffect(() => {
    const onFocus = () => {
      const s = useEditor.getState()
      if (!s.projectId) return
      api.getProject(s.projectId).then((r) => { s.setStatuses(r.statuses); s.setRenders(r.renders) }).catch(() => undefined)
    }
    window.addEventListener("focus", onFocus)
    return () => window.removeEventListener("focus", onFocus)
  }, [])

  // Undo / redo shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); useEditor.getState().undo() }
      else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
        e.preventDefault(); useEditor.getState().redo()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  if (error) return <div className="page-error">Could not open this project: {error} <a href="#/">Back to start</a></div>
  if (!doc) return <div className="page-error">Opening…</div>
  return (
    <div className="editor">
      <TopBar onExport={() => setExporting(true)} />
      <MediaPanel onTrim={setTrim} />
      <main className="center"><Player projectId={projectId} /></main>
      <Inspector onTrim={setTrim} onPickGameplay={() => selected && setPicking(selected)} />
      <SceneStrip onTrim={setTrim} onIntro={() => setIntroOpen(true)} />
      {trim && <TrimBench target={trim} onClose={() => setTrim(null)} />}
      {picking && <GameplayPicker sceneId={picking} onClose={() => setPicking(null)} />}
      {exporting && <ExportDialog onClose={() => setExporting(false)} />}
      {introOpen && <IntroDialog onClose={() => setIntroOpen(false)} />}
    </div>
  )
}
