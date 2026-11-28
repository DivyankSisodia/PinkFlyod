// One scene's voice line: edit the text, then generate, record or import a take for this line only.
import { useEffect, useRef, useState } from "react"
import { api, takeUrl, type ProviderOption, type VoiceProvider } from "../../api"
import * as ops from "../../model/ops"
import type { Scene, VoiceOption } from "../../model/types"
import { useEditor } from "../../state/editor"
import { effectiveVoice, generateTake, loadVoices, sortVoices, speedUpTake, takeSpeed, takeState, uploadTake } from "../../state/narration"
import { Section, Slider, TextField, dbFmt, secFmt } from "./controls"

const STATE_LABEL = {
  none: "No line", missing: "No voice yet", ready: "Voice ready", stale: "Changed: regenerate", working: "Working…",
} as const

export function NarrationSection({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const job = useEditor((s) => s.takeJobs[scene.id])
  useEditor((s) => s.timeline)               // re-render when staleness is recomputed
  const { apply, select, setPlayhead } = useEditor.getState()
  const primarySeg = ops.primarySegment(doc, scene)
  const primarySrc = primarySeg ? doc.sources[primarySeg.seg.source_id] : null
  const isVideoScene = primarySrc?.kind === "video"
  const [recording, setRecording] = useState<{ rec: MediaRecorder; started: number } | null>(null)
  const [recError, setRecError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [voices, setVoices] = useState<{ online: boolean; voices: VoiceOption[] } | null>(null)
  const [models, setModels] = useState<ProviderOption[]>([])
  const [voiceError, setVoiceError] = useState("")
  const [switchingVoice, setSwitchingVoice] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const n = scene.narration
  const state = takeState(scene.id)
  const voice = effectiveVoice(doc, scene.id)
  const provider = voice.provider === "edge" || voice.provider === "system" || voice.provider === "elevenlabs"
    ? voice.provider : null

  useEffect(() => {
    if (!provider) return
    let live = true
    setVoices(null)
    setVoiceError("")
    void loadVoices(provider).then((v) => { if (live) setVoices(v) })
      .catch((e) => { if (live) setVoiceError((e as Error).message) })
    if (provider === "elevenlabs") {
      void api.providerOptions("elevenlabs").then((r) => { if (live) setModels(r.options) })
        .catch(() => { if (live) setModels([]) })
    }
    return () => { live = false }
  }, [provider])

  const voiceList = sortVoices(voices?.voices ?? [], doc.audience.language)

  async function chooseSceneVoice(next: VoiceProvider | "project") {
    setVoiceError("")
    if (next === "project") {
      apply((d) => ops.setSceneVoice(d, scene.id, null))
      return
    }
    if (next !== "elevenlabs") {
      apply((d) => ops.setSceneVoice(d, scene.id, {
        provider: next,
        voice_id: next === "edge" ? (d.audience.country === "CA" ? "en-CA-LiamNeural" : "en-US-AndrewNeural") : "",
      }))
      return
    }
    setSwitchingVoice(true)
    try {
      const defaults = await api.providers()
      apply((d) => ops.setSceneVoice(d, scene.id, {
        provider: "elevenlabs",
        voice_id: defaults.elevenlabs_voice,
        model_id: defaults.elevenlabs_model,
        rate_pct: Math.max(-30, Math.min(100, voice.rate_pct)),
      }))
    } catch (e) {
      setVoiceError((e as Error).message)
    } finally {
      setSwitchingVoice(false)
    }
  }

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
      {isVideoScene && scene.duration.driver !== "narration" && (
        <div className="subgroup">
          <div className="hint">
            Avoid audio clash: play this voiceover over a muted random clip from the video first, then start the video with its own sound.
          </div>
          <button
            className="primary"
            disabled={busy}
            data-testid="split-voiceover-intro"
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
      {isVideoScene && scene.duration.driver === "narration" && (
        <div className="subgroup">
          <div className="hint">
            Playing a muted clip until the voiceover ends. Don&apos;t like this moment?
          </div>
          <button
            disabled={busy}
            data-testid="shuffle-voiceover-clip"
            onClick={() => apply((d) => { ops.shuffleSceneClip(d, scene.id) })}
          >
            Shuffle random clip
          </button>
        </div>
      )}
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
        <>
          <div className="hint" data-testid="take-facts">
            {n.take.method === "tts" ? `${n.take.provider} · ${n.take.voice_id || "default voice"}` : n.take.method} ·
            {" "}{n.take.duration_s.toFixed(2)} s · word timing {n.take.timing}
          </div>
          <div className="subgroup">
            <div className="hint">Playback speed (always stretches from the 1.0× original):</div>
            <div className="seg-buttons">
              {[1, 1.15, 1.25, 1.5].map((spd) => (
                <button key={spd} disabled={busy} data-testid={`speed-take-${spd}`}
                  className={Math.abs(takeSpeed(n.take?.id) - spd) < 0.01 ? "on" : ""}
                  onClick={() => void speedUpTake(scene.id, spd)}>
                  {spd === 1 ? "1.0×" : `${spd}×`}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
      <div className="subgroup" data-testid="scene-voice-controls">
        <label className="slider"><span>Agent</span>
          <select value={n.voice ? (provider ?? "edge") : "project"} disabled={busy || switchingVoice}
            data-testid="scene-voice-provider"
            onChange={(e) => void chooseSceneVoice(e.target.value as VoiceProvider | "project")}>
            <option value="project">Project default ({doc.voice.provider === "none" ? "not set" : doc.voice.provider})</option>
            <option value="edge">Edge voices (free, online)</option>
            <option value="system">This computer's voice (offline)</option>
            <option value="elevenlabs">ElevenLabs</option>
          </select>
        </label>
        {provider && (
          <label className="slider"><span>Speaker</span>
            <select value={voice.voice_id} disabled={busy} data-testid="scene-voice-id"
              onChange={(e) => apply((d) => ops.setSceneVoice(d, scene.id, { voice_id: e.target.value }))}>
              {provider === "system" && <option value="">default</option>}
              {provider === "elevenlabs" && <option value="">Choose a speaker</option>}
              {voice.voice_id && !voiceList.some((v) => v.id === voice.voice_id) &&
                <option value={voice.voice_id}>{voice.voice_id}</option>}
              {voiceList.map((v) => <option key={v.id} value={v.id}>{v.name}{v.locale && ` (${v.locale}${v.gender ? `, ${v.gender}` : ""})`}</option>)}
            </select>
          </label>
        )}
        {provider === "elevenlabs" && (
          <label className="slider"><span>Model</span>
            <select value={voice.model_id ?? ""} disabled={busy} data-testid="scene-elevenlabs-model"
              onChange={(e) => apply((d) => ops.setSceneVoice(d, scene.id, { model_id: e.target.value }))}>
              {!voice.model_id && <option value="">Choose a model</option>}
              {voice.model_id && !models.some((m) => m.id === voice.model_id) &&
                <option value={voice.model_id}>{voice.model_id}</option>}
              {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
        )}
        {provider && (
          <Slider label="Pace" value={voice.rate_pct} min={-30} max={provider === "elevenlabs" ? 100 : 50} step={5}
            testid="scene-voice-pace" fmt={(v) => `${v > 0 ? "+" : ""}${v}%`}
            onChange={(v) => apply((d) => ops.setSceneVoice(d, scene.id, { rate_pct: v }))} />
        )}
        {voiceError && <div className="error-text" role="status">{voiceError}</div>}
        {provider === "edge" && voices && !voices.online && (
          <div className="hint">Offline: showing built-in Edge list.</div>
        )}
      </div>
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
