// Voice takes: generate, record or import one line's take, then attach it to that scene only. Jobs live outside
// any component, so switching scenes while a voice is being made doesn't lose it.
import { api } from "../api"
import { waitJob } from "../events"
import * as ops from "../model/ops"
import type { Project, Take } from "../model/types"
import { useEditor } from "./editor"

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
