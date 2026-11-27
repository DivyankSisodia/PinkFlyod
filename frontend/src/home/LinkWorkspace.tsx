import { useEffect, useRef, useState, type ReactNode } from "react"
import { api } from "../api"
import { navigate } from "../App"
import { waitJob } from "../events"
import { StudioShell } from "./StudioShell"
import { WorkspaceIcon } from "./WorkspaceIcon"

const sources = [
  { id: "youtube", icon: "youtube", label: "YouTube URL", placeholder: "https://www.youtube.com/watch?v=…" },
  { id: "instagram", icon: "instagram", label: "Instagram Reel URL", placeholder: "https://www.instagram.com/reel/…" },
  { id: "gameplay", icon: "game", label: "Background gameplay URL", placeholder: "https://…" },
] as const

type Source = typeof sources[number]["id"]
type Layout = "split" | "pip"
type Draft = { links: Record<Source, string>; layout: Layout }
const storageKey = "shorts-studio.link-draft.v1"

function loadDraft(): Draft {
  const draft: Draft = { links: { youtube: "", instagram: "", gameplay: "" }, layout: "split" }
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null")
    for (const { id } of sources) {
      if (typeof saved?.links?.[id] === "string") draft.links[id] = saved.links[id]
    }
    if (saved?.layout === "pip") draft.layout = "pip"
  } catch { /* The workspace can start with an empty form when storage is unavailable. */ }
  return draft
}

