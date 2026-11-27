// The gameplay library: your own (or licensed) background clips, tagged, with how often each was used. Picks are
// random stretches that don't repeat earlier picks while the clip has unused room.
import { useCallback, useEffect, useState } from "react"
import { api } from "../api"
import { onEvent, waitJob } from "../events"
import { StudioShell } from "../home/StudioShell"
import type { GameplayClip } from "../model/types"
import { useEditor } from "../state/editor"
import { Thumb } from "../ui/Thumb"
import { clock } from "../ui/format"

export function useGameplayClips() {
  const [clips, setClips] = useState<GameplayClip[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    api.gameplay().then((r) => { setClips(r.clips); setError(null) }).catch((e) => setError((e as Error).message))
  }, [])
  useEffect(reload, [reload])
  // Posters are made in the background; show them when they are ready.
  useEffect(() => {
    const off = onEvent((e) => {
      if (e.type === "media.updated") useEditor.getState().bumpMedia(e.source_id)
      if (e.type === "job.done" && e.kind === "url_import" && e.result.clip_id) reload()
    })
    return () => { off() }
  }, [reload])
  return { clips, error, reload }
}

export function GameplayList({ onUse, useLabel = "Use" }: { onUse?: (clip: GameplayClip) => void; useLabel?: string }) {
  const { clips, error, reload } = useGameplayClips()
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [tags, setTags] = useState("")
  const [url, setUrl] = useState("")
  const [importJob, setImportJob] = useState<string | null>(null)

  function newTags() { return tags.split(",").map((tag) => tag.trim()).filter(Boolean) }

  async function addOwn() {
    setMessage(null)
    setBusy("Choose clips…")
    try {
      const { paths } = await api.dialog("open_files", "Add gameplay clips (your own or licensed)")
      if (!paths.length) return
      setBusy("Adding…")
      const r = await api.addGameplay(paths, newTags())
      if (r.errors.length) setMessage(r.errors.map((e) => e.error).join(" "))
      reload()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function addFromLink() {
    setMessage(null)
    setImportJob(null)
    setBusy("Queuing the gameplay download…")
    try {
      const { job_id } = await api.importUrls({ gameplay: url.trim(), tags: newTags() })
      setImportJob(job_id)
      await waitJob(job_id, (pct, stage) => setBusy(`${stage} · ${Math.round(pct)}%`))
      setUrl("")
      reload()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function addSample() {
    setMessage(null)
    setBusy("Generating a 60 s sample clip…")
    try {
      const { job_id } = await api.sampleGameplay()
      await waitJob(job_id, (pct, stage) => setBusy(`${stage} ${Math.round(pct)}%`))
      reload()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function retag(clip: GameplayClip, value: string) {
    await api.editGameplay(clip.id, { tags: value.split(",").map((t) => t.trim()).filter(Boolean) })
    reload()
  }

  async function remove(clip: GameplayClip) {
    if (!confirm(`Remove “${clip.display_name}” and its local library file? Any project using it will need a replacement.`)) return
    await api.deleteGameplay(clip.id)
    reload()
  }

  return (
    <div className="gameplay-list" data-testid="gameplay-list">
      <div className="row wrap">
        <button className="primary" onClick={() => void addOwn()} disabled={!!busy} data-testid="gameplay-add">+ Add clips…</button>
        <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="tags for new clips (comma separated)"
          aria-label="Tags for new clips" />
        <button onClick={() => void addSample()} disabled={!!busy} data-testid="gameplay-sample">Generate a sample clip</button>
      </div>
      {!onUse && <form className="studio-gameplay-import" onSubmit={(e) => { e.preventDefault(); void addFromLink() }}>
        <label htmlFor="gameplay-library-url">Gameplay video link</label>
        <div className="studio-setting-row">
          <input id="gameplay-library-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="Public YouTube, Reel, MP4, or WebM link" disabled={!!busy} required />
          <button type="submit" disabled={!!busy || !url.trim()}>Download to library</button>
        </div>
      </form>}
      <p className="hint">Use your own recordings or footage you have a licence for. The sample is a generated
        animation, free to use, for trying layouts.</p>
      {busy && <p className="hint" data-testid="gameplay-busy" role="status">{busy}</p>}
      {importJob && <a className="hint" href={`#/activity/${importJob}`}>View download checkpoints</a>}
      {(message || error) && <p className="error-text">{message ?? error}</p>}
      {clips === null ? <p className="hint">Loading…</p> : clips.length === 0 ? (
        <p className="hint" data-testid="gameplay-empty">The library is empty.</p>
      ) : (
        <ul className="clips">
          {clips.map((c) => (
            <li key={c.id} className={`clip ${c.exists ? "" : "missing"}`} data-testid="gameplay-clip">
              <div className="clip-thumb">{c.exists && <Thumb sourceId={c.id} />}</div>
              <div className="clip-meta">
                <strong>{c.display_name}</strong>
                <span>{clock(c.fingerprint.duration_s ?? 0, false)} · {c.fingerprint.width}×{c.fingerprint.height}
                  {c.sample ? " · generated sample" : c.downloaded ? " · downloaded" : ""} · used {c.uses}×{c.exists ? "" : " · file missing"}</span>
                <input defaultValue={c.tags.join(", ")} placeholder="tags" aria-label="Tags"
                  onBlur={(e) => e.target.value !== c.tags.join(", ") && void retag(c, e.target.value)} />
              </div>
              <div className="clip-actions">
                {onUse && <button className="primary" disabled={!c.exists} onClick={() => onUse(c)} data-testid="gameplay-use">{useLabel}</button>}
                <button onClick={() => void remove(c)} title="Remove from the library">Remove</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function GameplayLibraryPage() {
  return (
    <StudioShell page="gameplay">
      <header className="studio-intro">
        <h1>Gameplay library</h1>
        <p>Keep background clips on this device and reuse them across Shorts.</p>
      </header>
      <section className="studio-card studio-config" aria-label="Gameplay clips"><GameplayList /></section>
    </StudioShell>
  )
}
