import { useState } from "react"
import { Thumb } from "../ui/Thumb"
import * as ops from "../model/ops"
import type { Scene } from "../model/types"
import { useEditor } from "../state/editor"
import { takeState } from "../state/narration"
import type { TrimTarget } from "../trim/TrimBench"
import { clock } from "../ui/format"

function CardPicture({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const l = scene.layers.primary
  const seg = ops.primarySegment(doc, scene)
  if (seg) return <Thumb sourceId={seg.seg.source_id} className="card-thumb" />
  if (l.type === "image" && l.source_id) return <Thumb sourceId={l.source_id} className="card-thumb" />
  const bg = l.type === "text_card" ? l.text_card?.background : l.color
  return <div className="card-thumb swatch" style={{ background: bg ?? "#000" }}>{l.type === "text_card" ? "Aa" : ""}</div>
}

export function SceneStrip({ onTrim, onIntro }: { onTrim: (t: TrimTarget) => void; onIntro: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const selected = useEditor((s) => s.selectedSceneId)
  const timeline = useEditor((s) => s.timeline)
  const playhead = useEditor((s) => s.playhead)
  useEditor((s) => s.takeJobs)
  const { apply, select, setPlayhead } = useEditor.getState()
  const [dragId, setDragId] = useState<string | null>(null)
  const [dropAt, setDropAt] = useState<number | null>(null)
  const total = ops.totalSeconds(doc)
  const rankOf = ops.ranks(doc)
  const videos = Object.entries(doc.sources).filter(([, s]) => s.kind === "video")

  function drop(index: number) {
    if (!dragId) return
    const from = doc.scenes.findIndex((s) => s.id === dragId)
    // Dropping in the gap after the dragged card's own position means "one further along" once it's lifted out.
    const to = index > from ? index - 1 : index
    apply((d) => ops.moveSceneTo(d, dragId, to))
    setDragId(null)
    setDropAt(null)
  }

  function addScene(kind: string) {
    let id = ""
    if (kind === "line") apply((d) => { id = ops.addNarratedScene(d, "New line", selected ?? undefined) })
    else if (kind === "card") apply((d) => { id = ops.addCardScene(d, "Your text here", selected ?? undefined) })
    else if (kind.startsWith("src:")) { onTrim({ sourceId: kind.slice(4), segmentId: null }); return }
    if (id) select(id)
  }

  return (
    <footer className="strip" data-testid="scene-strip">
      <div className="strip-head">
        <h3>Timeline</h3>
        <span className="hint">{doc.scenes.length} scene{doc.scenes.length === 1 ? "" : "s"} · {total.toFixed(2)} s
          {doc.output.max_duration_s !== null ? ` (max ${doc.output.max_duration_s} s)` : ""}
          {doc.ranking.enabled ? " · drag to re-rank" : " · drag to reorder"}</span>
        <span className="grow" />
        <button className="timeline-intro-button" onClick={onIntro} data-testid="open-ai-intro">AI intro</button>
        <select value="" aria-label="Add a scene" data-testid="add-scene" onChange={(e) => e.target.value && addScene(e.target.value)}>
          <option value="">+ Add scene…</option>
          {videos.map(([id, s]) => <option key={id} value={`src:${id}`}>Part of {s.display_name}</option>)}
          <option value="line">A voice line</option>
          <option value="card">A text card</option>
        </select>
      </div>
      <div className="cards" onDragOver={(e) => e.preventDefault()}>
        {doc.scenes.map((scene, i) => {
          const r = timeline?.scenes.find((s) => s.id === scene.id)
          const seg = ops.primarySegment(doc, scene)
          const secs = ops.sceneFrames(doc, scene) / doc.output.fps
          const here = r && playhead >= r.start_s && playhead < r.start_s + r.duration_s
          const local = r ? playhead - r.start_s : 0
          const canSplit = !!here && !!seg && scene.duration.driver === "primary" && local > 0.1 && local < secs - 0.1
          const rank = rankOf[scene.id]
          const ts = scene.narration ? takeState(scene.id) : null
          const silent = !scene.audio.primary.enabled && !scene.audio.secondary.enabled && !scene.audio.narration.enabled
          return (
            <div key={scene.id}
              className={`card ${scene.id === selected ? "selected" : ""} ${scene.enabled ? "" : "off"} ${here ? "here" : ""} ${dragId === scene.id ? "dragging" : ""} ${dropAt === i ? "drop-before" : ""} ${dropAt === i + 1 && i === doc.scenes.length - 1 ? "drop-after" : ""}`}
              style={{ flexGrow: Math.max(secs, 1) }} data-testid="scene-card" data-scene-id={scene.id}
              draggable onDragStart={(e) => { setDragId(scene.id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", scene.id) }}
              onDragEnd={() => { setDragId(null); setDropAt(null) }}
              onDragOver={(e) => {
                e.preventDefault()
                const box = e.currentTarget.getBoundingClientRect()
                setDropAt(e.clientX < box.left + box.width / 2 ? i : i + 1)
              }}
              onDrop={(e) => { e.preventDefault(); drop(dropAt ?? i) }}
              onClick={() => { select(scene.id); if (r) setPlayhead(r.start_s) }}>
              <CardPicture scene={scene} />
              <div className="card-meta">
                <strong>{rank !== undefined && <span className="card-rank" data-testid="card-rank">#{rank}</span>}{i + 1}. {scene.name}</strong>
                <span>{secs.toFixed(2)} s{seg ? ` · from ${clock(seg.seg.in_s, false)}` : ""}</span>
                <span className="card-tags">
                  {scene.layers.secondary && <span className="tag">{scene.layout.type === "pip" ? "PiP" : scene.layout.type === "split" ? "split" : "2 layers"}</span>}
                  {ts && <span className={`tag take ${ts}`} title={`Voice: ${ts}`}>voice{ts === "stale" ? " ⟳" : ts === "missing" ? " ?" : ""}</span>}
                  {silent && <span className="tag">silent</span>}
                </span>
              </div>
              <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                {seg && <button title="Trim" onClick={() => onTrim({ sourceId: seg.seg.source_id, segmentId: seg.id })}>✂</button>}
                {canSplit && <button title="Split at the playhead" data-testid="split-scene"
                  onClick={() => { let id: string | null = null; apply((d) => { id = ops.splitScene(d, scene.id, local) }); if (id) select(id) }}>⫼</button>}
                <button title="Move left" disabled={i === 0} onClick={() => apply((d) => ops.moveScene(d, scene.id, -1))}>◀</button>
                <button title="Move right" disabled={i === doc.scenes.length - 1} onClick={() => apply((d) => ops.moveScene(d, scene.id, 1))}>▶</button>
                <button title="Duplicate" onClick={() => { let id = ""; apply((d) => { id = ops.duplicateScene(d, scene.id) }); select(id) }}>⧉</button>
                <button title="Mute this scene" data-testid="card-mute" disabled={silent}
                  onClick={() => apply((d) => ops.muteScene(d, scene.id))}>🔇</button>
                <button title={scene.enabled ? "Skip this scene" : "Use this scene"} onClick={() => apply((d) => ops.toggleScene(d, scene.id))}>
                  {scene.enabled ? "◉" : "○"}</button>
                <button title="Delete" disabled={doc.scenes.length === 1}
                  onClick={() => { apply((d) => ops.deleteScene(d, scene.id)); if (selected === scene.id) select(doc.scenes[0]?.id ?? null) }}>🗑</button>
              </div>
            </div>
          )
        })}
      </div>
    </footer>
  )
}
