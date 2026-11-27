// A scene's sound: each layer's own sound, the voice, whether music plays here, and sound effects.
import { useRef } from "react"
import { sfxUrl } from "../../api"
import * as ops from "../../model/ops"
import type { Scene } from "../../model/types"
import { useEditor } from "../../state/editor"
import { Section, Slider, dbFmt, secFmt } from "./controls"

const SOUND_LABEL: Record<string, string> = {
  whoosh: "Whoosh", pop: "Pop", hit: "Hit", ding: "Ding", boing: "Boing", record_scratch: "Record scratch",
}

export function SoundSection({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const timeline = useEditor((s) => s.timeline)
  const playhead = useEditor((s) => s.playhead)
  const { apply } = useEditor.getState()
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const resolved = timeline?.scenes.find((s) => s.id === scene.id)
  const local = resolved ? Math.min(resolved.duration_s, Math.max(0, playhead - resolved.start_s)) : 0

  const track = (slot: "primary" | "secondary", label: string, testPrefix: string) => {
    const seg = ops.segmentOf(doc, scene, slot)
    if (!seg) return null
    const hasAudio = doc.sources[seg.seg.source_id]?.fingerprint.has_audio
    const mix = scene.audio[slot]
    if (!hasAudio) return <div className="hint" key={slot}>{label}: the clip has no sound.</div>
    return (
      <div key={slot} className="track">
        <label className="check">
          <input type="checkbox" checked={mix.enabled} data-testid={testPrefix === "" ? "audio-toggle" : `${testPrefix}audio-toggle`}
            onChange={(e) => apply((d) => ops.setMix(d, scene.id, slot, { enabled: e.target.checked }))} />
          {label}
        </label>
        {mix.enabled && (
          <>
            <Slider label="Volume" value={mix.gain_db} min={-36} max={6} step={0.5} fmt={dbFmt}
              testid={testPrefix === "" ? "gain" : `${testPrefix}gain`}
              onChange={(v) => apply((d) => ops.setMix(d, scene.id, slot, { gain_db: v }))} />
            {scene.narration && (
              <label className="check small">
                <input type="checkbox" checked={mix.duck_under_narration} data-testid={`${testPrefix || "primary-"}duck`}
                  onChange={(e) => apply((d) => ops.setMix(d, scene.id, slot, { duck_under_narration: e.target.checked }))} />
                Dip under the voice
              </label>
            )}
          </>
        )}
      </div>
    )
  }

  function preview(sound: string) {
    audioRef.current?.pause()
    const a = new Audio(sfxUrl(sound))
    audioRef.current = a
    void a.play()
  }

  return (
    <Section title="Sound" testid="sound-section">
      {track("primary", scene.layers.secondary ? "Main layer's own sound" : "Original sound", "")}
      {scene.layers.secondary && track("secondary", "Second layer's own sound", "secondary-")}
      {doc.audio.music && (
        <label className="check">
          <input type="checkbox" checked={scene.audio.music.enabled} data-testid="scene-music"
            onChange={(e) => apply((d) => ops.setSceneMusic(d, scene.id, e.target.checked))} />
          Music in this scene
        </label>
      )}
      <div className="row">
        <button onClick={() => apply((d) => ops.muteScene(d, scene.id))} data-testid="mute-scene">Mute this scene</button>
      </div>
      <div className="subhead">Sound effects</div>
      {scene.sfx.map((s) => (
        <div key={s.id} className="subgroup" data-testid="sfx">
          <div className="row between">
            <select value={s.sound} aria-label="Sound"
              onChange={(e) => apply((d) => ops.setSfx(d, scene.id, s.id, { sound: e.target.value }))}>
              {ops.SOUNDS.map((n) => <option key={n} value={n}>{SOUND_LABEL[n]}</option>)}
            </select>
            <button onClick={() => preview(s.sound)} title="Hear it">▶</button>
            <button onClick={() => apply((d) => ops.removeSfx(d, scene.id, s.id))} title="Remove">✕</button>
          </div>
          <Slider label="At" value={s.at_s} min={0} max={Math.max(resolved?.duration_s ?? 1, s.at_s)} step={0.05} fmt={secFmt}
            onChange={(v) => apply((d) => ops.setSfx(d, scene.id, s.id, { at_s: v }))} />
          <Slider label="Volume" value={s.gain_db} min={-30} max={6} step={1} fmt={dbFmt}
            onChange={(v) => apply((d) => ops.setSfx(d, scene.id, s.id, { gain_db: v }))} />
        </div>
      ))}
      <button onClick={() => apply((d) => ops.addSfx(d, scene.id, local))} data-testid="add-sfx">+ Effect at the playhead</button>
    </Section>
  )
}
