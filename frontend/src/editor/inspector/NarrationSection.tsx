// One scene's voice line: edit the text, then generate, record or import a take for this line only.
import { useEffect, useRef, useState } from "react"
import { takeUrl } from "../../api"
import * as ops from "../../model/ops"
import type { Scene } from "../../model/types"
import { useEditor } from "../../state/editor"
import { effectiveVoice, generateTake, takeState, uploadTake } from "../../state/narration"
import { Section, Slider, TextField, dbFmt, secFmt } from "./controls"

const STATE_LABEL = {
  none: "No line", missing: "No voice yet", ready: "Voice ready", stale: "Line changed: regenerate", working: "Working…",
} as const

export function NarrationSection({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const job = useEditor((s) => s.takeJobs[scene.id])
  useEditor((s) => s.timeline)               // re-render when staleness is recomputed
  const { apply } = useEditor.getState()
  const [recording, setRecording] = useState<{ rec: MediaRecorder; started: number } | null>(null)
  const [recError, setRecError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const n = scene.narration
  const state = takeState(scene.id)
  const voice = effectiveVoice(doc, scene.id)

  useEffect(() => {
    if (!recording) return
    const id = setInterval(() => setElapsed((performance.now() - recording.started) / 1000), 200)
    return () => clearInterval(id)
  }, [recording])

  useEffect(() => () => { audioRef.current?.pause() }, [])

  async function startRecording() {
    setRecError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" })
        const ext = (rec.mimeType || "").includes("ogg") ? "ogg" : (rec.mimeType || "").includes("mp4") ? "m4a" : "webm"
        void uploadTake(scene.id, blob, `recording.${ext}`, "recorded")
      }
      rec.start()
      setRecording({ rec, started: performance.now() })
      setElapsed(0)
    } catch (e) {
      setRecError(`The microphone isn't available: ${(e as Error).message}`)
    }
  }

  function stopRecording() {
    recording?.rec.stop()
    setRecording(null)
  }

  function playTake() {
    if (!n?.take) return
    audioRef.current?.pause()
    const a = new Audio(takeUrl(n.take.audio_path))
    audioRef.current = a
    void a.play()
  }

  if (!n) {
    return (
      <Section title="Voice" testid="narration-section">
        <p className="hint">No voice line in this scene.</p>
        <button onClick={() => apply((d) => ops.setNarrationText(d, scene.id, scene.name))} data-testid="add-narration">
          + Add a voice line</button>
      </Section>
    )
  }
  const busy = state === "working" || !!recording
  return (
    <Section title="Voice" testid="narration-section"
      extra={<span className={`take-state ${state}`} data-testid="take-state">{STATE_LABEL[state]}</span>}>
      <TextField multiline value={n.text} label="Voice line" testid="narration-text" maxLength={600}
        placeholder="What the voice says in this scene" onCommit={(v) => apply((d) => ops.setNarrationText(d, scene.id, v))} />
      <div className="hint">Ctrl+Enter or click away to apply. Only this line's voice is redone.</div>
      <div className="row wrap">
        <button className={state === "stale" || state === "missing" ? "primary" : ""} disabled={busy || !n.text.trim()}
          onClick={() => void generateTake(scene.id)} data-testid="generate-take"
          title={`${voice.provider === "elevenlabs" ? "ElevenLabs" : voice.provider === "edge" ? "Edge voice (online)" : voice.provider === "system" ? "System voice (offline)" : "No voice chosen"}: ${voice.voice_id || "default"}`}>
          {state === "ready" || state === "stale" ? "Regenerate" : "Generate"} voice</button>
        {!recording ? (
          <button onClick={() => void startRecording()} disabled={busy || !n.text.trim()} data-testid="record-take">● Record</button>
        ) : (
          <button className="danger" onClick={stopRecording} data-testid="stop-record">■ Stop ({elapsed.toFixed(1)} s)</button>
        )}
        <button onClick={() => fileRef.current?.click()} disabled={busy || !n.text.trim()} data-testid="import-take">Import…</button>
        <input ref={fileRef} type="file" hidden accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm,.flac" data-testid="take-file"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadTake(scene.id, f, f.name, "imported"); e.target.value = "" }} />
        {n.take && <button onClick={playTake} data-testid="play-take">▶ Hear it</button>}
      </div>
      {job?.error && <p className="error-text" data-testid="take-error">{job.error}</p>}
      {job && !job.error && <p className="hint">{job.stage || "Working"}…</p>}
      {recError && <p className="error-text">{recError}</p>}
      {n.take && (
        <div className="hint" data-testid="take-facts">
          {n.take.method === "tts" ? `${n.take.provider} · ${n.take.voice_id || "default voice"}` : n.take.method} ·
          {" "}{n.take.duration_s.toFixed(2)} s · word timing {n.take.timing}
        </div>
      )}
      <Slider label="Starts after" value={n.offset_s} min={0} max={3} step={0.05} fmt={secFmt}
        onChange={(v) => apply((d) => ops.setNarrationOffset(d, scene.id, v))} />
      <label className="check">
        <input type="checkbox" checked={scene.audio.narration.enabled} data-testid="narration-toggle"
          onChange={(e) => apply((d) => ops.setMix(d, scene.id, "narration", { enabled: e.target.checked }))} />
        Voice on
      </label>
      {scene.audio.narration.enabled && (
        <Slider label="Volume" value={scene.audio.narration.gain_db} min={-24} max={6} step={0.5} fmt={dbFmt}
          onChange={(v) => apply((d) => ops.setMix(d, scene.id, "narration", { gain_db: v }))} />
      )}
      <button onClick={() => apply((d) => ops.removeNarration(d, scene.id))} data-testid="remove-narration">Remove voice line</button>
    </Section>
  )
}
