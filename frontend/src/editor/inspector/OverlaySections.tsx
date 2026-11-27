// A scene's captions (word-synced from its voice, or timed by hand) and overlays (rank badge, label, Reddit card,
// text). Everything here belongs to this scene, so it moves with it when scenes are reordered.
import { useState } from "react"
import * as ops from "../../model/ops"
import type { Scene } from "../../model/types"
import { useEditor } from "../../state/editor"
import { Section, Slider, TextField, secFmt } from "./controls"

const CAPTION_MODES = [
  { value: "inherit", label: "Project default" },
  { value: "narration_words", label: "From the voice, word by word" },
  { value: "manual", label: "Typed, with times" },
  { value: "off", label: "Off" },
] as const

export function CaptionsSection({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const timeline = useEditor((s) => s.timeline)
  const playhead = useEditor((s) => s.playhead)
  const { apply } = useEditor.getState()
  const [editing, setEditing] = useState<number | null>(null)
  const resolved = timeline?.scenes.find((s) => s.id === scene.id)
  const words = resolved?.narration?.words ?? []
  const local = resolved ? Math.max(0, playhead - resolved.start_s) : 0
  const mode = scene.captions.mode
  const effective = !doc.captions.enabled ? "off" : mode === "inherit" ? doc.captions.default_mode : mode
  return (
    <Section title="Captions" testid="captions-section" open={effective !== "off" || mode !== "inherit"}>
      <label className="slider"><span>Captions</span>
        <select value={mode} data-testid="caption-mode"
          onChange={(e) => apply((d) => ops.setCaptionMode(d, scene.id, e.target.value as Scene["captions"]["mode"]))}>
          {CAPTION_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </label>
      {!doc.captions.enabled && <p className="hint">Captions are off for the project (Project → Captions).</p>}
      {effective === "narration_words" && (
        words.length ? (
          <>
            <div className="hint">Click a word to fix how it's shown (the timing stays).</div>
            <div className="words" data-testid="caption-words">
              {words.map(([w, a], i) => editing === i ? (
                <input key={i} autoFocus defaultValue={w} className="word-edit" data-testid="word-edit"
                  onBlur={(e) => { apply((d) => ops.setWordEdit(d, scene.id, i, e.target.value)); setEditing(null) }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditing(null) }} />
              ) : (
                <button key={i} className={`word ${scene.captions.word_edits.some((x) => x.index === i) ? "edited" : ""}`}
                  title={`${a.toFixed(2)} s`} onClick={() => setEditing(i)}>{w}</button>
              ))}
            </div>
          </>
        ) : <p className="hint">Captions appear once this scene has a voice.</p>
      )}
      {mode === "manual" && (
        <>
          {scene.captions.manual_cues.map((c, i) => (
            <div key={i} className="cue" data-testid="cue">
              <TextField value={c.text} label="Caption text" onCommit={(v) => apply((d) => ops.setCue(d, scene.id, i, { text: v }))} />
              <div className="row">
                <label>from <input type="number" step={0.1} min={0} value={c.start_s} aria-label="Start"
                  onChange={(e) => apply((d) => ops.setCue(d, scene.id, i, { start_s: Number(e.target.value) }))} /></label>
                <label>to <input type="number" step={0.1} min={0} value={c.end_s} aria-label="End"
                  onChange={(e) => apply((d) => ops.setCue(d, scene.id, i, { end_s: Number(e.target.value) }))} /></label>
                <button onClick={() => apply((d) => ops.removeCue(d, scene.id, i))} title="Remove">✕</button>
              </div>
            </div>
          ))}
          <button data-testid="add-cue" onClick={() => apply((d) => ops.addCue(d, scene.id, local, local + 1.5))}>
            + Caption at the playhead</button>
        </>
      )}
    </Section>
  )
}

export function OverlaysSection({ scene }: { scene: Scene }) {
  const doc = useEditor((s) => s.doc)!
  const { apply } = useEditor.getState()
  const rank = ops.ranks(doc)[scene.id]
  const ov = scene.overlays
  const card = ov.reddit_card
  const num = (v: string) => (v.trim() === "" ? null : Math.max(0, Math.round(Number(v))))
  return (
    <Section title="On screen" testid="overlays-section">
      {doc.ranking.enabled && (
        <label className="check">
          <input type="checkbox" checked={scene.rank.include} data-testid="rank-include"
            onChange={(e) => apply((d) => ops.setRankInclude(d, scene.id, e.target.checked))} />
          Counts in the ranking {rank !== undefined && <strong data-testid="rank-value">#{rank}</strong>}
        </label>
      )}
      <label className="check">
        <input type="checkbox" checked={ov.label.visible} data-testid="label-toggle"
          onChange={(e) => apply((d) => ops.setLabel(d, scene.id, { visible: e.target.checked }))} />
        Label
      </label>
      {ov.label.visible && (
        <TextField value={ov.label.text ?? ""} placeholder={scene.name} label="Label text" testid="label-text" maxLength={80}
          onCommit={(v) => apply((d) => ops.setLabel(d, scene.id, { text: v }))} />
      )}
      <label className="check">
        <input type="checkbox" checked={!!card} data-testid="reddit-toggle"
          onChange={(e) => apply((d) => ops.setRedditCard(d, scene.id, e.target.checked ? {} : null))} />
        Reddit-style post card
      </label>
      {card && (
        <div className="subgroup" data-testid="reddit-card">
          <TextField value={card.community} label="Community" placeholder="r/community" maxLength={60}
            onCommit={(v) => apply((d) => ops.setRedditCard(d, scene.id, { community: v.trim() || "r/stories" }))} />
          <TextField multiline value={card.title} label="Post title" placeholder="Post title" maxLength={300}
            onCommit={(v) => apply((d) => ops.setRedditCard(d, scene.id, { title: v }))} />
          <label className="slider"><span>Author</span>
            <select value={card.author.mode} data-testid="reddit-author"
              onChange={(e) => apply((d) => ops.setRedditCard(d, scene.id, { author: { mode: e.target.value as "hidden", name: card.author.name } }))}>
              <option value="hidden">hidden</option><option value="anonymized">shown as u/anonymous</option>
              <option value="shown">shown (their consent needed)</option>
            </select>
          </label>
          {card.author.mode === "shown" && (
            <TextField value={card.author.name ?? ""} label="Username" placeholder="u/name" maxLength={40}
              onCommit={(v) => apply((d) => ops.setRedditCard(d, scene.id, { author: { mode: "shown", name: v.trim() || null } }))} />
          )}
          <TextField value={card.source_url ?? ""} label="Link to the original post" placeholder="https://www.reddit.com/r/…"
            maxLength={300} onCommit={(v) => apply((d) => ops.setRedditCard(d, scene.id, { source_url: v.trim() || null }))} />
          <label className="check">
            <input type="checkbox" checked={card.show_metrics}
              onChange={(e) => apply((d) => ops.setRedditCard(d, scene.id, { show_metrics: e.target.checked }))} />
            Show votes and comments (only the numbers you type)
          </label>
          {card.show_metrics && (
            <div className="row">
              <label>Votes <input type="number" min={0} value={card.metrics.upvotes ?? ""} aria-label="Upvotes"
                onChange={(e) => apply((d) => ops.setRedditCard(d, scene.id, { metrics: { upvotes: num(e.target.value), comments: card.metrics.comments } }))} /></label>
              <label>Comments <input type="number" min={0} value={card.metrics.comments ?? ""} aria-label="Comments"
                onChange={(e) => apply((d) => ops.setRedditCard(d, scene.id, { metrics: { upvotes: card.metrics.upvotes, comments: num(e.target.value) } }))} /></label>
            </div>
          )}
          <div className="hint">The card shows until the voice finishes reading the title.</div>
        </div>
      )}
      {ov.texts.map((t) => (
        <div key={t.id} className="subgroup" data-testid="text-overlay">
          <div className="row between">
            <TextField value={t.text} label="Text" maxLength={200} onCommit={(v) => apply((d) => ops.setText(d, scene.id, t.id, { text: v }))} />
            <button onClick={() => apply((d) => ops.removeText(d, scene.id, t.id))} title="Remove text">✕</button>
          </div>
          <Slider label="Across" value={t.anchor.x} min={0} max={1} step={0.01} onChange={(v) => apply((d) => ops.setText(d, scene.id, t.id, { x: v }))} />
          <Slider label="Down" value={t.anchor.y} min={0} max={1} step={0.01} onChange={(v) => apply((d) => ops.setText(d, scene.id, t.id, { y: v }))} />
          <Slider label="From" value={t.start_s} min={0} max={30} step={0.1} fmt={secFmt}
            onChange={(v) => apply((d) => ops.setText(d, scene.id, t.id, { start_s: v }))} />
        </div>
      ))}
      <button onClick={() => apply((d) => ops.addText(d, scene.id))} data-testid="add-text">+ Text</button>
    </Section>
  )
}
