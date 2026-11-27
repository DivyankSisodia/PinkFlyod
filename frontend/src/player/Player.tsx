// The 9:16 preview. One clock drives every source; each frame is drawn on a canvas from the resolved timeline:
// layers in their layout slots with the crop rectangles the export uses (model/geometry.ts), then the overlay and
// caption images the export burns in (/api/raster/<id>.png). Sound follows the same timeline: clip sound through
// WebAudio gain nodes, narration takes, music with its gate/duck envelope, and sound effects.
import { useCallback, useEffect, useRef, useState } from "react"
import { api, mediaUrl, rasterUrl, sfxUrl, takeUrl } from "../api"
import { even, place } from "../model/geometry"
import * as ops from "../model/ops"
import type { Project, Rect, ResolvedLayer, ResolvedScene, Timeline } from "../model/types"
import { useEditor } from "../state/editor"
import { clock } from "../ui/format"
import { eventGain, kenBurnsScale, layerTime, musicGain, musicOffset, sceneAt } from "./timing"

const VIEW_W = 540
const VIEW_H = 960
const PIP_ASPECTS: Record<string, number> = { "9:16": 16 / 9, "1:1": 1, "4:3": 3 / 4, "16:9": 9 / 16 }

interface Media { el: HTMLVideoElement | HTMLImageElement; gain?: GainNode; version: number }
type Slot = "primary" | "secondary"

declare global {
  interface Window { __preview?: { t: number; scene: string | null; layers: string[]; overlays: string[] } }
}

/** The slot rectangle as the current document says (so dragging a divider shows at once). Mirrors resolve._layout. */
function liveRect(ds: Project["scenes"][number], scene: ResolvedScene, layer: ResolvedLayer, W: number, H: number): Rect {
  const lay = ds.layout
  if (lay.type !== scene.layout.type) return layer.rect
  if (lay.type === "split" && lay.split) {
    const sp = lay.split
    const topH = Math.max(2, even(H * sp.divider - sp.gap_px / 2))
    const botY = Math.min(H - 2, even(H * sp.divider + sp.gap_px / 2))
    const top = { x: 0, y: 0, w: W, h: topH }
    const bottom = { x: 0, y: botY, w: W, h: H - botY }
    const primaryTop = sp.primary_position === "top"
    return (layer.slot === "primary") === primaryTop ? top : bottom
  }
  if (lay.type === "pip" && lay.pip && layer.slot === lay.pip.inset_layer && layer.source_size) {
    const p = lay.pip
    const w = Math.max(32, even(W * p.width))
    const ratio = PIP_ASPECTS[p.aspect] ?? layer.source_size.h / layer.source_size.w
    const h = Math.max(32, Math.min(even(H * 0.9), even(w * ratio)))
    return { x: even(p.x * (W - w)), y: even(p.y * (H - h)), w, h }
  }
  return layer.rect
}

/** The layer with the document's current framing, so a crop drag shows at once. */
function liveLayer(doc: Project | null, scene: ResolvedScene, layer: ResolvedLayer, W: number, H: number): ResolvedLayer {
  if (!doc) return layer
  const ds = doc.scenes.find((s) => s.id === scene.id)
  if (!ds) return layer
  const rect = liveRect(ds, scene, layer, W, H)
  const docLayer = ds.layers[layer.slot]
  if (!layer.source_size || !docLayer || (layer.kind !== "segment" && layer.kind !== "image")) return { ...layer, rect }
  const rf = docLayer.reframe
  const ss = layer.source_size
  const p = place(ss.w, ss.h, rect.w, rect.h, rf.mode, rf.focus.x, rf.focus.y, rf.zoom)
  const bg = rf.mode === "blur_fill" ? place(ss.w, ss.h, rect.w, rect.h, "fill", 0.5, 0.5, 1) : null
  return { ...layer, rect, mode: rf.mode, src: p.src, dst: p.dst, blur_background: bg }
}

const mediaKey = (sid: string, slot: Slot) => `${sid}|${slot}`

