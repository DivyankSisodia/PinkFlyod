import { useEffect, useRef, useState } from "react"
import { api, uploadFile, type VoiceProvider } from "../api"
import { navigate } from "../App"
import { waitJob } from "../events"
import { useGameplayClips } from "../library/GameplayLibrary"
import type { ProjectSummary } from "../model/types"
import { Thumb } from "../ui/Thumb"
import { ago } from "../ui/format"
import { DeleteProjectDialog } from "./DeleteProject"
import { LinkWorkspace } from "./LinkWorkspace"

type EditPreset = "quick_short" | "ranking" | "whole" | "gameplay"
const EDIT_PRESETS: { value: EditPreset; label: string; hint: string }[] = [
  { value: "quick_short", label: "Quick Short", hint: "Pick 12–15 seconds of one video. Works offline." },
  { value: "ranking", label: "Ranking / countdown", hint: "Each file is one entry with a number badge and a label." },
  { value: "whole", label: "Whole clips", hint: "Each file becomes a scene, in order, no length cap." },
  { value: "gameplay", label: "Clips over gameplay", hint: "Your clips on top, library gameplay below (or around)." },
]

type ScratchKind = "script" | "reddit" | "ranking_list" | "blank" | "topic"
const SCRATCH: { value: ScratchKind; label: string }[] = [
  { value: "script", label: "Script or story" },
  { value: "reddit", label: "Reddit-style post" },
  { value: "ranking_list", label: "Ranking list" },
  { value: "blank", label: "Blank" },
  { value: "topic", label: "From a topic" },
]

