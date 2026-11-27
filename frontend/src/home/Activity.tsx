import { useEffect, useState } from "react"
import { api } from "../api"
import type { Checkpoint, Job } from "../model/types"
import { StudioShell } from "./StudioShell"

const kindNames: Record<string, string> = {
  url_import: "Video link import", script_draft: "Script draft", intro_draft: "AI intro draft", take: "Voice take",
  render: "MP4 export", media_prep: "Media preparation", gameplay_sample: "Gameplay sample",
}
const time = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })

export function ActivityPage({ jobId }: { jobId?: string }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [logs, setLogs] = useState<Checkpoint[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState("")
  const [cancelled, setCancelled] = useState(false)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    setCancelled(false)
    async function refresh() {
      try {
        const { jobs: recent } = await api.jobs()
        const selected = jobId ? (recent.find((entry) => entry.id === jobId) ?? await api.job(jobId)) : recent[0]
        const result = selected ? await api.checkpoints(selected.id) : { checkpoints: [] }
        if (active) {
          setJobs(recent)
          setJob(selected ?? null)
          setLogs(result.checkpoints)
          setError("")
        }
      } catch (reason) {
        if (active) setError((reason as Error).message)
      } finally {
        if (active) {
          setLoaded(true)
          timer = setTimeout(refresh, 1500)
        }
      }
    }
    void refresh()
    return () => { active = false; clearTimeout(timer) }
  }, [jobId])

  async function cancel() {
    if (!job) return
    try { setCancelled((await api.cancelJob(job.id)).cancelled) }
    catch (reason) { setError((reason as Error).message) }
  }

  const running = job?.status === "running" || job?.status === "queued"
  const project = job?.project_id ?? (typeof job?.result?.project_id === "string" ? job.result.project_id : null)

  return (
    <StudioShell page="activity">
      <header className="studio-intro"><h1>Activity</h1><p>Follow imports, script drafts, voice takes, and exports from queue to completion.</p></header>
      {error && <p className="error-text" role="status">{error}</p>}
      <div className="studio-activity-grid">
        <section className="studio-card studio-config" aria-labelledby="recent-jobs-heading">
          <h2 id="recent-jobs-heading">Recent jobs</h2>
          {jobs.length ? <ul className="studio-job-list">
            {jobs.map((entry) => <li key={entry.id}>
              <a href={`#/activity/${entry.id}`} aria-current={entry.id === job?.id ? "page" : undefined}>
                <span>{kindNames[entry.kind] ?? entry.kind}</span>
                <span className={`studio-state studio-state-${entry.status}`}>{entry.status}</span>
              </a>
            </li>)}
          </ul> : <p className="hint">{loaded ? "Jobs appear here when you start one." : "Loading activity…"}</p>}
        </section>
        <section className="studio-card studio-config" aria-labelledby="checkpoint-heading">
          <header className="studio-card-head studio-preview-head">
            <div><h2 id="checkpoint-heading">Checkpoints</h2>{job && <p>{kindNames[job.kind] ?? job.kind}</p>}</div>
            {running && <button disabled={cancelled} onClick={() => void cancel()}>{cancelled ? "Cancelling…" : "Cancel job"}</button>}
          </header>
          {job && (running || job.status === "done") && (
            <div className="studio-job-progress"><progress aria-label="Job progress" value={job.pct} max={100} /><span>{Math.round(job.pct)}%</span></div>
          )}
          {logs.length ? <ol className="studio-checkpoints">
            {logs.map((entry, index) => <li key={`${entry.created_at}-${index}`}>
              <time dateTime={entry.created_at}>{time.format(new Date(entry.created_at))}</time><span>{entry.stage}</span>
            </li>)}
          </ol> : <p className="hint">{job?.stage || "Select a job to see its checkpoint log."}</p>}
          {job?.error && <p className="error-text">{job.error}</p>}
          {job?.status === "done" && <div className="row studio-result-links">
            {project && <a href={`#/p/${project}`}>Open project</a>}
            {typeof job.result?.clip_id === "string" && <a href="#/library/gameplay">Open gameplay library</a>}
            {job.kind === "script_draft" && <a href={`#/draft/${job.id}`}>Review script</a>}
          </div>}
        </section>
      </div>
    </StudioShell>
  )
}