export function Player({ projectId }: { projectId: string }) {
  const doc = useEditor((s) => s.doc)
  const timeline = useEditor((s) => s.timeline)
  const playhead = useEditor((s) => s.playhead)
  const mediaVersion = useEditor((s) => s.mediaVersion)
  const { setPlayhead, apply, beginGesture, endGesture, select } = useEditor.getState()

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const holderRef = useRef<HTMLDivElement>(null)
  const media = useRef(new Map<string, Media>())
  const rasters = useRef(new Map<string, HTMLImageElement>())
  const buffers = useRef(new Map<string, AudioBuffer | "loading" | "failed">())
  const scheduled = useRef<AudioScheduledSourceNode[]>([])
  const musicNode = useRef<{ gain: GainNode } | null>(null)
  const audioCtx = useRef<AudioContext | null>(null)
  const tRef = useRef(0)
  const playingRef = useRef(false)
  const clockStart = useRef({ perf: 0, t: 0 })
  const lastStoreWrite = useRef(0)
  const docRef = useRef(doc)
  const tlRef = useRef(timeline)
  const scheduledFor = useRef<Timeline | null>(null)
  const drag = useRef<{ x: number; y: number; fx: number; fy: number; scene: string; slot: Slot; layer: ResolvedLayer } | null>(null)
  const [playing, setPlaying] = useState(false)
  const [showSafe, setShowSafe] = useState(true)
  const [exact, setExact] = useState<{ url: string; t: number } | null>(null)
  const [exactBusy, setExactBusy] = useState(false)
  const [exactError, setExactError] = useState<string | null>(null)
  const showSafeRef = useRef(showSafe)
  showSafeRef.current = showSafe
  docRef.current = doc
  tlRef.current = timeline

  // Keep one media element per (source, slot) the timeline uses, and load every overlay image and sound.
  useEffect(() => {
    if (!timeline || !holderRef.current) return
    const wanted = new Map<string, { sid: string; kind: string }>()
    for (const sc of timeline.scenes) {
      for (const l of sc.layers) {
        if (!l.source_id || (l.kind !== "segment" && l.kind !== "image")) continue
        wanted.set(l.kind === "image" ? l.source_id : mediaKey(l.source_id, l.slot), { sid: l.source_id, kind: l.kind })
      }
    }
    for (const [key, { sid, kind }] of wanted) {
      if (timeline.sources[sid]?.status !== "ok") continue     // missing or changed: nothing to load until relinked
      const version = mediaVersion[sid] ?? 0
      const existing = media.current.get(key)
      if (existing && existing.version === version) continue
      if (existing) {
        if (existing.el instanceof HTMLVideoElement) existing.el.src = mediaUrl(sid, "preview", String(version))
        existing.version = version
        continue
      }
      let el: HTMLVideoElement | HTMLImageElement
      if (kind === "image") {
        el = new Image()
        el.src = mediaUrl(sid, "original")
      } else {
        const v = document.createElement("video")
        v.preload = "auto"
        v.playsInline = true
        v.muted = true
        v.src = mediaUrl(sid, "preview", String(version))
        el = v
      }
      holderRef.current.appendChild(el)
      media.current.set(key, { el, version })
      if (audioCtx.current) attachGain(audioCtx.current, media.current.get(key)!)
    }
    const ids = new Set<string>([timeline.blank_raster])
    for (const o of timeline.overlays) ids.add(o.raster)
    for (const sc of timeline.scenes) {
      for (const o of sc.overlays) ids.add(o.raster)
      for (const l of sc.layers) {
        if (l.raster) ids.add(l.raster)
        if (l.pip?.border) ids.add(l.pip.border)
      }
    }
    for (const rid of ids) {
      if (rasters.current.has(rid)) continue
      const img = new Image()
      img.decoding = "async"
      img.src = rasterUrl(rid)
      rasters.current.set(rid, img)
    }
    const sounds: string[] = []
    for (const sc of timeline.scenes) {
      for (const a of sc.audio) if (a.track === "narration" && a.path) sounds.push(takeUrl(a.path))
      for (const s of sc.sfx) sounds.push(sfxUrl(s.sound))
    }
    if (timeline.music && timeline.sources[timeline.music.source_id]?.status === "ok") {
      sounds.push(mediaUrl(timeline.music.source_id, "original"))
    }
    for (const url of sounds) void loadBuffer(url)
    if (playingRef.current && scheduledFor.current !== timeline) scheduleSounds(tRef.current)
  }, [timeline, mediaVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadBuffer(url: string) {
    if (buffers.current.has(url)) return
    buffers.current.set(url, "loading")
    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(String(r.status))
      // Decoding needs no running audio context; an offline one avoids the autoplay warning before the first click.
      const buf = await new OfflineAudioContext(2, 1, 48000).decodeAudioData(await r.arrayBuffer())
      buffers.current.set(url, buf)
    } catch {
      buffers.current.set(url, "failed")
    }
  }

  useEffect(() => () => {
    for (const m of media.current.values()) {
      if (m.el instanceof HTMLVideoElement) { m.el.pause(); m.el.removeAttribute("src"); m.el.load() }
      m.el.remove()
    }
    media.current.clear()
    stopSounds()
    void audioCtx.current?.close()
    audioCtx.current = null
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // The playhead set elsewhere (a scene card, the scrubber) moves the clock when paused.
  useEffect(() => {
    if (!playingRef.current) tRef.current = playhead
  }, [playhead])

  function attachGain(ctx: AudioContext, m: Media) {
    if (!(m.el instanceof HTMLVideoElement) || m.gain) return
    const node = ctx.createMediaElementSource(m.el)
    m.gain = ctx.createGain()
    m.gain.gain.value = 0
    node.connect(m.gain).connect(ctx.destination)
    m.el.muted = false
  }

  const ensureAudio = useCallback(() => {
    if (!audioCtx.current) audioCtx.current = new AudioContext()
    const ctx = audioCtx.current
    void ctx.resume()
    for (const m of media.current.values()) attachGain(ctx, m)
    return ctx
  }, [])

  function stopSounds() {
    for (const n of scheduled.current) { try { n.stop() } catch { /* not started */ } }
    scheduled.current = []
    musicNode.current = null
    scheduledFor.current = null
  }

  /** Schedule narration, effects and music from timeline time ``t`` on. Called on play, seek and timeline change. */
  function scheduleSounds(t: number) {
    stopSounds()
    const tl = tlRef.current
    const ctx = audioCtx.current
    if (!tl || !ctx) return
    scheduledFor.current = tl
    const now = ctx.currentTime + 0.03
    const play = (buf: AudioBuffer, at: number, offset: number, length: number | undefined, gainValue: number) => {
      const src = ctx.createBufferSource()
      src.buffer = buf
      const g = ctx.createGain()
      g.gain.value = gainValue
      src.connect(g).connect(ctx.destination)
      src.start(now + Math.max(0, at - t), offset, length)
      scheduled.current.push(src)
      return { src, g }
    }
    for (const sc of tl.scenes) {
      for (const a of sc.audio) {
        if (a.track !== "narration" || !a.path) continue
        const buf = buffers.current.get(takeUrl(a.path))
        if (!(buf instanceof AudioBuffer)) continue
        const g0 = sc.start_s + a.start_s
        const end = g0 + a.read_s
        if (t >= end) continue
        const skip = Math.max(0, t - g0)
        play(buf, g0, skip, a.read_s - skip, Math.pow(10, a.gain_db / 20))
      }
      for (const s of sc.sfx) {
        const buf = buffers.current.get(sfxUrl(s.sound))
        if (!(buf instanceof AudioBuffer)) continue
        const at = sc.start_s + s.at_s
        if (t > at + buf.duration) continue
        play(buf, at, Math.max(0, t - at), undefined, Math.pow(10, s.gain_db / 20))
      }
    }
    const m = tl.music
    if (m) {
      const buf = buffers.current.get(mediaUrl(m.source_id, "original"))
      const off = musicOffset(m, t)
      if (buf instanceof AudioBuffer && off !== null) {
        const src = ctx.createBufferSource()
        src.buffer = buf
        src.loop = m.loop
        const g = ctx.createGain()
        g.gain.value = musicGain(m, t, tl.duration_s)
        src.connect(g).connect(ctx.destination)
        src.start(now, off)
        scheduled.current.push(src)
        musicNode.current = { gain: g }
      }
    }
  }

  const stop = useCallback(() => {
    playingRef.current = false
    setPlaying(false)
    for (const m of media.current.values()) if (m.el instanceof HTMLVideoElement) m.el.pause()
    stopSounds()
    setPlayhead(tRef.current)
  }, [setPlayhead]) // eslint-disable-line react-hooks/exhaustive-deps

  const play = useCallback(() => {
    const tl = tlRef.current
    if (!tl) return
    ensureAudio()
    if (tRef.current >= tl.duration_s - 1 / tl.output.fps) tRef.current = 0
    clockStart.current = { perf: performance.now(), t: tRef.current }
    playingRef.current = true
    setPlaying(true)
    scheduleSounds(tRef.current)
  }, [ensureAudio]) // eslint-disable-line react-hooks/exhaustive-deps

  // The render loop.
  useEffect(() => {
    let raf = 0
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      const tl = tlRef.current
      const canvas = canvasRef.current
      if (!tl || !canvas) return
      const ctx = canvas.getContext("2d")
      if (!ctx) return
      let t = tRef.current
      if (playingRef.current) {
        t = clockStart.current.t + (now - clockStart.current.perf) / 1000
        if (t >= tl.duration_s) { t = Math.max(0, tl.duration_s - 1 / tl.output.fps); tRef.current = t; stop() }
        tRef.current = t
        if (now - lastStoreWrite.current > 100) { lastStoreWrite.current = now; setPlayhead(t) }
        if (musicNode.current && tl.music) musicNode.current.gain.gain.value = musicGain(tl.music, t, tl.duration_s)
      }
      draw(ctx, tl, t)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [stop, setPlayhead]) // eslint-disable-line react-hooks/exhaustive-deps

  function drawRaster(ctx: CanvasRenderingContext2D, rid: string | null | undefined, x: number, y: number, w: number, h: number) {
    if (!rid) return false
    const img = rasters.current.get(rid)
    if (!img || !img.complete || !img.naturalWidth) return false
    ctx.drawImage(img, x, y, w, h)
    return true
  }

  function draw(ctx: CanvasRenderingContext2D, tl: Timeline, t: number) {
    const W = tl.output.width
    const H = tl.output.height
    const fps = tl.output.fps
    const k = VIEW_W / W
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.filter = "none"
    ctx.fillStyle = "#000"
    ctx.fillRect(0, 0, VIEW_W, VIEW_H)
    const scene = sceneAt(tl, t)
    const active = new Set<string>()
    const drawnLayers: string[] = []
    const drawnOverlays: string[] = []
    if (scene) {
      const local = t - scene.start_s
      ctx.fillStyle = scene.background_color
      ctx.fillRect(0, 0, VIEW_W, VIEW_H)
      if (scene.layout.gap) {
        const g = scene.layout.gap
        ctx.fillStyle = g.color
        ctx.fillRect(0, g.y * k, VIEW_W, g.h * k)
      }
      for (const raw of scene.layers) {
        const layer = liveLayer(docRef.current, scene, raw, W, H)
        const R = layer.rect
        const rx = R.x * k
        const ry = R.y * k
        const rw = R.w * k
        const rh = R.h * k
        ctx.save()
        ctx.beginPath()
        if (layer.pip && layer.pip.radius > 0) ctx.roundRect(rx, ry, rw, rh, layer.pip.radius * k)
        else ctx.rect(rx, ry, rw, rh)
        ctx.clip()
        if (layer.kind === "color") {
          ctx.fillStyle = layer.color ?? "#000"
          ctx.fillRect(rx, ry, rw, rh)
          drawnLayers.push(`${layer.slot}:color`)
        } else if (layer.kind === "text_card") {
          ctx.fillStyle = layer.color ?? "#000"
          ctx.fillRect(rx, ry, rw, rh)
          drawRaster(ctx, layer.raster, rx, ry, rw, rh)
          drawnLayers.push(`${layer.slot}:text_card`)
        } else if (layer.source_id && layer.src && layer.dst && layer.source_size) {
          const key = layer.kind === "image" ? layer.source_id : mediaKey(layer.source_id, layer.slot)
          const m = media.current.get(key)
          let ready = false
          let natW = 0
          let natH = 0
          let hidden = false
          if (m && m.el instanceof HTMLVideoElement) {
            const v = m.el
            active.add(key)
            const lt = layerTime(layer, local, fps)
            hidden = lt.hidden
            if (playingRef.current && !lt.inTail) {
              v.playbackRate = layer.speed ?? 1
              if (v.paused) { v.currentTime = lt.mediaT; void v.play().catch(() => undefined) }
              else if (Math.abs(v.currentTime - lt.mediaT) > 0.3) v.currentTime = lt.mediaT
            } else {
              if (!v.paused) v.pause()
              if (!v.seeking && Math.abs(v.currentTime - lt.mediaT) > 0.02) v.currentTime = lt.mediaT
            }
            const ev = scene.audio.find((a) => a.track === layer.slot && a.source_id === layer.source_id)
            if (m.gain) m.gain.gain.value = playingRef.current && ev ? eventGain(ev, local, scene.duration_s) : 0
            ready = v.readyState >= 2
            natW = v.videoWidth
            natH = v.videoHeight
          } else if (m) {
            const img = m.el as HTMLImageElement
            ready = img.complete && img.naturalWidth > 0
            natW = img.naturalWidth
            natH = img.naturalHeight
          }
          if (hidden) {
            ctx.fillStyle = scene.background_color
            ctx.fillRect(rx, ry, rw, rh)
          } else if (m && ready && natW) {
            const kx = natW / layer.source_size.w
            const ky = natH / layer.source_size.h
            let { src } = layer
            const { dst } = layer
            if (layer.mode === "fit" || (layer.mode === "fill" && (dst.w < R.w || dst.h < R.h))) {
              ctx.fillStyle = layer.bar_color
              ctx.fillRect(rx, ry, rw, rh)
            } else if (layer.mode === "blur_fill" && layer.blur_background) {
              const b = layer.blur_background.src
              ctx.filter = `blur(${Math.max(1, Math.round(24 * k))}px) brightness(0.94)`
              ctx.drawImage(m.el, b.x * kx, b.y * ky, b.w * kx, b.h * ky, rx - 20, ry - 20, rw + 40, rh + 40)
              ctx.filter = "none"
            }
            const z = layer.kind === "image" ? kenBurnsScale(layer, local, scene.duration_s) : 1
            if (z !== 1) {
              const cw = src.w / z
              const ch = src.h / z
              src = { x: src.x + (src.w - cw) / 2, y: src.y + (src.h - ch) / 2, w: cw, h: ch }
            }
            ctx.drawImage(m.el, src.x * kx, src.y * ky, src.w * kx, src.h * ky,
              rx + dst.x * k, ry + dst.y * k, dst.w * k, dst.h * k)
            drawnLayers.push(`${layer.slot}:${layer.kind}`)
          }
        }
        ctx.restore()
        if (layer.pip?.border && drawRaster(ctx, layer.pip.border, rx, ry, rw, rh)) drawnLayers.push(`${layer.slot}:pip_border`)
      }
      for (const o of scene.overlays) {
        if (local >= o.start_s && local < o.end_s && drawRaster(ctx, o.raster, 0, 0, VIEW_W, VIEW_H)) {
          drawnOverlays.push(o.kind)
        }
      }
    }
    for (const o of tl.overlays) {
      if (t >= o.start_s && t < o.end_s && drawRaster(ctx, o.raster, 0, 0, VIEW_W, VIEW_H)) drawnOverlays.push(o.kind)
    }
    for (const [key, m] of media.current) {
      if (!active.has(key) && m.el instanceof HTMLVideoElement && !m.el.paused) m.el.pause()
      if (!active.has(key) && m.gain) m.gain.gain.value = 0
    }
    window.__preview = { t, scene: scene?.id ?? null, layers: drawnLayers, overlays: drawnOverlays }
    if (showSafeRef.current) {
      const sa = tl.safe_area
      ctx.fillStyle = "rgba(0,0,0,0.28)"
      ctx.fillRect(0, 0, VIEW_W, sa.y * k)
      ctx.fillRect(0, (sa.y + sa.h) * k, VIEW_W, VIEW_H - (sa.y + sa.h) * k)
      ctx.fillRect((sa.x + sa.w) * k, sa.y * k, VIEW_W - (sa.x + sa.w) * k, sa.h * k)
      ctx.fillRect(0, sa.y * k, sa.x * k, sa.h * k)
      ctx.setLineDash([6, 5])
      ctx.strokeStyle = "rgba(255,255,255,0.7)"
      ctx.lineWidth = 1
      ctx.strokeRect(sa.x * k + 0.5, sa.y * k + 0.5, sa.w * k - 1, sa.h * k - 1)
      ctx.setLineDash([])
    }
  }

  // Drag the picture to move the crop of the layer under the pointer (the PiP inset sits on top).
  function onPointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    const tl = tlRef.current
    const d = docRef.current
    if (!tl || !d) return
    const scene = sceneAt(tl, tRef.current)
    if (!scene) return
    const box = e.currentTarget.getBoundingClientRect()
    const toOut = tl.output.width / box.width
    const px = (e.clientX - box.left) * toOut
    const py = (e.clientY - box.top) * toOut
    const ds = d.scenes.find((s) => s.id === scene.id)
    if (!ds) return
    select(scene.id)
    const hit = [...scene.layers].reverse()
      .map((l) => liveLayer(d, scene, l, tl.output.width, tl.output.height))
      .find((l) => px >= l.rect.x && px < l.rect.x + l.rect.w && py >= l.rect.y && py < l.rect.y + l.rect.h)
    if (!hit || !hit.source_size || !hit.src || !hit.dst) return
    const rf = ds.layers[hit.slot]?.reframe
    if (!rf) return
    useEditor.getState().selectLayer(hit.slot)
    drag.current = { x: e.clientX, y: e.clientY, fx: rf.focus.x, fy: rf.focus.y, scene: scene.id, slot: hit.slot, layer: hit }
    e.currentTarget.setPointerCapture(e.pointerId)
    beginGesture()
  }

  function onPointerMove(e: React.PointerEvent<HTMLCanvasElement>) {
    const g = drag.current
    const tl = tlRef.current
    if (!g || !tl || !g.layer.src || !g.layer.dst || !g.layer.source_size) return
    const rect = e.currentTarget.getBoundingClientRect()
    const toOut = tl.output.width / rect.width
    const dx = (e.clientX - g.x) * toOut
    const dy = (e.clientY - g.y) * toOut
    const { src, dst, source_size: ss } = g.layer
    const fx = g.fx - (dx / dst.w) * (src.w / ss.w)
    const fy = g.fy - (dy / dst.h) * (src.h / ss.h)
    apply((draft) => ops.setReframe(draft, g.scene, { x: fx, y: fy }, g.slot))
  }

  function onPointerUp() {
    if (!drag.current) return
    drag.current = null
    endGesture()
  }

  async function checkExactFrame() {
    if (!doc) return
    setExactBusy(true)
    setExactError(null)
    try {
      const blob = await api.exactFrame(projectId, doc, tRef.current)
      if (exact) URL.revokeObjectURL(exact.url)
      setExact({ url: URL.createObjectURL(blob), t: tRef.current })
    } catch (e) {
      setExactError((e as Error).message)
    } finally {
      setExactBusy(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.querySelector(".modal")) return
      if (e.code === "Space") { e.preventDefault(); playingRef.current ? stop() : play() }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [play, stop])

  const duration = timeline?.duration_s ?? 0
  const fps = timeline?.output.fps ?? 30
  const usedIds = new Set(timeline?.scenes.flatMap((s) => s.layers.map((l) => l.source_id)).filter(Boolean) ?? [])
  const missing = Object.entries(timeline?.sources ?? {})
    .filter(([id, s]) => usedIds.has(id) && s.status !== "ok").map(([, s]) => `“${s.display_name}”`)
  return (
    <div className="player">
      <div className="player-stage">
        <canvas ref={canvasRef} width={VIEW_W} height={VIEW_H} className="player-canvas" data-testid="preview-canvas"
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp} title="Drag to move the crop" />
        {exact && (
          <div className="exact">
            <div className="exact-head">
              <span>Exact frame from the export pipeline at {clock(exact.t)}</span>
              <button onClick={() => { URL.revokeObjectURL(exact.url); setExact(null) }}>Close</button>
            </div>
            <img src={exact.url} alt="Exact frame" data-testid="exact-frame" />
          </div>
        )}
        {!timeline && <div className="player-empty">Preparing preview…</div>}
        {missing.length > 0 && (
          <div className="player-empty missing" data-testid="preview-missing">
            {missing.join(", ")} {missing.length > 1 ? "are" : "is"} missing. Relink {missing.length > 1 ? "them" : "it"} in
            the Media panel to see the preview and export.
          </div>
        )}
      </div>
      <div className="player-controls">
        <button className="primary" onClick={() => (playing ? stop() : play())} disabled={!timeline} data-testid="play">
          {playing ? "Pause" : "Play"}
        </button>
        <input type="range" min={0} max={Math.max(duration, 0.001)} step={1 / fps} value={Math.min(playhead, duration)}
          onChange={(e) => {
            const t = Number(e.target.value); tRef.current = t; setPlayhead(t)
            if (playingRef.current) { clockStart.current = { perf: performance.now(), t }; scheduleSounds(t) }
          }}
          className="scrub" aria-label="Playhead" data-testid="scrub" />
        <span className="time">{clock(playhead)} / {clock(duration)}</span>
      </div>
      <div className="player-controls small">
        <label className="check"><input type="checkbox" checked={showSafe} onChange={(e) => setShowSafe(e.target.checked)}
          data-testid="safe-toggle" /> Shorts safe area</label>
        <button onClick={checkExactFrame} disabled={exactBusy || !doc} data-testid="exact-frame-button">
          {exactBusy ? "Rendering frame…" : "Check exact frame"}</button>
        {exactError && <span className="error-text">{exactError}</span>}
      </div>
      <div ref={holderRef} className="media-holder" aria-hidden />
    </div>
  )
}
