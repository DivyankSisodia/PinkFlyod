import { useState, type ReactNode } from "react"
import * as ops from "../model/ops"
import { useEditor } from "../state/editor"
import type { TrimTarget } from "../trim/TrimBench"
import { NarrationSection } from "./inspector/NarrationSection"
import { CaptionsSection, OverlaysSection } from "./inspector/OverlaySections"
import { ProjectSection } from "./inspector/ProjectSection"
import { SceneSection } from "./inspector/SceneSection"
import { SoundSection } from "./inspector/SoundSection"

type InspectorTab = "clip" | "voice" | "captions" | "overlays" | "audio" | "project"

function TabIcon({ name }: { name: InspectorTab }) {
  const props = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true }
  switch (name) {
    case "clip":
      return <svg {...props}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16M3 12h18" /></svg>
    case "voice":
      return <svg {...props}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" /></svg>
    case "captions":
      return <svg {...props}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 13h4M13 13h4M7 10h2M11 10h6" /></svg>
    case "overlays":
      return <svg {...props}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9h10M7 13h6" /><circle cx="16.5" cy="14.5" r="2" /></svg>
    case "audio":
      return <svg {...props}><path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" /></svg>
    case "project":
      return <svg {...props}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
  }
}

export function Inspector({ onTrim, onPickGameplay }: { onTrim: (t: TrimTarget) => void; onPickGameplay: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const selected = useEditor((s) => s.selectedSceneId)
  const timeline = useEditor((s) => s.timeline)
  const [tab, setTab] = useState<InspectorTab>("clip")
  const scene = doc.scenes.find((s) => s.id === selected) ?? null
  const issues = timeline?.issues ?? []
  const sceneIssues = issues.filter((i) => scene && i.scene_id === scene.id)

  const hasVoice = !!scene?.narration
  const hasCaptions = !!scene && doc.captions.enabled && scene.captions.mode !== "off"
  const hasOverlays = !!scene && (scene.overlays.label.visible || !!scene.overlays.reddit_card || scene.overlays.texts.length > 0)
  const hasAudio = !!scene && (scene.sfx.length > 0 || (!!doc.audio.music && scene.audio.music.enabled))
  const hasProjectActive = issues.length > 0 || !!doc.audio.music || doc.ranking.enabled || !!doc.overlays.title_bar || !!doc.overlays.hook
  const primarySeg = scene ? ops.primarySegment(doc, scene) : null
  const isVideoWithVoice = !!scene?.narration && !!primarySeg && doc.sources[primarySeg.seg.source_id]?.kind === "video" && scene.duration.driver !== "narration"
  const { apply, select, setPlayhead } = useEditor.getState()

  const tabs: { id: InspectorTab; label: string; title: string; dot?: boolean; warn?: boolean }[] = [
    { id: "clip", label: "Clip", title: "Scene framing, trim, speed & split-screen layout" },
    { id: "voice", label: "Voice", title: "Per-scene AI voiceover, mic recording & audio takes", dot: hasVoice },
    { id: "captions", label: "Captions", title: "Word-synced captions & manual cues", dot: hasCaptions },
    { id: "overlays", label: "Overlays", title: "Reddit post cards, text overlays & labels", dot: hasOverlays },
    { id: "audio", label: "Audio", title: "Scene volume, ducking & sound effects", dot: hasAudio },
    { id: "project", label: "Project", title: "Whole video: TTS voice, music, ranking, caption style & titles", dot: hasProjectActive, warn: issues.some((i) => i.severity === "error") },
  ]

  let body: ReactNode
  if (tab === "project") {
    body = (
      <div className="inspector-body">
        <ProjectSection />
        {issues.length > 0 && (
          <details className="section" open>
            <summary><span>Notes ({issues.length})</span></summary>
            <ul className="issues-list" data-testid="issues">
              {issues.map((i, k) => <li key={k} className={i.severity}>{i.message}</li>)}
            </ul>
          </details>
        )}
      </div>
    )
  } else if (!scene) {
    body = <div className="inspector-body"><p className="hint">Select a scene in the timeline below to edit it.</p></div>
  } else {
    body = (
      <div className="inspector-body" key={`${scene.id}-${tab}`}>
        {tab === "clip" && isVideoWithVoice && (
          <div className="subgroup" style={{ marginBottom: 10 }}>
            <div className="hint">Voiceover &amp; video audio overlap on this scene.</div>
            <button
              className="primary"
              data-testid="clip-split-voiceover-intro"
              onClick={() => {
                let introId: string | null = null
                apply((d) => { introId = ops.splitVoiceoverToIntroClip(d, scene.id) })
                if (introId) {
                  select(introId)
                  setPlayhead(0)
                }
              }}
            >
              Play voiceover over random clip first
            </button>
          </div>
        )}
        {tab === "clip" && <SceneSection scene={scene} onTrim={onTrim} onPickGameplay={onPickGameplay} />}
        {tab === "voice" && <NarrationSection scene={scene} />}
        {tab === "captions" && <CaptionsSection scene={scene} />}
        {tab === "overlays" && <OverlaysSection scene={scene} />}
        {tab === "audio" && <SoundSection scene={scene} />}
        {sceneIssues.length > 0 && (
          <ul className="issues-list" data-testid="scene-issues">
            {sceneIssues.map((i, k) => <li key={k} className={i.severity}>{i.message}</li>)}
          </ul>
        )}
      </div>
    )
  }

  return (
    <aside className="panel right inspector-modern" data-testid="inspector">
      <nav className="inspector-tabs" role="tablist" aria-label="Inspector sections" data-testid="inspector-tabs">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} title={t.title}
            data-testid={`tab-${t.id}`}
            className={`inspector-tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}>
            <TabIcon name={t.id} />
            <span>{t.label}</span>
            {t.warn ? <i className="tab-dot warn" aria-hidden /> : t.dot ? <i className="tab-dot" aria-hidden /> : null}
          </button>
        ))}
      </nav>
      {body}
    </aside>
  )
}