export function Home({ draftId }: { draftId?: string }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null)
  const [deleted, setDeleted] = useState<string | null>(null)
  const [country, setCountry] = useState("US")
  const [preset, setPreset] = useState<EditPreset>("quick_short")
  const [direction, setDirection] = useState<"descending" | "ascending">("descending")
  const [gpLayout, setGpLayout] = useState<"split" | "pip">("split")
  const [gpClip, setGpClip] = useState("")
  const [kind, setKind] = useState<ScratchKind>("script")
  const [text, setText] = useState("")
  const [topic, setTopic] = useState("")
  const [draftJob, setDraftJob] = useState<string | null>(null)
  const [title, setTitle] = useState("")
  const [reddit, setReddit] = useState({ community: "r/", title: "", source_url: "" })
  const [bgClip, setBgClip] = useState("")
  const [voiceOverride, setVoice] = useState<VoiceProvider | null>(null)
  const [elevenReady, setElevenReady] = useState(false)
  const voice = voiceOverride ?? (elevenReady ? "elevenlabs" : "edge")
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const { clips } = useGameplayClips()
  const usable = (clips ?? []).filter((c) => c.exists)

  useEffect(() => {
    api.listProjects().then((r) => setProjects(r.projects)).catch((e) => setError(e.message))
    api.providers().then((r) => {
      if (r.elevenlabs_configured && r.elevenlabs_voice) setElevenReady(true)
    }).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (!draftId) return
    let active = true
    api.job(draftId).then((job) => {
      if (active && job.kind === "script_draft" && typeof job.result?.script === "string") {
        setKind("topic")
        setText(job.result.script)
        const audience = job.result.country
        if (audience === "US" || audience === "CA" || audience === "BOTH") setCountry(audience)
      }
    }).catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [draftId])
  useEffect(() => { if (!gpClip && usable.length) setGpClip(usable[0].id) }, [usable, gpClip])

  async function create(paths: string[]) {
    if (!paths.length) return
    setBusy("Reading your video…")
    setError(null)
    try {
      let r: { project: { id: string }; import_errors: { path: string; error: string }[] }
      if (preset === "ranking") r = await api.createRanking(paths, "own", country, direction)
      else if (preset === "gameplay") {
        if (!gpClip) throw new Error("Add a gameplay clip to the library first (Gameplay library).")
        r = await api.createOverGameplay(paths, gpClip, gpLayout, "own", country)
      } else r = await api.createProject(paths, preset === "whole" ? "blank" : "quick_short", "own", country)
      if (r.import_errors.length) console.warn(r.import_errors)
      navigate(`#/p/${r.project.id}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }

  async function chooseFiles() {
    setError(null)
    setBusy("Waiting for you to choose files…")
    try {
      const { paths } = await api.dialog("open_files", "Choose the footage to edit")
      if (paths.length) await create(paths)
      else setBusy(null)
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }

  async function uploadAndCreate(files: FileList | File[]) {
    const list = Array.from(files)
    if (!list.length) return
    setError(null)
    const paths: string[] = []
    try {
      for (const [i, f] of list.entries()) {
        paths.push(await uploadFile(f, (p) => setBusy(`Copying ${f.name} (${i + 1}/${list.length}) ${Math.round(p * 100)}%`)))
      }
      await create(paths)
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }

  async function createFromScratch() {
    setError(null)
    setBusy("Setting up your project…")
    try {
      const r = await api.createFromScript({
        kind: kind === "topic" ? "script" : kind, text, title: title.trim() || null, country,
        voice_provider: voice, from_topic: kind === "topic",
        reddit: kind === "reddit" ? {
          community: reddit.community.trim() || "r/stories", title: reddit.title,
          source_url: reddit.source_url.trim() || null
        } : null,
        gameplay_clip_id: (kind === "script" || kind === "reddit" || kind === "topic") && bgClip ? bgClip : null,
      })
      navigate(`#/p/${r.project.id}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }

  async function draftFromTopic() {
    setError(null)
    setBusy("Queuing the script draft…")
    setDraftJob(null)
    try {
      const { job_id } = await api.draftScript(topic, country)
      setDraftJob(job_id)
      const result = await waitJob<{ script: string }>(job_id, (_pct, stage) => setBusy(stage))
      setText(result.script)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const presetHint = EDIT_PRESETS.find((p) => p.value === preset)!.hint
  const scratchReady = kind === "blank" || text.trim().length > 0 || (kind === "reddit" && reddit.title.trim().length > 0)
  return (
    <LinkWorkspace country={country} onFilesDrop={(files) => { if (!busy) void uploadAndCreate(files) }}>
      <section className="studio-local" id="local-start" aria-labelledby="local-heading" tabIndex={-1}>
        <h2 id="local-heading">What do you want to make?</h2>
        <div className="row">
          <label className="inline">Audience
            <select value={country} onChange={(e) => setCountry(e.target.value)} data-testid="home-audience">
              <option value="US">United States</option>
              <option value="CA">Canada</option>
              <option value="BOTH">Both</option>
            </select>
          </label>
        </div>
        <div className="start-cards">
          <section className="start-card" data-testid="edit-card">
            <h3>Edit an existing video</h3>
            <div className="seg-buttons wrap" role="radiogroup" aria-label="What to make">
              {EDIT_PRESETS.map((p) => (
                <button key={p.value} className={preset === p.value ? "on" : ""} onClick={() => setPreset(p.value)}
                  data-testid={`preset-${p.value}`}>{p.label}</button>
              ))}
            </div>
            <p>{presetHint}</p>
            {preset === "ranking" && (
              <label>Order
                <select value={direction} onChange={(e) => setDirection(e.target.value as "descending")} data-testid="home-direction">
                  <option value="descending">Countdown: the first file is the highest number</option>
                  <option value="ascending">Count up: the first file is #1</option>
                </select>
              </label>
            )}
            {preset === "gameplay" && (
              usable.length ? (
                <div className="row">
                  <label>Gameplay
                    <select value={gpClip} onChange={(e) => setGpClip(e.target.value)} data-testid="home-gameplay">
                      {usable.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
                    </select>
                  </label>
                  <label>Layout
                    <select value={gpLayout} onChange={(e) => setGpLayout(e.target.value as "split")} data-testid="home-gp-layout">
                      <option value="split">Split screen</option><option value="pip">Picture in picture</option>
                    </select>
                  </label>
                </div>
              ) : <p className="hint">The gameplay library is empty. <a href="#/library/gameplay">Add clips or a sample</a> first.</p>
            )}
            <div className="row">
              <button className="primary" disabled={!!busy} onClick={chooseFiles} data-testid="choose-files">Choose files…</button>
              <button disabled={!!busy} onClick={() => fileInput.current?.click()}>Copy files in…</button>
              <input ref={fileInput} type="file" multiple hidden accept="video/*,image/*" data-testid="file-input"
                onChange={(e) => e.target.files && void uploadAndCreate(e.target.files)} />
            </div>
            <p className="hint">“Choose files” links to your files where they are. “Copy files in”, or dropping files
              on this page, copies them into the app.</p>
          </section>
          <section className="start-card" data-testid="scratch-card">
            <h3>Create from scratch</h3>
            <div className="seg-buttons wrap" role="radiogroup" aria-label="Start from">
              {SCRATCH.map((k) => (
                <button key={k.value} className={kind === k.value ? "on" : ""} onClick={() => setKind(k.value)} disabled={!!busy}
                  data-testid={`scratch-${k.value}`}>{k.label}</button>
              ))}
            </div>
            {kind === "topic" && (
              <div className="studio-topic">
                <label>Topic<input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={2000}
                  placeholder="What should the Short be about?" /></label>
                <div className="row">
                  <button disabled={!!busy || !topic.trim()} onClick={() => void draftFromTopic()}>Draft with OpenCode Go</button>
                  <a className="hint" href={draftJob ? `#/activity/${draftJob}` : "#/settings"}>
                    {draftJob ? "View checkpoints" : "AI settings"}
                  </a>
                </div>
              </div>
            )}
            {kind === "reddit" && (
              <div className="row">
                <label>Community<input value={reddit.community} onChange={(e) => setReddit({ ...reddit, community: e.target.value })}
                  data-testid="reddit-community" /></label>
                <label className="grow">Link to the post (optional)<input value={reddit.source_url} placeholder="https://www.reddit.com/r/…"
                  onChange={(e) => setReddit({ ...reddit, source_url: e.target.value })} data-testid="reddit-link" /></label>
              </div>
            )}
            {kind === "reddit" && (
              <label>Post title<input value={reddit.title} onChange={(e) => setReddit({ ...reddit, title: e.target.value })}
                data-testid="reddit-title" /></label>
            )}
            {kind !== "blank" && (
              <label>{kind === "ranking_list" ? "One entry per line, in the order they play" : kind === "reddit" ? "Post text" :
                kind === "topic" ? "Review and edit the script" : "Script"}
                <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} data-testid="scratch-text" maxLength={20000}
                  disabled={!!busy && kind === "topic"} placeholder={kind === "topic" ? "Your draft will appear here." :
                    kind === "ranking_list" ? "The bridge jump\nThe car flip\nThe final boss" :
                      "Paste your script. Each sentence or paragraph becomes a scene with its own voice line."} />
              </label>
            )}
            {kind === "reddit" && <p className="hint">Usernames like u/name are replaced with “the poster”. The card shows
              votes only if you type them in later.</p>}
            <div className="row">
              <label>Title (optional)<input value={title} onChange={(e) => setTitle(e.target.value)} data-testid="scratch-title" /></label>
              {kind !== "blank" && (
                <label>Voice
                  <select value={voice} onChange={(e) => setVoice(e.target.value as VoiceProvider)} data-testid="scratch-voice">
                    <option value="edge">Edge voice (free, online)</option>
                    <option value="system">This computer's voice (offline)</option>
                    <option value="elevenlabs">ElevenLabs</option>
                  </select>
                </label>
              )}
              {(kind === "script" || kind === "reddit" || kind === "topic") && (
                <label>Background
                  <select value={bgClip} onChange={(e) => setBgClip(e.target.value)} data-testid="scratch-gameplay">
                    <option value="">Colour cards</option>
                    {usable.map((c) => <option key={c.id} value={c.id}>Gameplay: {c.display_name}</option>)}
                  </select>
                </label>
              )}
            </div>
            {voice === "elevenlabs" && kind !== "blank" && !elevenReady && (
              <p className="hint"><a href="#/settings">Add an ElevenLabs key and choose a speaker in AI settings.</a></p>
            )}
            <div className="row">
              <button className="primary" disabled={!!busy || !scratchReady} onClick={() => void createFromScratch()}
                data-testid="create-scratch">Create</button>
            </div>
          </section>
        </div>
        {busy && <div className="notice" data-testid="busy">{busy}</div>}
        {error && <div className="notice error" data-testid="error">{error}</div>}
      </section>
      <section className="studio-local studio-recent" id="recent-projects" aria-labelledby="recent-heading" tabIndex={-1}>
        <h2 id="recent-heading">Recent projects</h2>
        {projects === null ? <p className="hint">Loading…</p> : projects.length === 0 ? (
          <p className="hint">Nothing yet. Your projects will appear here.</p>
        ) : (
          <div className="recent" data-testid="recent">
            {projects.map((p) => (
              <div key={p.id} className="recent-wrap">
                <a className="recent-item" href={`#/p/${p.id}`} data-testid="recent-item">
                  <div className="recent-thumb">
                    {p.poster_source_id && <Thumb sourceId={p.poster_source_id} />}
                  </div>
                  <div className="recent-meta">
                    <strong>{p.title}</strong>
                    <span>{p.scene_count} scene{p.scene_count === 1 ? "" : "s"} · {ago(p.updated_at)}</span>
                    {!!p.missing && <span className="badge warn">{p.missing} missing file{p.missing > 1 ? "s" : ""}</span>}
                  </div>
                </a>
                <button className="recent-delete" title="Delete this project" aria-label={`Delete ${p.title}`}
                  data-testid="delete-project" onClick={() => setDeleting(p)}>🗑</button>
              </div>
            ))}
          </div>
        )}
        {deleted && <p className="notice" role="status" data-testid="deleted-message">{deleted}</p>}
        {deleting && <DeleteProjectDialog project={deleting} onClose={() => setDeleting(null)}
          onDeleted={(message) => {
            setDeleting(null)
            setDeleted(message)
            setProjects((list) => (list ?? []).filter((x) => x.id !== deleting.id))
          }} />}
      </section>
    </LinkWorkspace>
  )
}
