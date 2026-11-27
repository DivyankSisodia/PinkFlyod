// Pick the in and out points on a source: a player, a filmstrip rail with two handles, I/O keys, exact entry,
// and the project's length cap (15 s for a Quick Short).
import { useEffect, useRef, useState } from "react"
import { mediaUrl } from "../api"
import * as ops from "../model/ops"
import { useEditor } from "../state/editor"
import { Thumb } from "../ui/Thumb"
import { clock } from "../ui/format"

export interface TrimTarget {
  sourceId: string
  segmentId: string | null          // null = a new scene will be added
}

export function TrimBench({ target, onClose }: { target: TrimTarget; onClose: () => void }) {
  const doc = useEditor((s) => s.doc)
  const mediaVersion = useEditor((s) => s.mediaVersion[target.sourceId] ?? 0)
  const { apply, select } = useEditor.getState()
  const videoRef = useRef<HTMLVideoElement>(null)
  const railRef = useRef<HTMLDivElement>(null)
  const source = doc?.sources[target.sourceId]
  const duration = source?.fingerprint.duration_s ?? 0
  const fps = doc?.output.fps ?? 30
  const cap = doc?.output.max_duration_s ?? null
  const existing = target.segmentId ? doc?.segments[target.segmentId] : null
  const initial = existing ? [existing.in_s, existing.out_s]
    : ops.clampTrim(0, Math.min(duration, cap ?? ops.QUICK_SHORT_DEFAULT_S, ops.QUICK_SHORT_DEFAULT_S), duration, fps, cap, "both")
  const [range, setRange] = useState<[number, number]>([initial[0], initial[1]])
  const [t, setT] = useState(initial[0])
  const [playing, setPlaying] = useState(false)
  const [loopSel, setLoopSel] = useState(true)
  const dragging = useRef<"in" | "out" | "head" | null>(null)

  const [a, b] = range
  const len = b - a

  function setBoth(next: [number, number], moved: "in" | "out" | "both") {
    const r = ops.clampTrim(next[0], next[1], duration, fps, cap, moved)
    setRange(r)
    return r
  }

  function seek(x: number) {
    const v = videoRef.current
    const tt = Math.max(0, Math.min(duration, x))
    setT(tt)
    if (v) v.currentTime = tt
  }

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => {
      setT(v.currentTime)
      if (loopSel && !v.paused && v.currentTime >= range[1]) v.currentTime = range[0]
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    v.addEventListener("timeupdate", onTime)
    v.addEventListener("play", onPlay)
    v.addEventListener("pause", onPause)
    return () => { v.removeEventListener("timeupdate", onTime); v.removeEventListener("play", onPlay); v.removeEventListener("pause", onPause) }
  }, [range, loopSel])

  useEffect(() => { if (videoRef.current) videoRef.current.currentTime = initial[0] }, []) // eslint-disable-line

  function togglePlay() {
    const v = videoRef.current
    if (!v) return
    if (v.paused) {
      if (loopSel && (v.currentTime < a || v.currentTime >= b - 0.05)) v.currentTime = a
      void v.play()
    } else v.pause()
  }

  function step(frames: number) {
    videoRef.current?.pause()
    seek(t + frames / fps)
  }

  function markIn() { const r = setBoth([t, Math.max(b, t + 1 / fps)], "in"); seek(r[0]) }
  function markOut() { const r = setBoth([Math.min(a, t - 1 / fps), t], "out"); seek(r[1]) }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return
      if (e.key === "i" || e.key === "I") { e.preventDefault(); markIn() }
      else if (e.key === "o" || e.key === "O") { e.preventDefault(); markOut() }
      else if (e.code === "Space") { e.preventDefault(); togglePlay() }
      else if (e.key === "ArrowLeft") { e.preventDefault(); step(e.shiftKey ? -10 : -1) }
      else if (e.key === "ArrowRight") { e.preventDefault(); step(e.shiftKey ? 10 : 1) }
      else if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  function timeAt(clientX: number) {
    const r = railRef.current!.getBoundingClientRect()
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration
  }

  function onRailDown(e: React.PointerEvent<HTMLDivElement>, what: "in" | "out" | "head") {
    e.stopPropagation()
    dragging.current = what
    railRef.current?.setPointerCapture(e.pointerId)
    videoRef.current?.pause()
    if (what === "head") seek(timeAt(e.clientX))
  }

  function onRailMove(e: React.PointerEvent<HTMLDivElement>) {
    const what = dragging.current
    if (!what) return
    const x = timeAt(e.clientX)
    if (what === "head") seek(x)
    else if (what === "in") { const r = setBoth([x, b], "in"); seek(r[0]) }
    else { const r = setBoth([a, x], "out"); seek(r[1]) }
  }

  function commit() {
    if (!doc) return
    if (target.segmentId) {
      apply((d) => ops.setTrim(d, target.segmentId as string, a, b, "both"))
    } else {
      let id = ""
      apply((d) => { id = ops.addSceneFromSource(d, target.sourceId, a, b) })
      if (id) select(id)
    }
    onClose()
  }

  if (!source) return null
  const pct = (x: number) => `${(x / Math.max(duration, 1e-6)) * 100}%`
  const tooShortHint = doc?.origin.preset === "quick_short" && len < ops.QUICK_SHORT_MIN_HINT_S - 1e-6
  return (
    <div className="modal" role="dialog" aria-label="Trim" data-testid="trim-bench">
      <div className="modal-box trim">
        <div className="modal-head">
          <h2>Choose the part to use · {source.display_name}</h2>
          <button onClick={onClose}>Cancel</button>
        </div>
        <video ref={videoRef} className="trim-video" src={mediaUrl(target.sourceId, "preview", String(mediaVersion))}
          preload="auto" playsInline onClick={togglePlay} data-testid="trim-video" />
        <div className="rail" ref={railRef} onPointerDown={(e) => onRailDown(e, "head")} onPointerMove={onRailMove}
          onPointerUp={() => (dragging.current = null)} data-testid="trim-rail">
          <Thumb sourceId={target.sourceId} kind="filmstrip" className="filmstrip" />
          <div className="sel" style={{ left: pct(a), width: pct(len) }} />
          <div className="handle in" style={{ left: pct(a) }} onPointerDown={(e) => onRailDown(e, "in")}
            title="In point (I)" data-testid="handle-in" />
          <div className="handle out" style={{ left: pct(b) }} onPointerDown={(e) => onRailDown(e, "out")}
            title="Out point (O)" data-testid="handle-out" />
          <div className="head" style={{ left: pct(t) }} />
        </div>
        <div className="trim-row">
          <button className="primary" onClick={togglePlay}>{playing ? "Pause" : "Play"}</button>
          <button onClick={() => step(-1)} title="Back one frame (←)">◀ 1f</button>
          <button onClick={() => step(1)} title="Forward one frame (→)">1f ▶</button>
          <span className="time">{clock(t)}</span>
          <button onClick={markIn} data-testid="mark-in">Mark in (I)</button>
          <button onClick={markOut} data-testid="mark-out">Mark out (O)</button>
          <label className="check"><input type="checkbox" checked={loopSel} onChange={(e) => setLoopSel(e.target.checked)} />
            Loop selection</label>
        </div>
        <div className="trim-row">
          <label>In <input type="number" step={1 / fps} min={0} max={duration} value={a.toFixed(3)} data-testid="in-input"
            onChange={(e) => { const r = setBoth([Number(e.target.value), b], "in"); seek(r[0]) }} /> s</label>
          <label>Out <input type="number" step={1 / fps} min={0} max={duration} value={b.toFixed(3)} data-testid="out-input"
            onChange={(e) => { const r = setBoth([a, Number(e.target.value)], "out"); seek(r[1]) }} /> s</label>
          <span className={`len ${cap !== null && len >= cap - 1e-6 ? "at-cap" : ""}`} data-testid="trim-length">
            {len.toFixed(2)} s{cap !== null ? ` of max ${cap} s` : ""}</span>
          {tooShortHint && <span className="hint">Quick Shorts work best at 12–15 s.</span>}
          <span className="grow" />
          <button className="primary" onClick={commit} data-testid="trim-done">
            {target.segmentId ? "Use this part" : "Add to timeline"}</button>
        </div>
        <p className="hint">Drag the handles or press I and O at the playhead. ← → step one frame (Shift: ten).</p>
      </div>
    </div>
  )
}
