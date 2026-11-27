import { useEffect, useRef, useState } from "react"
import { api, takeUrl, type ProviderSettings } from "../api"
import { waitJob } from "../events"
import * as ops from "../model/ops"
import type { Project, Take } from "../model/types"
import { useEditor } from "../state/editor"
import { Thumb } from "../ui/Thumb"

type IntroDraft = {
  script: string; scene_id: string; segment_id: string; source_id: string; in_s: number; out_s: number; model: string
}
type Progress = { stage: string; pct: number; jobId?: string }

function openingVideo(project: Project) {
  const scene = project.scenes.find((entry) => entry.enabled)
  const segment = scene && ops.primarySegment(project, scene)
  const source = segment && project.sources[segment.seg.source_id]
  if (!scene || !segment || source?.kind !== "video") return null
  return { scene, segment, source }
}

export function IntroDialog({ onClose }: { onClose: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const timeline = useEditor((s) => s.timeline)
  const { apply, flush } = useEditor.getState()
  const opening = openingVideo(doc)
  const sceneId = opening?.scene.id
  const segmentId = opening?.segment.id
  const sourceId = opening?.segment.seg.source_id
  const inSeconds = opening?.segment.seg.in_s
  const outSeconds = opening?.segment.seg.out_s
  const openingSeconds = opening ? timeline?.scenes.find((scene) => scene.id === sceneId)?.duration_s ??
    ops.sceneFrames(doc, opening.scene) / doc.output.fps : 0
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [settings, setSettings] = useState<ProviderSettings | null>(null)
  const [notes, setNotes] = useState("")
  const [draft, setDraft] = useState<IntroDraft | null>(null)
  const [script, setScript] = useState("")
  const [duck, setDuck] = useState(true)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [error, setError] = useState("")
  const [result, setResult] = useState<Take | null>(null)
  const [restoring, setRestoring] = useState(true)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    const dialog = dialogRef.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])

  useEffect(() => {
    let active = true
    function loadSettings() {
      void api.providers().then((value) => { if (active) setSettings(value) }).catch((reason) => {
        if (active) setError((reason as Error).message)
      })
    }
    loadSettings()
    window.addEventListener("focus", loadSettings)
    return () => { active = false; window.removeEventListener("focus", loadSettings) }
  }, [])

  useEffect(() => {
    let active = true
    if (!sceneId) { setRestoring(false); return }
    setRestoring(true)
    void api.jobs(doc.id).then(({ jobs }) => {
      const match = jobs.find(({ kind, status, result: value }) => kind === "intro_draft" && status === "done" &&
        value?.scene_id === sceneId && value.segment_id === segmentId && value.source_id === sourceId &&
        value.in_s === inSeconds && value.out_s === outSeconds && typeof value.script === "string")
      if (active && match?.result) {
        const previous = match.result as IntroDraft
        setDraft(previous)
        setScript(previous.script)
      }
    }).catch(() => undefined).finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [doc.id, sceneId, segmentId, sourceId, inSeconds, outSeconds])

  async function runJob<T>(start: () => Promise<{ job_id: string }>): Promise<T> {
    const { job_id } = await start()
    setProgress({ stage: "Queued", pct: 0, jobId: job_id })
    return waitJob<T>(job_id, (pct, stage) => setProgress({ stage, pct, jobId: job_id }))
  }

  async function makeDraft() {
    setError("")
    setProgress({ stage: "Saving timeline", pct: 0 })
    try {
      if (!await flush()) throw new Error(useEditor.getState().saveError ?? "Save the project before drafting an intro.")
      const latest = useEditor.getState()
      const next = await runJob<IntroDraft>(() => api.draftIntro(doc.id, latest.baseRevision, notes))
      setDraft(next)
      setScript(next.script)
      setResult(null)
    } catch (reason) { setError((reason as Error).message) }
    finally { setProgress(null); setCancelling(false) }
  }

  async function addVoiceover() {
    if (!opening || !draft || !settings || !script.trim()) return
    const approved = script.trim()
    setError("")
    setResult(null)
    setProgress({ stage: "Queuing ElevenLabs voiceover", pct: 0 })
    try {
      const { take } = await runJob<{ take: Take }>(() => api.generateTake(doc.id, {
        scene_id: opening.scene.id, text: approved, provider: "elevenlabs", voice_id: settings.elevenlabs_voice,
        model_id: settings.elevenlabs_model, rate_pct: 0,
      }))
      const latest = useEditor.getState()
      const current = latest.doc?.id === doc.id && openingVideo(latest.doc)
      if (!current || current.scene.id !== opening.scene.id || current.segment.seg !== opening.segment.seg ||
        current.scene.narration !== opening.scene.narration || latest.saveState === "readonly" || latest.saveState === "conflict") {
        throw new Error("The opening scene changed. Reopen AI intro to apply voiceover to the current timeline.")
      }
      // The opening scene grows to fit the line (the clip keeps playing under it), up to the whole opening clip.
      const seconds = ops.openingSceneSeconds(latest.doc!, current.scene.id, take.duration_s)
      if (seconds === null) {
        const room = ops.openingVoiceRoom(latest.doc!, current.scene.id)
        throw new Error(`This take is ${take.duration_s.toFixed(2)} s, but the opening clip only has ${room.toFixed(2)} s. Shorten the line and try again.`)
      }
      apply((project) => ops.addOpeningVoice(project, current.scene.id, approved, take, seconds, duck && current.source.fingerprint.has_audio))
      latest.select(current.scene.id)
      latest.setPlayhead(0)
      if (!await flush()) throw new Error(useEditor.getState().saveError ?? "The voiceover was added, but the project could not be saved.")
      setResult(take)
    } catch (reason) { setError((reason as Error).message) }
    finally { setProgress(null); setCancelling(false) }
  }

  async function cancel() {
    if (!progress?.jobId) return
    setCancelling(true)
    try {
      if (!(await api.cancelJob(progress.jobId)).cancelled) setCancelling(false)
    } catch (reason) {
      setError((reason as Error).message)
      setCancelling(false)
    }
  }

  const canDraft = settings?.opencode_configured && settings.opencode_model
  const canVoice = settings?.elevenlabs_configured && settings.elevenlabs_voice
  return (
    <dialog ref={dialogRef} className="modal-box intro-dialog" aria-labelledby="intro-title" data-testid="intro-dialog"
      onCancel={(event) => { event.preventDefault(); if (!progress) onClose() }}>
      <div className="modal-head"><h2 id="intro-title">AI intro voiceover</h2><button onClick={onClose} disabled={!!progress}>Close</button></div>
      {opening && sourceId ? <>
        <div className="intro-source">
          <Thumb sourceId={sourceId} />
          <div><strong>{opening.source.display_name}</strong>
            <div className="hint">Timeline 0:00 · {openingSeconds.toFixed(2)} s opening scene</div></div>
        </div>
        <p className="hint">OpenCode Go uses the clip title and sampled video frames to write an opening hook. If the
          line runs longer than the opening scene, the scene is extended to fit it.</p>
        <label className="intro-field">Context for the hook (optional)
          <input type="text" value={notes} maxLength={500} disabled={!!progress} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="row intro-actions">
          <button className={draft ? "" : "primary"} onClick={() => void makeDraft()} disabled={!canDraft || !!progress || restoring}>
            {draft ? "Draft again with OpenCode" : "Draft with OpenCode"}
          </button>
          {canDraft && <span className="hint">{settings.opencode_model}</span>}
          {settings && !canDraft && <a href="#/settings" target="_blank" rel="noopener">Set up OpenCode Go</a>}
        </div>
        {draft && <section className="intro-review" aria-labelledby="intro-review-heading">
          <h3 id="intro-review-heading">Review the script</h3>
          <label className="intro-field">Voiceover text
            <textarea rows={3} maxLength={600} value={script} onChange={(e) => setScript(e.target.value)} disabled={!!progress} />
          </label>
          {script !== draft.script && <details className="intro-original"><summary>Original OpenCode draft</summary><p>{draft.script}</p></details>}
          {opening.source.fingerprint.has_audio && <label className="check"><input type="checkbox" checked={duck}
            onChange={(e) => setDuck(e.target.checked)} disabled={!!progress} /> Lower the original audio while the intro speaks</label>}
          <div className="row intro-actions">
            <button className="primary" disabled={!canVoice || !script.trim() || !!progress} onClick={() => void addVoiceover()}>
              {opening.scene.narration ? "Replace opening voice with ElevenLabs" : "Generate with ElevenLabs and add at 0:00"}
            </button>
            {settings && !canVoice && <a href="#/settings" target="_blank" rel="noopener">Set up ElevenLabs voice</a>}
          </div>
        </section>}
      </> : <p className="hint">Put a video clip at the start of the timeline first.</p>}
      {progress && <div className="intro-progress" role="status">
        <progress value={progress.pct} max={100} aria-label="AI intro progress" />
        <div className="row between">
          <span>{progress.stage}</span>
          {progress.jobId && <div className="row">
            <a href={`#/activity/${progress.jobId}`} target="_blank" rel="noopener">View checkpoints</a>
            <button onClick={() => void cancel()} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel"}</button>
          </div>}
        </div>
      </div>}
      {error && <p role="alert" className="error-text">{error}</p>}
      {result && <div className="intro-result">
        <p role="status">Voiceover added at 0:00.</p>
        <audio controls src={takeUrl(result.audio_path)} aria-label="Preview the intro voiceover" />
      </div>}
    </dialog>
  )
}
