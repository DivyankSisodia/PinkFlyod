// Settings for the whole video: length cap, audience, ranking, captions style, music and ducking, title bar,
// hook, watermark and the narration voice.
import { useEffect, useState } from "react"
import { api, type ProviderOption, type VoiceProvider } from "../../api"
import * as ops from "../../model/ops"
import type { VoiceOption } from "../../model/types"
import { useEditor } from "../../state/editor"
import { generateAllNeeded, loadVoices, sortVoices, takeState } from "../../state/narration"
import { Choice, Section, Slider, TextField, dbFmt, secFmt } from "./controls"

export function ProjectSection() {
  const doc = useEditor((s) => s.doc)!
  const projectId = useEditor((s) => s.projectId)
  const { apply } = useEditor.getState()
  const [voices, setVoices] = useState<{ online: boolean; voices: VoiceOption[] } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [voiceError, setVoiceError] = useState("")
  const [models, setModels] = useState<ProviderOption[]>([])
  const [switchingVoice, setSwitchingVoice] = useState(false)
  const provider = doc.voice.provider === "edge" || doc.voice.provider === "system" || doc.voice.provider === "elevenlabs"
    ? doc.voice.provider : null
  const narrated = doc.scenes.filter((s) => s.narration)
  const needing = narrated.filter((s) => ["missing", "stale"].includes(takeState(s.id))).length
  useEditor((s) => s.timeline)
  useEditor((s) => s.takeJobs)

  useEffect(() => {
    if (!provider) return
    let live = true
    setVoices(null)
    setVoiceError("")
    void loadVoices(provider).then((v) => { if (live) setVoices(v) })
      .catch((error) => { if (live) setVoiceError(error.message) })
    if (provider === "elevenlabs") void api.providerOptions("elevenlabs").then((r) => { if (live) setModels(r.options) })
      .catch(() => { if (live) setModels([]) })
    return () => { live = false }
  }, [provider])

  const locale = doc.audience.language
  const voiceList = sortVoices(voices?.voices ?? [], locale)
  const overriddenCount = doc.scenes.filter((s) => s.narration?.voice).length

  async function chooseVoice(next: VoiceProvider) {
    setVoiceError("")
    if (next !== "elevenlabs") {
      apply((d) => ops.setVoice(d, { provider: next,
        voice_id: next === "edge" ? (d.audience.country === "CA" ? "en-CA-LiamNeural" : "en-US-AndrewNeural") : "" }))
      return
    }
    setSwitchingVoice(true)
    try {
      const defaults = await api.providers()
      if (useEditor.getState().projectId !== projectId) return
      apply((d) => ops.setVoice(d, { provider: next, voice_id: defaults.elevenlabs_voice,
        model_id: defaults.elevenlabs_model, rate_pct: Math.max(-30, Math.min(20, d.voice.rate_pct)) }))
    } catch (error) { setVoiceError((error as Error).message) }
    finally { setSwitchingVoice(false) }
  }

  async function sampleMusic() {
    if (!projectId) return
    setBusy("Making a music loop…")
    setMessage(null)
    try {
      const r = await api.sampleMusic(projectId)
      const [sid] = Object.keys(r.sources)
      apply((d) => { ops.addSources(d, r.sources); ops.setMusic(d, sid) })
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function generateAll() {
    setBusy("Making voices…")
    try { await generateAllNeeded() } finally { setBusy(null) }
  }

  const audioSources = Object.entries(doc.sources).filter(([, s]) => s.kind === "audio" || (s.kind === "video" && s.fingerprint.has_audio))
  const m = doc.audio.music
  const r = doc.ranking
  const c = doc.captions
  return (
    <>
      <Section title="Project" testid="project-section">
        <label className="check">
          <input type="checkbox" checked={doc.output.max_duration_s !== null} data-testid="cap-toggle"
            onChange={(e) => apply((d) => ops.setCap(d, e.target.checked ? ops.QUICK_SHORT_CAP_S : null))} />
          Keep it under {ops.QUICK_SHORT_CAP_S} s (Quick Short)
        </label>
        <label className="slider"><span>Audience</span>
          <select value={doc.audience.country} data-testid="audience"
            onChange={(e) => apply((d) => ops.setAudienceCountry(d, e.target.value as "US" | "CA" | "BOTH"))}>
            <option value="US">United States</option><option value="CA">Canada</option><option value="BOTH">Both</option>
          </select>
        </label>
        <div className="hint">{doc.output.width}×{doc.output.height} · {doc.output.fps} fps · H.264 + AAC ·
          sound normalised to {doc.output.audio.loudness.target_lufs} LUFS</div>
      </Section>

      <Section title="Ranking" testid="ranking-section" open={r.enabled}>
        <label className="check">
          <input type="checkbox" checked={r.enabled} data-testid="ranking-toggle"
            onChange={(e) => apply((d) => ops.setRanking(d, { enabled: e.target.checked }))} />
          Number the entries (a countdown)
        </label>
        {r.enabled && (
          <>
            <Choice label="Order" value={r.direction} testid="direction"
              options={[{ value: "descending", label: "Countdown (N → 1)" }, { value: "ascending", label: "Count up (1 → N)" }] as const}
              onChange={(v) => apply((d) => ops.setRanking(d, { direction: v }))} />
            <label className="slider"><span>Badge</span>
              <select value={r.badge.position} data-testid="badge-position"
                onChange={(e) => apply((d) => ops.setRanking(d, { position: e.target.value as "top_left" }))}>
                <option value="top_left">top left</option><option value="top_center">top centre</option>
                <option value="top_right">top right</option>
              </select>
              <select value={r.reveal} aria-label="Reveal" data-testid="reveal"
                onChange={(e) => apply((d) => ops.setRanking(d, { reveal: e.target.value as "current_only" }))}>
                <option value="current_only">one badge</option><option value="list_build_up">list that fills in</option>
              </select>
            </label>
            <div className="hint">Numbers follow the scene order; drag scenes in the timeline to re-rank.</div>
          </>
        )}
      </Section>

      <Section title="Voice" testid="voice-section" open={narrated.length > 0}>
        <label className="slider"><span>Voice</span>
          <select value={provider ?? ""} data-testid="voice-provider" disabled={switchingVoice}
            onChange={(e) => void chooseVoice(e.target.value as VoiceProvider)}>
            {!provider && <option value="" disabled>Choose a provider</option>}
            <option value="edge">Edge voices (free, online)</option>
            <option value="system">This computer's voice (offline)</option>
            <option value="elevenlabs">ElevenLabs</option>
          </select>
        </label>
        {provider && (
          <label className="slider"><span>Speaker</span>
            <select value={doc.voice.voice_id} data-testid="voice-id"
              onChange={(e) => apply((d) => ops.setVoice(d, { voice_id: e.target.value }))}>
              {provider === "system" && <option value="">default</option>}
              {provider === "elevenlabs" && <option value="">Choose a speaker</option>}
              {doc.voice.voice_id && !voiceList.some((v) => v.id === doc.voice.voice_id) &&
                <option value={doc.voice.voice_id}>{doc.voice.voice_id}</option>}
              {voiceList.map((v) => <option key={v.id} value={v.id}>{v.name}{v.locale && ` (${v.locale}${v.gender ? `, ${v.gender}` : ""})`}</option>)}
            </select>
          </label>
        )}
        {provider === "elevenlabs" && <>
          <label className="slider"><span>Voice model</span>
            <select value={doc.voice.model_id ?? ""} data-testid="elevenlabs-model"
              onChange={(e) => apply((d) => ops.setVoice(d, { model_id: e.target.value }))}>
              {!doc.voice.model_id && <option value="">Choose a model</option>}
              {doc.voice.model_id && !models.some((m) => m.id === doc.voice.model_id) &&
                <option value={doc.voice.model_id}>{doc.voice.model_id}</option>}
              {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <a href="#/settings" target="_blank" rel="noopener" className="hint">AI settings</a>
        </>}
        {voiceError && <div className="error-text" role="status">{voiceError}</div>}
        {provider === "edge" && voices && !voices.online && (
          <div className="hint">Offline: showing a built-in list. Edge voices need internet; the computer's voice works offline.</div>
        )}
        <Slider label="Pace" value={doc.voice.rate_pct} min={-30} max={provider === "elevenlabs" ? 100 : 50} step={5} fmt={(v) => `${v > 0 ? "+" : ""}${v}%`}
          onChange={(v) => apply((d) => ops.setVoice(d, { rate_pct: v }))} />
        {overriddenCount > 0 && (
          <button
            disabled={!!busy}
            data-testid="apply-project-voice-all"
            onClick={() => apply((d) => ops.clearSceneVoiceOverrides(d))}
          >
            Use this voice for all {overriddenCount} custom scene{overriddenCount > 1 ? "s" : ""}
          </button>
        )}
        {narrated.length > 0 && (
          <button className={needing ? "primary" : ""} disabled={!needing || !!busy} onClick={() => void generateAll()}
            data-testid="generate-all">{needing ? `Make ${needing} missing or changed voice${needing > 1 ? "s" : ""}` : "All voices ready"}</button>
        )}
        <div className="hint">Changing the voice marks generated takes as changed; recordings are kept.</div>
      </Section>

      <Section title="Captions style" testid="caption-style-section" open={c.enabled}>
        <label className="check">
          <input type="checkbox" checked={c.enabled} data-testid="captions-toggle"
            onChange={(e) => apply((d) => ops.setCaptions(d, { enabled: e.target.checked }))} />
          Captions
        </label>
        {c.enabled && (
          <>
            <label className="slider"><span>Style</span>
              <select value={c.style.preset} data-testid="caption-preset"
                onChange={(e) => apply((d) => ops.setCaptions(d, { preset: e.target.value as "bold" }))}>
                <option value="bold">bold, highlighted word</option><option value="boxed">boxed</option>
                <option value="karaoke">karaoke</option><option value="clean">clean</option><option value="minimal">minimal</option>
              </select>
            </label>
            <Slider label="Size" value={c.style.text.font_size_px} min={40} max={140} step={2} fmt={(v) => `${v} px`}
              onChange={(v) => apply((d) => ops.setCaptions(d, { size: v }))} />
            <Slider label="Height" value={c.anchor_y} min={0} max={1} step={0.01} testid="caption-y"
              fmt={(v) => `${Math.round(v * 100)}%`} onChange={(v) => apply((d) => ops.setCaptions(d, { anchor_y: v }))} />
            <Slider label="Words at once" value={c.style.max_words} min={1} max={6} step={1} fmt={(v) => String(v)}
              onChange={(v) => apply((d) => ops.setCaptions(d, { max_words: v }))} />
            <div className="hint">Captions always stay inside the Shorts safe area.</div>
          </>
        )}
      </Section>

      <Section title="Music" testid="music-section">
        {m ? (
          <>
            <div className="row between"><span>{doc.sources[m.source_id]?.display_name}</span>
              <button onClick={() => apply((d) => ops.setMusic(d, null))} data-testid="remove-music">Remove</button></div>
            <label className="check">
              <input type="checkbox" checked={m.enabled} data-testid="music-toggle"
                onChange={(e) => apply((d) => ops.setMusicFields(d, { enabled: e.target.checked }))} />Music on
            </label>
            <Slider label="Volume" value={m.gain_db} min={-36} max={0} step={1} fmt={dbFmt} testid="music-gain"
              onChange={(v) => apply((d) => ops.setMusicFields(d, { gain_db: v }))} />
            <label className="check">
              <input type="checkbox" checked={m.loop} onChange={(e) => apply((d) => ops.setMusicFields(d, { loop: e.target.checked }))} />
              Loop
            </label>
            <div className="hint">Choose which scenes have music in each scene's Sound section.</div>
          </>
        ) : (
          <div className="row wrap">
            <button onClick={() => void sampleMusic()} disabled={!!busy} data-testid="sample-music">+ Sample music loop</button>
            {audioSources.length > 0 && (
              <select value="" aria-label="Use a file as music" data-testid="music-source"
                onChange={(e) => e.target.value && apply((d) => ops.setMusic(d, e.target.value))}>
                <option value="">Use a file from Media…</option>
                {audioSources.map(([id, s]) => <option key={id} value={id}>{s.display_name}</option>)}
              </select>
            )}
          </div>
        )}
        <label className="check">
          <input type="checkbox" checked={doc.audio.ducking.enabled} data-testid="ducking-toggle"
            onChange={(e) => apply((d) => ops.setDucking(d, { enabled: e.target.checked }))} />
          Dip the music under the voice
        </label>
        {doc.audio.ducking.enabled && (
          <Slider label="Dip by" value={doc.audio.ducking.depth_db} min={-30} max={0} step={1} fmt={dbFmt} testid="duck-depth"
            onChange={(v) => apply((d) => ops.setDucking(d, { depth_db: v }))} />
        )}
      </Section>

      <Section title="Titles" testid="titles-section" open={!!(doc.overlays.title_bar || doc.overlays.hook)}>
        <TextField value={doc.overlays.title_bar?.text ?? ""} label="Title bar" placeholder="Title bar (stays on screen)"
          testid="title-bar" maxLength={80} onCommit={(v) => apply((d) => ops.setTitleBar(d, v))} />
        <TextField value={doc.overlays.hook?.text ?? ""} label="Opening hook" placeholder="Opening hook (first seconds)"
          testid="hook" maxLength={80} onCommit={(v) => apply((d) => ops.setHook(d, v))} />
        {doc.overlays.hook && (
          <Slider label="Hook for" value={doc.overlays.hook.duration_s} min={0.5} max={6} step={0.1} fmt={secFmt}
            onChange={(v) => apply((d) => ops.setHook(d, doc.overlays.hook!.text, v))} />
        )}
        <TextField value={doc.overlays.watermark?.text ?? ""} label="Watermark" placeholder="Watermark (e.g. @yourchannel)"
          testid="watermark" maxLength={40} onCommit={(v) => apply((d) => ops.setWatermark(d, v))} />
      </Section>
      {busy && <p className="hint">{busy}</p>}
      {message && <p className="error-text">{message}</p>}
    </>
  )
}