function validLink(source: Source, value: string): boolean {
  let url: URL
  try { url = new URL(value) } catch { return false }
  if (!/^https?:\/\//i.test(value) || url.username || url.password) return false
  const host = url.hostname.replace(/^www\./, "")
  if (source === "gameplay") return true
  if (source === "instagram") {
    return host === "instagram.com" && /^\/reels?\/[\w-]+\/?$/.test(url.pathname)
  }
  if (host === "youtu.be") return /^\/[\w-]+\/?$/.test(url.pathname)
  return ["youtube.com", "m.youtube.com", "music.youtube.com"].includes(host) && (
    (url.pathname === "/watch" && /^[\w-]+$/.test(url.searchParams.get("v") ?? "")) ||
    /^\/(shorts|live|embed)\/[\w-]+\/?$/.test(url.pathname)
  )
}

const validationMessage = {
  youtube: "Enter a YouTube video or Shorts link.",
  instagram: "Enter an Instagram Reel link.",
  gameplay: "Enter a link that starts with https:// or http://.",
}

export function LinkWorkspace({ children, onFilesDrop, country }: {
  children: ReactNode; onFilesDrop: (files: FileList) => void; country: string
}) {
  const [draft, setDraft] = useState(loadDraft)
  const [submitted, setSubmitted] = useState(false)
  const [status, setStatus] = useState("")
  const [actionError, setActionError] = useState(false)
  const [importing, setImporting] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const filled = sources.filter(({ id }) => draft.links[id].trim())
  const invalid = filled.filter(({ id }) => !validLink(id, draft.links[id].trim()))

  function updateDraft(next: Draft) {
    setDraft(next)
    setStatus("")
    setActionError(false)
  }

  function checkedDraft(): Draft | null {
    setSubmitted(true)
    if (!filled.length || invalid.length) {
      document.getElementById(`link-${invalid[0]?.id ?? "youtube"}`)?.focus()
      return null
    }
    const links = {
      youtube: draft.links.youtube.trim(),
      instagram: draft.links.instagram.trim(),
      gameplay: draft.links.gameplay.trim(),
    }
    return { ...draft, links }
  }

  function saveDraft() {
    const normalized = checkedDraft()
    if (!normalized) return
    try {
      localStorage.setItem(storageKey, JSON.stringify(normalized))
      setSubmitted(false)
      setActionError(false)
      setStatus("Draft saved on this device.")
    } catch {
      setActionError(true)
      setStatus("This browser couldn’t save your draft.")
    }
  }

  async function importLinks() {
    const normalized = checkedDraft()
    if (!normalized) return
    setImporting(true)
    setJobId(null)
    setActionError(false)
    setStatus("Queuing the import…")
    try {
      const started = await api.importUrls({ ...normalized.links, layout: normalized.layout, country })
      setJobId(started.job_id)
      const result = await waitJob<{ project_id?: string; clip_id?: string }>(started.job_id, (pct, stage) => {
        if (mounted.current) setStatus(`${stage} · ${Math.round(pct)}%`)
      })
      if (mounted.current) navigate(result.project_id ? `#/p/${result.project_id}` : "#/library/gameplay")
    } catch (e) {
      if (mounted.current) {
        setStatus((e as Error).message)
        setActionError(true)
      }
    } finally {
      if (mounted.current) setImporting(false)
    }
  }

  return (
    <StudioShell page="home" onFilesDrop={onFilesDrop}>
          <header className="studio-intro" id="new-short" tabIndex={-1}>
            <h1>Create a Short</h1>
            <p>Start with a YouTube video, an Instagram Reel, or both. Add gameplay for the background.</p>
          </header>
          <div className="studio-grid">
            <form className="studio-card studio-form" onSubmit={(event) => { event.preventDefault(); void importLinks() }} noValidate>
              <header className="studio-card-head">
                <h2>Video sources</h2>
                <p>Paste the links you want to use in your short.</p>
              </header>
              <div className="studio-sources">
                {sources.map(({ id, icon, label, placeholder }) => {
                  const error = submitted && invalid.some((source) => source.id === id)
                  const ready = draft.links[id].trim() && !invalid.some((source) => source.id === id)
                  return (
                    <div className="studio-source" key={id}>
                      <span className={`studio-platform studio-platform-${id}`}><WorkspaceIcon name={icon} /></span>
                      <div className="studio-source-field">
                        <label htmlFor={`link-${id}`}>{label}</label>
                        <div className="studio-url">
                          <WorkspaceIcon name="link" size={17} />
                          <input id={`link-${id}`} type="url" value={draft.links[id]} placeholder={placeholder} disabled={importing}
                            autoComplete="off" spellCheck={false} aria-invalid={error || undefined}
                            aria-describedby={error ? `link-error-${id}` : undefined}
                            onChange={(event) => updateDraft({ ...draft, links: { ...draft.links, [id]: event.target.value } })} />
                          {ready && <span className="studio-valid"><WorkspaceIcon name="check" size={16} /></span>}
                        </div>
                        {error && <p className="studio-field-error" id={`link-error-${id}`}>{validationMessage[id]}</p>}
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="studio-form-footer">
                <p className="studio-rights"><WorkspaceIcon name="shield" size={16} /> Use footage you own or have permission to use.</p>
                <div className="studio-form-actions">
                  <button className="studio-save" type="submit" disabled={importing}>
                    {filled.length === 1 && filled[0].id === "gameplay" ? "Add to gameplay library" : "Import and open editor"}
                    <WorkspaceIcon name="arrow" size={19} />
                  </button>
                  <button type="button" disabled={importing} onClick={saveDraft}>Save draft</button>
                </div>
                <p className={`studio-save-status${actionError || (submitted && !filled.length) ? " studio-field-error" : ""}`} role="status">
                  {submitted && !filled.length ? "Add at least one video link." : status || "Use public video links. Gameplay is saved in your library."}
                  {jobId && <> · <a href={`#/activity/${jobId}`}>View checkpoints</a></>}
                </p>
              </div>
            </form>

            <section className="studio-card studio-preview" aria-labelledby="layout-heading">
              <header className="studio-card-head studio-preview-head">
                <div><h2 id="layout-heading">Layout preview</h2><p>Sample footage</p></div>
                <span className="studio-aspect"><WorkspaceIcon name="portrait" size={16} /> 9:16</span>
              </header>
              <div className="studio-stage">
                <div className={`studio-frame studio-frame-${draft.layout}`} role="img"
                  aria-label={draft.layout === "split" ? "Sample with foreground above gameplay" : "Sample with a foreground inset over gameplay"}>
                  <div className="studio-media studio-foreground" />
                  <div className="studio-media studio-gameplay" />
                </div>
              </div>
              <fieldset className="studio-layouts" disabled={importing}>
                <legend>Composition</legend>
                <div>
                  <label><input type="radio" name="link-layout" value="split" checked={draft.layout === "split"}
                    onChange={() => updateDraft({ ...draft, layout: "split" })} />
                    <span><WorkspaceIcon name="split" size={17} /> Split screen</span></label>
                  <label><input type="radio" name="link-layout" value="pip" checked={draft.layout === "pip"}
                    onChange={() => updateDraft({ ...draft, layout: "pip" })} />
                    <span><WorkspaceIcon name="pip" size={17} /> Picture-in-picture</span></label>
                </div>
              </fieldset>
            </section>
          </div>
          {children}
    </StudioShell>
  )
}
