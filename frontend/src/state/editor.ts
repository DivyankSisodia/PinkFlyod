// The one owner of the open project: edits (each an undo step), autosave with revision checks, and the
// resolved timeline the preview draws from.
import { produce, type Draft } from "immer"
import { create } from "zustand"
import { ApiError, api } from "../api"
import type { Project, RenderRecord, Timeline } from "../model/types"

export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict" | "readonly"
const AUTOSAVE_MS = 800
const UNDO_LIMIT = 200

interface EditorState {
  projectId: string | null
  doc: Project | null
  baseRevision: number
  saveState: SaveState
  saveError: string | null
  past: Project[]
  future: Project[]
  gestureStart: Project | null
  statuses: Record<string, string>
  renders: RenderRecord[]
  timeline: Timeline | null
  timelineError: string | null
  selectedSceneId: string | null
  playhead: number
  mediaVersion: Record<string, number>
  /** Which layer of the selected scene the inspector's framing controls act on. */
  selectedSlot: "primary" | "secondary"
  /** Voice takes being made, by scene id. */
  takeJobs: Record<string, { pct: number; stage: string; error?: string }>

  load: (id: string) => Promise<void>
  close: () => void
  apply: (recipe: (d: Draft<Project>) => void, opts?: { gesture?: boolean }) => void
  beginGesture: () => void
  endGesture: () => void
  undo: () => void
  redo: () => void
  flush: () => Promise<boolean>
  select: (sceneId: string | null) => void
  setPlayhead: (t: number) => void
  setStatuses: (s: Record<string, string>) => void
  setRenders: (r: RenderRecord[]) => void
  bumpMedia: (sourceId: string) => void
  selectLayer: (slot: "primary" | "secondary") => void
  setTakeJob: (sceneId: string, job: { pct: number; stage: string; error?: string } | null) => void
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
let resolveTimer: ReturnType<typeof setTimeout> | null = null
let resolveAbort: AbortController | null = null
let saving: Promise<boolean> | null = null

export const useEditor = create<EditorState>((set, get) => {
  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => void get().flush(), AUTOSAVE_MS)
  }

  function scheduleResolve() {
    if (resolveTimer) clearTimeout(resolveTimer)
    resolveTimer = setTimeout(async () => {
      const doc = get().doc
      if (!doc) return
      resolveAbort?.abort()
      resolveAbort = new AbortController()
      try {
        const timeline = await api.resolve(doc, resolveAbort.signal)
        if (get().doc === doc || get().projectId === doc.id) set({ timeline, timelineError: null })
      } catch (e) {
        if ((e as Error).name !== "AbortError") set({ timelineError: (e as Error).message })
      }
    }, 120)
  }

  function changed(next: Project, pushHistory: Project | null) {
    const s = get()
    const past = pushHistory ? [...s.past, pushHistory].slice(-UNDO_LIMIT) : s.past
    set({
      doc: next, past, future: pushHistory ? [] : s.future,
      saveState: s.saveState === "readonly" || s.saveState === "conflict" ? s.saveState : "dirty"
    })
    scheduleResolve()
    if (get().saveState === "dirty") scheduleSave()
  }

  return {
    projectId: null, doc: null, baseRevision: 0, saveState: "saved", saveError: null, past: [], future: [],
    gestureStart: null, statuses: {}, renders: [], timeline: null, timelineError: null, selectedSceneId: null,
    playhead: 0, mediaVersion: {}, selectedSlot: "primary", takeJobs: {},

    async load(id) {
      const r = await api.getProject(id)
      set({
        projectId: id, doc: r.project, baseRevision: r.project.revision,
        saveState: r.read_only ? "readonly" : "saved", saveError: null, past: [], future: [], gestureStart: null,
        statuses: r.statuses, renders: r.renders, timeline: null,
        selectedSceneId: r.project.scenes[0]?.id ?? null, playhead: 0, selectedSlot: "primary",
        takeJobs: {}
      })
      scheduleResolve()
    },

    close() {
      if (saveTimer) clearTimeout(saveTimer)
      set({ projectId: null, doc: null, timeline: null, past: [], future: [] })
    },

    apply(recipe, opts = {}) {
      const s = get()
      if (!s.doc || s.saveState === "readonly" || s.saveState === "conflict") return
      const next = produce(s.doc, recipe)
      if (next === s.doc) return
      changed(next, opts.gesture || s.gestureStart ? null : s.doc)
    },

    beginGesture() {
      const doc = get().doc
      if (doc && !get().gestureStart) set({ gestureStart: doc })
    },

    endGesture() {
      const { gestureStart, doc, past } = get()
      if (!gestureStart) return
      set({ gestureStart: null })
      if (doc !== gestureStart) set({ past: [...past, gestureStart].slice(-UNDO_LIMIT), future: [] })
    },

    undo() {
      const { past, doc, future } = get()
      if (!past.length || !doc) return
      set({ past: past.slice(0, -1), future: [doc, ...future] })
      changed(past[past.length - 1], null)
    },

    redo() {
      const { past, doc, future } = get()
      if (!future.length || !doc) return
      set({ past: [...past, doc], future: future.slice(1) })
      changed(future[0], null)
    },

    async flush() {
      if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
      if (saving) await saving
      const s = get()
      if (!s.doc || !s.projectId) return false
      if (s.saveState === "saved") return true
      if (s.saveState === "readonly" || s.saveState === "conflict") return false
      const doc = s.doc
      set({ saveState: "saving" })
      saving = (async () => {
        try {
          const r = await api.saveProject(s.projectId as string, doc, s.baseRevision)
          const now = get()
          // Record the new revision on whatever the document is now (edits may have happened meanwhile).
          const stamp = (p: Project) => ({ ...p, revision: r.revision, updated_at: r.updated_at })
          set({
            baseRevision: r.revision, doc: now.doc ? stamp(now.doc) : now.doc, saveError: null,
            saveState: now.doc === doc ? "saved" : "dirty"
          })
          if (get().saveState === "dirty") scheduleSave()
          return true
        } catch (e) {
          const err = e as ApiError
          if (err.status === 409) set({ saveState: "conflict", saveError: err.message })
          else if (err.status === 423) set({ saveState: "readonly", saveError: err.message })
          else { set({ saveState: "error", saveError: err.message }); scheduleSave() }
          return false
        } finally {
          saving = null
        }
      })()
      return saving
    },

    select: (sceneId) => set((s) => ({
      selectedSceneId: sceneId,
      selectedSlot: sceneId === s.selectedSceneId ? s.selectedSlot : "primary"
    })),
    selectLayer: (slot) => set({ selectedSlot: slot }),
    setTakeJob: (sceneId, job) => set((s) => {
      const next = { ...s.takeJobs }
      if (job) next[sceneId] = job
      else delete next[sceneId]
      return { takeJobs: next }
    }),
    setPlayhead: (t) => set({ playhead: Math.max(0, t) }),
    setStatuses: (statuses) => { set({ statuses }); scheduleResolve() },
    setRenders: (renders) => set({ renders }),
    bumpMedia: (sid) => set((s) => ({ mediaVersion: { ...s.mediaVersion, [sid]: (s.mediaVersion[sid] ?? 0) + 1 } })),
  }
})

/** Last-chance save when the tab closes (fetch keepalive survives unload). */
export function saveOnUnload(): void {
  const s = useEditor.getState()
  if (s.doc && s.projectId && (s.saveState === "dirty" || s.saveState === "error")) {
    void api.saveProject(s.projectId, s.doc, s.baseRevision, true).catch(() => undefined)
  }
}
