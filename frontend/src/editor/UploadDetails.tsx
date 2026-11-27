// Upload details: OpenCode Go writes a title, description and YouTube tags from the video (frames, titles, voice
// lines) and live data (YouTube search suggestions, today's Google Trends). Everything is editable, saved with the
// project, and has a Copy button for pasting into YouTube Studio.
import { useEffect, useRef, useState } from "react"
import { api, type ProviderSettings } from "../api"
import { waitJob } from "../events"
import * as ops from "../model/ops"
import { useEditor } from "../state/editor"

type Tag = { text: string; searched: boolean }
type Draft = {
  titles: string[]; description: string; tags: Tag[]; summary: string
  searches: { query: string; geo: string; suggestions: string[] }[]
  trends: { geo: string; items: { query: string; traffic: string }[] }[]
  trends_used: { query: string; traffic: string }[]; collected_at: string; frames_used: number; model: string
}

const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z")

function CopyButton({ text, label = "Copy", testid }: { text: string; label?: string; testid?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button disabled={!text} data-testid={testid} onClick={() => {
      void navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) })
    }}>{done ? "Copied ✓" : label}</button>
  )
}

export function UploadDetails({ onClose }: { onClose: () => void }) {
  const doc = useEditor((s) => s.doc)!
  const { apply, flush } = useEditor.getState()
  const ref = useRef<HTMLDialogElement>(null)
  const pm = doc.publish_meta ?? {}
  const [settings, setSettings] = useState<ProviderSettings | null>(null)
  const [notes, setNotes] = useState("")
  const [draft, setDraft] = useState<Draft | null>(null)
  const [title, setTitle] = useState(pm.title_drafts?.[0]?.text ?? "")
  const [description, setDescription] = useState(pm.description ?? "")
  const [tags, setTags] = useState((pm.tags ?? []).join(", "))
  const [progress, setProgress] = useState<{ stage: string; pct: number } | null>(null)
  const [error, setError] = useState("")
  const tagList = tags.split(",").map((t) => t.trim()).filter(Boolean)
  const tagChars = tagList.join(",").length
  const dirty = title !== (pm.title_drafts?.[0]?.text ?? "") || description !== (pm.description ?? "") ||
    tagList.join(",") !== (pm.tags ?? []).join(",")

  useEffect(() => {
    const d = ref.current
    d?.showModal()
    return () => d?.close()
  }, [])
  useEffect(() => { void api.providers().then(setSettings).catch((e) => setError((e as Error).message)) }, [])
  // Show the last generated draft for this project again (the job result is kept).
  useEffect(() => {
    let live = true
    void api.jobs(doc.id).then(({ jobs }) => {
      const last = jobs.find((j) => j.kind === "publish_draft" && j.status === "done" && j.result)
      if (live && last) setDraft(last.result as unknown as Draft)
    }).catch(() => undefined)
    return () => { live = false }
  }, [doc.id])

  async function generate() {
    setError("")
    setProgress({ stage: "Saving the project", pct: 0 })
    try {
      if (!await flush()) throw new Error(useEditor.getState().saveError ?? "Save the project first.")
      const { job_id } = await api.draftPublish(doc.id, useEditor.getState().baseRevision, notes)
      const next = await waitJob<Draft>(job_id, (pct, stage) => setProgress({ stage, pct }))
      setDraft(next)
      setTitle(next.titles[0] ?? "")
      setDescription(next.description)
      setTags(next.tags.map((t) => t.text).join(", "))
      apply((d) => {
        for (const t of [...next.titles].reverse()) ops.setPublishMeta(d, { title: t, titleKind: "editorial", at: now() })
        ops.setPublishMeta(d, { description: next.description, tags: next.tags.map((t) => t.text), at: now() })
      })
    } catch (e) { setError((e as Error).message) } finally { setProgress(null) }
  }

  function save() {
    apply((d) => ops.setPublishMeta(d, { title, titleKind: draft?.titles.includes(title) ? "editorial" : "user",
      description, tags: tagList, at: now() }))
  }

  const canDraft = settings?.opencode_configured && settings.opencode_model
  const busy = !!progress
  return (
    <dialog ref={ref} className="modal-box upload-dialog" aria-labelledby="upload-title" data-testid="upload-dialog"
      onCancel={(e) => { e.preventDefault(); if (!busy) { if (dirty) save(); onClose() } }}>
      <div className="modal-head"><h2 id="upload-title">Upload details</h2>
        <button onClick={() => { if (dirty) save(); onClose() }} disabled={busy}>Close</button></div>
      <p className="hint">OpenCode Go watches sampled frames, reads your titles and voiceover, and checks what people
        search on YouTube and what's trending on Google today in your audience's country. Review everything before
        you upload.</p>
      <label className="intro-field">What should it know? (optional)
        <input type="text" value={notes} maxLength={500} disabled={busy} placeholder="e.g. the balloon hits the horse at the end"
          onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="row">
        <button className={draft ? "" : "primary"} onClick={() => void generate()} disabled={!canDraft || busy}
          data-testid="generate-upload">{draft ? "Write again with OpenCode" : "Write with OpenCode"}</button>
        {canDraft && <span className="hint">{settings.opencode_model}</span>}
        {settings && !canDraft && <a href="#/settings" target="_blank" rel="noopener">Set up OpenCode Go</a>}
      </div>
      {progress && <div className="intro-progress" role="status">
        <progress value={progress.pct} max={100} aria-label="Upload details progress" /><span>{progress.stage}</span></div>}
      {error && <p role="alert" className="error-text">{error}</p>}

      <section className="upload-fields">
        <div className="row between"><h3>Title</h3><CopyButton text={title} testid="copy-title" /></div>
        <input type="text" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} disabled={busy}
          aria-label="Title" data-testid="upload-title" />
        <div className="hint">{title.length}/100{title.length > 70 ? " · long titles get cut off in the Shorts feed" : ""}</div>
        {draft && draft.titles.length > 1 && <div className="title-options">
          {draft.titles.map((t) => <button key={t} className={t === title ? "on" : ""} onClick={() => setTitle(t)}
            disabled={busy} data-testid="title-option">{t}</button>)}
        </div>}

        <div className="row between"><h3>Description</h3><CopyButton text={description} testid="copy-description" /></div>
        <textarea rows={6} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)}
          disabled={busy} aria-label="Description" data-testid="upload-description" />

        <div className="row between"><h3>Tags</h3><CopyButton text={tagList.join(", ")} testid="copy-tags" /></div>
        <textarea rows={3} value={tags} onChange={(e) => setTags(e.target.value)} disabled={busy}
          aria-label="Tags, separated by commas" data-testid="upload-tags" />
        <div className={`hint ${tagChars > 500 ? "error-text" : ""}`}>{tagList.length} tags · {tagChars}/500 characters
          {draft && ` · ${draft.tags.filter((t) => t.searched).length} match real YouTube searches`}</div>
      </section>

      {draft && <details className="upload-sources">
        <summary>What it was based on</summary>
        <p><strong>What the video shows:</strong> {draft.summary}</p>
        <p className="hint">{draft.frames_used} frame{draft.frames_used === 1 ? "" : "s"} sent to {draft.model}. Search
          data collected {new Date(draft.collected_at).toLocaleString()}.</p>
        <p><strong>YouTube search suggestions</strong> <span className="hint">(what people type into YouTube search;
          a hint of what's searched in that country, not exact volumes)</span></p>
        <ul>{draft.searches.map((s) => <li key={s.query}><em>{s.query}</em> ({s.geo}): {s.suggestions.join(", ") || "none"}</li>)}</ul>
        <p><strong>Google trending searches today</strong> <span className="hint">(Google Trends; used only if related to
          the video)</span></p>
        {draft.trends.map((t) => <p key={t.geo} className="hint">{t.geo}: {t.items.map((i) => i.query).join(", ") || "unavailable"}</p>)}
        <p>{draft.trends_used.length ? `Used: ${draft.trends_used.map((t) => `${t.query} (${t.traffic} searches)`).join(", ")}`
          : "None of today's trends were related to this video, so none were used."}</p>
      </details>}

      <div className="row end">
        <button className="primary" onClick={save} disabled={!dirty || busy} data-testid="save-upload">
          {dirty ? "Save changes" : "Saved with the project"}</button>
      </div>
    </dialog>
  )
}
