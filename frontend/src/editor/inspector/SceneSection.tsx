// One scene's picture: its layout (full, split, picture-in-picture, blurred fill), its two layers, and for each
// layer what it shows, how it is framed and what happens when the scene outlasts the clip.
import { useState } from "react"
import { api } from "../../api"
import * as ops from "../../model/ops"
import type { Scene } from "../../model/types"
import { useEditor } from "../../state/editor"
import type { TrimTarget } from "../../trim/TrimBench"
import { clock } from "../../ui/format"
import { Choice, Section, Slider, TextField, secFmt } from "./controls"

const MODES = [
  { value: "fill", label: "Fill (crop)" },
  { value: "fit", label: "Fit (bars)" },
  { value: "blur_fill", label: "Blurred fill" },
] as const

const LAYOUTS = [
  { value: "full", label: "Full" },
  { value: "split", label: "Split" },
  { value: "pip", label: "Picture in picture" },
] as const

const WHEN_SHORT = [
  { value: "loop", label: "Loop" },
  { value: "freeze_last", label: "Freeze" },
  { value: "slow_to_fit", label: "Slow down" },
  { value: "black", label: "Black" },
] as const

type Slot = "primary" | "secondary"

export function SceneSection({ scene, onTrim, onPickGameplay }: {
  scene: Scene; onTrim: (t: TrimTarget) => void; onPickGameplay: () => void
}) {
  const doc = useEditor((s) => s.doc)!
  const slotSel = useEditor((s) => s.selectedSlot)
  const timeline = useEditor((s) => s.timeline)
  const projectId = useEditor((s) => s.projectId)
  const { apply, selectLayer } = useEditor.getState()
  const [joinClip, setJoinClip] = useState<{ url: string; at: number } | null>(null)
  const [joinBusy, setJoinBusy] = useState<number | null>(null)
  const [joinError, setJoinError] = useState<string | null>(null)
  const slot: Slot = slotSel === "secondary" && scene.layers.secondary ? "secondary" : "primary"
  const layer = ops.layerOf(scene, slot)!
  const seg = ops.segmentOf(doc, scene, slot)
  const resolved = timeline?.scenes.find((s) => s.id === scene.id)
  const rLayer = resolved?.layers.find((l) => l.slot === slot)
  const rf = layer.reframe
  const hasSecondary = !!scene.layers.secondary
  const layoutType = scene.layout.type
  const sceneSecs = ops.sceneFrames(doc, scene) / doc.output.fps
  const videos = Object.entries(doc.sources).filter(([, s]) => s.kind === "video" || s.kind === "image")

  function useSource(sourceId: string) {
    const src = doc.sources[sourceId]
    if (src.kind === "image") apply((d) => ops.setLayerToImage(d, scene.id, slot, sourceId))
    else {
      const dur = src.fingerprint.duration_s ?? 0
      const len = slot === "primary" ? Math.min(dur, doc.output.max_duration_s ?? dur) : Math.min(dur, Math.max(sceneSecs, 1))
      apply((d) => ops.setLayerToSegment(d, scene.id, slot, sourceId, 0, len))
    }
  }

  function addSecond(kind: string) {
    if (kind === "gameplay") { onPickGameplay(); return }
    apply((d) => {
      if (kind === "color") ops.setLayerToColor(d, scene.id, "secondary", "#14213D")
      else if (kind === "text") ops.setLayerToTextCard(d, scene.id, "secondary", "Your text here")
      else {
        const src = d.sources[kind]
        if (src.kind === "image") ops.setLayerToImage(d, scene.id, "secondary", kind)
        else ops.setLayerToSegment(d, scene.id, "secondary", kind, 0, Math.min(src.fingerprint.duration_s ?? 0, Math.max(sceneSecs, 1)))
        d.scenes.find((s) => s.id === scene.id)!.audio.secondary.enabled = false
      }
      ops.setLayout(d, scene.id, "split")
    })
    selectLayer("secondary")
  }

  async function previewJoin(at: number) {
    if (!projectId) return
    setJoinBusy(at)
    setJoinError(null)
    try {
      const blob = await api.previewClip(projectId, doc, scene.id, Math.max(0, at - 1.5), at + 1.5)
      if (joinClip) URL.revokeObjectURL(joinClip.url)
      setJoinClip({ url: URL.createObjectURL(blob), at })
    } catch (e) {
      setJoinError((e as Error).message)
    } finally {
      setJoinBusy(null)
    }
  }

  const sourceName = (sid: string) => doc.sources[sid]?.display_name ?? "?"
  const layerLabel = (s: Slot) => {
    const l = ops.layerOf(scene, s)
    if (!l) return ""
    if (l.type === "segment") { const g = ops.segmentOf(doc, scene, s); return g ? sourceName(g.seg.source_id) : "clip" }
    if (l.type === "image") return sourceName(l.source_id as string)
    return l.type === "color" ? "colour" : "text card"
  }

  return (
    <>
      <Section title="Scene" testid="scene-section">
        <input className="name" value={scene.name} aria-label="Scene name" data-testid="scene-name"
          onChange={(e) => apply((d) => ops.renameScene(d, scene.id, e.target.value))} />
        <label className="slider"><span>Length</span>
          <select value={scene.duration.driver} data-testid="duration-driver"
            onChange={(e) => apply((d) => ops.setDuration(d, scene.id, e.target.value as "primary" | "narration" | "fixed",
              sceneSecs))}>
            {scene.layers.primary.type === "segment" && <option value="primary">follows the clip</option>}
            {scene.narration && <option value="narration">follows the voice</option>}
            <option value="fixed">fixed</option>
          </select>
          <span className="val">{resolved ? secFmt(resolved.duration_s) : ""}</span>
        </label>
        {scene.duration.driver === "fixed" && (
          <Slider label="Seconds" value={scene.duration.fixed_s ?? 3} min={0.5} max={30} step={0.1} testid="fixed-seconds"
            onChange={(v) => apply((d) => ops.setDuration(d, scene.id, "fixed", v))} fmt={secFmt} />
        )}
      </Section>

      <Section title="Layout" testid="layout-section">
        {hasSecondary ? (
          <>
            <Choice label="Layout" value={scene.layers.primary.reframe.mode === "blur_fill" && layoutType === "full" ? "full" : layoutType}
              options={LAYOUTS} testid="layout" onChange={(v) => apply((d) => ops.setLayout(d, scene.id, v))} />
            {layoutType === "split" && scene.layout.split && (
              <>
                <Slider label="Divider" value={scene.layout.split.divider} min={0.2} max={0.8} step={0.005} testid="divider"
                  onChange={(v) => apply((d) => ops.setSplit(d, scene.id, { divider: v }))} fmt={(v) => `${Math.round(v * 100)}%`} />
                <div className="row">
                  <span className="hint">Main layer on</span>
                  <Choice label="Main layer position" value={scene.layout.split.primary_position}
                    options={[{ value: "top", label: "Top" }, { value: "bottom", label: "Bottom" }] as const}
                    testid="split-pos" onChange={(v) => apply((d) => ops.setSplit(d, scene.id, { primary_position: v }))} />
                </div>
                <Slider label="Gap" value={scene.layout.split.gap_px} min={0} max={60} step={2}
                  onChange={(v) => apply((d) => ops.setSplit(d, scene.id, { gap_px: v }))} fmt={(v) => `${v} px`} />
              </>
            )}
            {layoutType === "pip" && scene.layout.pip && (
              <>
                <label className="slider"><span>Inset</span>
                  <select value={scene.layout.pip.inset_layer} data-testid="pip-inset"
                    onChange={(e) => apply((d) => ops.setPip(d, scene.id, { inset_layer: e.target.value as Slot }))}>
                    <option value="primary">main layer</option><option value="secondary">second layer</option>
                  </select>
                  <select value={scene.layout.pip.aspect} aria-label="Inset shape"
                    onChange={(e) => apply((d) => ops.setPip(d, scene.id, { aspect: e.target.value as "16:9" }))}>
                    <option value="16:9">16:9</option><option value="4:3">4:3</option><option value="1:1">1:1</option>
                    <option value="9:16">9:16</option><option value="source">as the clip</option>
                  </select>
                </label>
                <Slider label="Size" value={scene.layout.pip.width} min={0.15} max={0.9} step={0.01} testid="pip-size"
                  onChange={(v) => apply((d) => ops.setPip(d, scene.id, { width: v }))} fmt={(v) => `${Math.round(v * 100)}%`} />
                <Slider label="Across" value={scene.layout.pip.x} min={0} max={1} step={0.01} testid="pip-x"
                  onChange={(v) => apply((d) => ops.setPip(d, scene.id, { x: v }))} />
                <Slider label="Down" value={scene.layout.pip.y} min={0} max={1} step={0.01} testid="pip-y"
                  onChange={(v) => apply((d) => ops.setPip(d, scene.id, { y: v }))} />
                <Slider label="Corners" value={scene.layout.pip.corner_radius_px} min={0} max={80} step={1}
                  onChange={(v) => apply((d) => ops.setPip(d, scene.id, { corner_radius_px: v }))} fmt={(v) => `${v} px`} />
                <Slider label="Border" value={scene.layout.pip.border_px} min={0} max={20} step={1}
                  onChange={(v) => apply((d) => ops.setPip(d, scene.id, { border_px: v }))} fmt={(v) => `${v} px`} />
              </>
            )}
            <div className="row">
              <button onClick={() => apply((d) => ops.swapLayers(d, scene.id))} data-testid="swap-layers">Swap layers</button>
              <button onClick={() => { apply((d) => ops.removeSecondary(d, scene.id)); selectLayer("primary") }}
                data-testid="remove-secondary">Remove second layer</button>
            </div>
          </>
        ) : (
          <>
            <p className="hint">One layer, full screen. Add a second layer for a split screen or picture in picture.</p>
            <div className="row wrap">
              <button onClick={onPickGameplay} data-testid="add-gameplay">+ Gameplay background…</button>
              <select value="" aria-label="Add a second layer" data-testid="add-second"
                onChange={(e) => e.target.value && addSecond(e.target.value)}>
                <option value="">+ Second layer…</option>
                {videos.map(([id, s]) => <option key={id} value={id}>{s.display_name}</option>)}
                <option value="color">A colour</option>
                <option value="text">A text card</option>
              </select>
            </div>
          </>
        )}
      </Section>

      <Section title={hasSecondary ? "Layer" : "Picture"} testid="layer-section"
        extra={hasSecondary ? <span className="hint">{slot === "primary" ? "main" : "second"}</span> : null}>
        {hasSecondary && (
          <Choice label="Layer" value={slot} testid="layer"
            options={[{ value: "primary", label: `Main · ${layerLabel("primary")}` },
              { value: "secondary", label: `Second · ${layerLabel("secondary")}` }] as const}
            onChange={(v) => selectLayer(v)} />
        )}
        <label className="slider"><span>Shows</span>
          <select data-testid="layer-source"
            value={layer.type === "segment" ? seg?.seg.source_id ?? "" : layer.type === "image" ? layer.source_id ?? "" : layer.type}
            onChange={(e) => {
              const v = e.target.value
              if (v === "color") apply((d) => ops.setLayerToColor(d, scene.id, slot))
              else if (v === "text_card") apply((d) => ops.setLayerToTextCard(d, scene.id, slot))
              else if (v) useSource(v)
            }}>
            {videos.map(([id, s]) => <option key={id} value={id}>{s.display_name}</option>)}
            <option value="color">A colour</option>
            <option value="text_card">A text card</option>
          </select>
        </label>
        {seg && (
          <>
            <div className="row between">
              <span className="hint">{clock(seg.seg.in_s)} → {clock(seg.seg.out_s)} ({(seg.seg.out_s - seg.seg.in_s).toFixed(2)} s)</span>
              <button onClick={() => onTrim({ sourceId: seg.seg.source_id, segmentId: seg.id })}
                data-testid={slot === "primary" ? "open-trim" : "open-trim-secondary"}>Trim…</button>
            </div>
            {seg.seg.pick && <div className="hint">Random gameplay stretch (seed {seg.seg.pick.seed}).</div>}
            <label className="slider"><span>Speed</span>
              <select value={layer.playback?.speed ?? 1} data-testid="speed"
                onChange={(e) => apply((d) => ops.setPlayback(d, scene.id, slot, { speed: Number(e.target.value) }))}>
                {[0.5, 0.75, 1, 1.25, 1.5, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
              </select>
            </label>
            {(slot === "secondary" || scene.duration.driver !== "primary") && layer.playback && (
              <>
                <div className="row"><span className="hint">If the clip is shorter than the scene</span></div>
                <Choice label="When the clip is short" value={layer.playback.when_short} options={WHEN_SHORT} testid="when-short"
                  onChange={(v) => apply((d) => ops.setPlayback(d, scene.id, slot, { when_short: v }))} />
                {layer.playback.when_short === "loop" && (
                  <Slider label="Join blend" value={layer.playback.loop_crossfade_s} min={0} max={1} step={0.05} testid="crossfade"
                    onChange={(v) => apply((d) => ops.setPlayback(d, scene.id, slot, { loop_crossfade_s: v }))} fmt={secFmt} />
                )}
                <label className="check">
                  <input type="checkbox" checked={layer.playback.continue_from_previous} data-testid="continue-prev"
                    onChange={(e) => apply((d) => ops.setPlayback(d, scene.id, slot, { continue_from_previous: e.target.checked }))} />
                  Carry on from where the previous scene left this clip
                </label>
              </>
            )}
            {rLayer?.loop && rLayer.loop.joins.length > 0 && (
              <div className="joins" data-testid="joins">
                <span className="hint">Loops {rLayer.loop.copies.length - 1}× · joins at {rLayer.loop.joins.map((j) => `${j.toFixed(2)} s`).join(", ")}</span>
                <div className="row wrap">
                  {rLayer.loop.joins.slice(0, 4).map((j) => (
                    <button key={j} onClick={() => void previewJoin(j)} disabled={joinBusy !== null} data-testid="preview-join">
                      {joinBusy === j ? "Rendering…" : `Preview join ${j.toFixed(2)} s`}</button>
                  ))}
                </div>
              </div>
            )}
            {joinError && <p className="error-text">{joinError}</p>}
          </>
        )}
        {layer.type === "image" && (
          <label className="slider"><span>Motion</span>
            <select value={layer.motion ?? "none"} data-testid="motion"
              onChange={(e) => apply((d) => ops.setMotion(d, scene.id, slot, e.target.value as "none"))}>
              <option value="none">none</option><option value="ken_burns_in">slow zoom in</option>
              <option value="ken_burns_out">slow zoom out</option>
            </select>
          </label>
        )}
        {layer.type === "text_card" && layer.text_card && (
          <>
            <TextField multiline value={layer.text_card.text} label="Card text" testid="text-card-text" maxLength={500}
              onCommit={(v) => apply((d) => ops.setTextCard(d, scene.id, slot, { text: v }))} />
            <label className="slider"><span>Background</span>
              <input type="color" value={layer.text_card.background.slice(0, 7)}
                onChange={(e) => apply((d) => ops.setTextCard(d, scene.id, slot, { background: e.target.value.toUpperCase() }))} />
            </label>
          </>
        )}
        {layer.type === "color" && (
          <label className="slider"><span>Colour</span>
            <input type="color" value={(layer.color ?? "#000000").slice(0, 7)} data-testid="layer-color"
              onChange={(e) => apply((d) => ops.setColor(d, scene.id, slot, e.target.value.toUpperCase()))} />
          </label>
        )}
        {(layer.type === "segment" || layer.type === "image") && (
          <>
            <div className="subhead">Framing</div>
            <Choice label="Framing" value={rf.mode} options={MODES} testid="mode"
              onChange={(v) => apply((d) => ops.setReframe(d, scene.id, { mode: v }, slot))} />
            <Slider label="Left ↔ right" value={rf.focus.x} min={0} max={1} step={0.005} testid="focus-x"
              onChange={(v) => apply((d) => ops.setReframe(d, scene.id, { x: v }, slot))} />
            <Slider label="Up ↕ down" value={rf.focus.y} min={0} max={1} step={0.005} testid="focus-y"
              onChange={(v) => apply((d) => ops.setReframe(d, scene.id, { y: v }, slot))} />
            <Slider label="Zoom" value={rf.zoom} min={1} max={3} step={0.01} testid="zoom" fmt={(v) => `${v.toFixed(2)}×`}
              onChange={(v) => apply((d) => ops.setReframe(d, scene.id, { zoom: v }, slot))} />
            <div className="row">
              <button onClick={() => apply((d) => ops.setReframe(d, scene.id, { x: 0.5, y: 0.5, zoom: 1 }, slot))}>Centre</button>
              <span className="hint">Or drag the picture in the preview.</span>
            </div>
          </>
        )}
      </Section>
      {joinClip && (
        <div className="modal" role="dialog" aria-label="Loop join preview" data-testid="join-preview">
          <div className="modal-box join">
            <div className="modal-head">
              <h2>Loop join at {joinClip.at.toFixed(2)} s, rendered by the export pipeline</h2>
              <button onClick={() => { URL.revokeObjectURL(joinClip.url); setJoinClip(null) }} data-testid="join-close">Done</button>
            </div>
            <video src={joinClip.url} controls autoPlay loop muted playsInline className="join-video" />
            <p className="hint">1.5 s either side of the join, exactly as the export renders it (picture only).</p>
          </div>
        </div>
      )}
    </>
  )
}
