// Put a random, non-repeating stretch of a library clip under the selected scene.
import { useState } from "react"
import { api } from "../api"
import { GameplayList } from "../library/GameplayLibrary"
import * as ops from "../model/ops"
import type { GameplayClip } from "../model/types"
import { useEditor } from "../state/editor"

export function GameplayPicker({ sceneId, onClose }: { sceneId: string; onClose: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const projectId = useEditor((s) => s.projectId)
  const { apply, selectLayer } = useEditor.getState()
  const [layout, setLayout] = useState<"split" | "pip" | "full">("split")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scene = doc.scenes.find((s) => s.id === sceneId)
  const seconds = scene ? ops.sceneFrames(doc, scene) / doc.output.fps : 10

  async function use(clip: GameplayClip) {
    setBusy(true)
    setError(null)
    try {
      const pick = await api.pickGameplay(clip.id, Math.max(1, seconds), projectId, sceneId)
      apply((d) => ops.addGameplay(d, sceneId, pick, layout))
      selectLayer(layout === "full" ? "primary" : "secondary")
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" role="dialog" aria-label="Gameplay background" data-testid="gameplay-picker">
      <div className="modal-box wide">
        <div className="modal-head">
          <h2>Gameplay background for “{scene?.name}”</h2>
          <button onClick={onClose}>Cancel</button>
        </div>
        <div className="row">
          <span>Show it as</span>
          <div className="seg-buttons" role="radiogroup" aria-label="Gameplay layout">
            {([["split", "Split screen (below)"], ["pip", "Picture in picture"], ["full", "Full-screen background"]] as const).map(([v, l]) => (
              <button key={v} className={layout === v ? "on" : ""} onClick={() => setLayout(v)} data-testid={`gp-layout-${v}`}>{l}</button>
            ))}
          </div>
        </div>
        <p className="hint">A random {seconds.toFixed(1)} s stretch is picked, avoiding parts used before. Its sound starts
          muted; it loops if the clip is shorter than the scene.</p>
        {error && <p className="error-text">{error}</p>}
        <fieldset disabled={busy} className="bare"><GameplayList onUse={(c) => void use(c)} useLabel="Use this clip" /></fieldset>
      </div>
    </div>
  )
}
