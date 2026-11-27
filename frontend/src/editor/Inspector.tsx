import { useEditor } from "../state/editor"
import type { TrimTarget } from "../trim/TrimBench"
import { NarrationSection } from "./inspector/NarrationSection"
import { CaptionsSection, OverlaysSection } from "./inspector/OverlaySections"
import { ProjectSection } from "./inspector/ProjectSection"
import { SceneSection } from "./inspector/SceneSection"
import { SoundSection } from "./inspector/SoundSection"

export function Inspector({ onTrim, onPickGameplay }: { onTrim: (t: TrimTarget) => void; onPickGameplay: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const selected = useEditor((s) => s.selectedSceneId)
  const timeline = useEditor((s) => s.timeline)
  const scene = doc.scenes.find((s) => s.id === selected) ?? null
  const issues = timeline?.issues ?? []
  const sceneIssues = issues.filter((i) => scene && i.scene_id === scene.id)

  return (
    <aside className="panel right" data-testid="inspector">
      {scene ? (
        <div key={scene.id}>
          <SceneSection scene={scene} onTrim={onTrim} onPickGameplay={onPickGameplay} />
          <NarrationSection scene={scene} />
          <CaptionsSection scene={scene} />
          <OverlaysSection scene={scene} />
          <SoundSection scene={scene} />
          {sceneIssues.length > 0 && (
            <ul className="issues-list" data-testid="scene-issues">
              {sceneIssues.map((i, k) => <li key={k} className={i.severity}>{i.message}</li>)}
            </ul>
          )}
        </div>
      ) : <p className="hint">Select a scene below.</p>}
      <div className="divider-title">Whole video</div>
      <ProjectSection />
      {issues.length > 0 && (
        <details className="section" open>
          <summary><span>Notes</span></summary>
          <ul className="issues-list" data-testid="issues">
            {issues.map((i, k) => <li key={k} className={i.severity}>{i.message}</li>)}
          </ul>
        </details>
      )}
    </aside>
  )
}
