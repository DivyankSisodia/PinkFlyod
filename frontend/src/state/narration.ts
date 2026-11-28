// Voice takes: generate, record or import one line's take, then attach it to that scene only. Jobs live outside
// any component, so switching scenes while a voice is being made doesn't lose it.
import { api, type VoiceProvider } from "../api"
import { waitJob } from "../events"
import * as ops from "../model/ops"
import type { Project, Take, VoiceOption } from "../model/types"
import { useEditor } from "./editor"

const voiceCache: Partial<Record<"edge" | "system", Promise<{ online: boolean; voices: VoiceOption[] }>>> = {}

export function loadVoices(provider: VoiceProvider) {
  if (provider === "elevenlabs") return api.voices(provider)
  voiceCache[provider] ??= api.voices(provider).catch(() => ({ online: false, voices: [] }))
  return voiceCache[provider]!
}

export function sortVoices(voices: VoiceOption[], locale: string): VoiceOption[] {
  return voices.slice().sort((a, b) =>
    Number(b.locale === locale) - Number(a.locale === locale) || a.name.localeCompare(b.name))
}

export type TakeState = "none" | "missing" | "ready" | "stale" | "working"

/** The take state shown for a scene: from the resolved timeline (which compares text and voice hashes). */
export function takeState(sceneId: string): TakeState {
  const s = useEditor.getState()
  if (s.takeJobs[sceneId] && !s.takeJobs[sceneId].error) return "working"
  const scene = s.doc?.scenes.find((x) => x.id === sceneId)
  if (!scene?.narration || !scene.narration.text.trim()) return "none"
  if (!scene.narration.take) return "missing"
  const issue = s.timeline?.issues.find((i) => i.scene_id === sceneId && i.code === "voice_stale")
  const r = s.timeline?.scenes.find((x) => x.id === sceneId)?.narration
  return issue || r?.state === "stale" ? "stale" : "ready"
}

export function effectiveVoice(doc: Project, sceneId: string) {
  const scene = doc.scenes.find((s) => s.id === sceneId)
  return scene?.narration?.voice ?? doc.voice
}

function attach(sceneId: string, take: Take) {
  useEditor.getState().apply((d) => ops.attachTake(d, sceneId, take))
}

/** Make a voice for one line with the scene's effective voice. Only this scene's take changes. */
export async function generateTake(sceneId: string): Promise<void> {
  const s = useEditor.getState()
  const doc = s.doc
  const scene = doc?.scenes.find((x) => x.id === sceneId)
  if (!doc || !s.projectId || !scene?.narration) return
  const isCurrent = () => {
    const current = useEditor.getState()
    return current.projectId === s.projectId && current.doc?.scenes.some((entry) => entry.id === sceneId)
  }
  const voice = effectiveVoice(doc, sceneId)
  if (voice.provider !== "edge" && voice.provider !== "system" && voice.provider !== "elevenlabs") {
    s.setTakeJob(sceneId, { pct: 0, stage: "", error: "Choose a narration provider first." })
    return
  }
  s.setTakeJob(sceneId, { pct: 0, stage: "Queued" })
  try {
    const { job_id } = await api.generateTake(s.projectId, {
      scene_id: sceneId, text: scene.narration.text, provider: voice.provider, voice_id: voice.voice_id,
      rate_pct: voice.rate_pct, model_id: voice.model_id,
    })
    const res = await waitJob<{ scene_id: string; take: Take }>(job_id, (pct, stage) => {
      if (isCurrent()) useEditor.getState().setTakeJob(sceneId, { pct, stage })
    })
    if (!isCurrent()) return
    attach(sceneId, res.take)
    useEditor.getState().setTakeJob(sceneId, null)
  } catch (e) {
    if (isCurrent()) useEditor.getState().setTakeJob(sceneId, { pct: 0, stage: "", error: (e as Error).message })
  }
}

/** Every line that has no voice yet, or whose line or voice changed, one after another. */
export async function generateAllNeeded(): Promise<number> {
  const doc = useEditor.getState().doc
  if (!doc) return 0
  const ids = doc.scenes.filter((sc) => ["missing", "stale"].includes(takeState(sc.id))).map((sc) => sc.id)
  for (const id of ids) await generateTake(id)
  return ids.length
}

/** A recording from the microphone or an imported audio file becomes this line's take. */
export async function uploadTake(sceneId: string, file: Blob, filename: string, method: "recorded" | "imported") {
  const s = useEditor.getState()
  const scene = s.doc?.scenes.find((x) => x.id === sceneId)
  if (!s.projectId || !scene?.narration) return
  s.setTakeJob(sceneId, { pct: 30, stage: method === "recorded" ? "Saving the recording" : "Importing" })
  try {
    const r = await api.uploadTake(s.projectId, sceneId, scene.narration.text, file, filename, method)
    attach(sceneId, r.take)
    useEditor.getState().setTakeJob(sceneId, null)
  } catch (e) {
    useEditor.getState().setTakeJob(sceneId, { pct: 0, stage: "", error: (e as Error).message })
  }
}

const takeSpeeds: Record<string, number> = {}

export function takeSpeed(takeId: string | undefined): number {
  return takeId ? (takeSpeeds[takeId] ?? 1) : 1
}

/** Time-stretch an existing take WAV from its 1.0x original on the server (preserves pitch & timings). */
export async function speedUpTake(sceneId: string, speed: number) {
  const s = useEditor.getState()
  const scene = s.doc?.scenes.find((x) => x.id === sceneId)
  const take = scene?.narration?.take
  if (!s.projectId || !scene?.narration || !take) return
  s.setTakeJob(sceneId, { pct: 40, stage: speed === 1 ? "Restoring 1.0× speed" : `Adjusting speed (${speed.toFixed(2)}×)` })
  try {
    const audioName = ops.takeFileName(take.audio_path)
    const r = await api.speedTake(s.projectId, {
      scene_id: sceneId, text: scene.narration.text, audio_name: audioName,
      speed, words: take.words, timing: take.timing,
    })
    takeSpeeds[r.take.id] = r.speed ?? speed
    attach(sceneId, r.take)
    useEditor.getState().setTakeJob(sceneId, null)
  } catch (e) {
    const msg = (e as Error).message
    const hint = msg.includes("404") || msg.toLowerCase().includes("not found")
      ? "Restart Shorts Studio once to enable instant local speed-up, or change Pace and click Regenerate voice."
      : msg
    useEditor.getState().setTakeJob(sceneId, { pct: 0, stage: "", error: hint })
  }
}
