import type {
  Checkpoint, GameplayClip, Job, Project, ProjectSummary, RenderRecord, Segment, Source, Take, Timeline, VoiceOption,
} from "./model/types"

let token = ""

export class ApiError extends Error {
  constructor(message: string, public status: number, public body: Record<string, unknown> = {}) {
    super(message)
  }
}

export async function initSession(): Promise<void> {
  const r = await fetch("/api/session")
  token = (await r.json()).token
}

export const sessionToken = () => token

async function call<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Studio-Token": token }
  if (body !== undefined) headers["Content-Type"] = "application/json"
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), ...init })
  if (!r.ok) {
    let data: Record<string, unknown> = {}
    try { data = await r.json() } catch { /* not JSON */ }
    throw new ApiError(String(data.detail ?? `${r.status} ${r.statusText}`), r.status, data)
  }
  const type = r.headers.get("content-type") ?? ""
  return (type.includes("application/json") ? r.json() : r.blob()) as Promise<T>
}

export type Ownership = "own" | "licensed" | "third_party" | "unknown"
export type VoiceProvider = "edge" | "system" | "elevenlabs"
export type AIProvider = "opencode" | "elevenlabs"
export type ProviderOption = { id: string; name: string }
export type ProviderSettings = {
  opencode_configured: boolean; elevenlabs_configured: boolean; opencode_model: string;
  elevenlabs_model: string; elevenlabs_voice: string
}

export const api = {
  health: () => call<{ ok: boolean; version: string; ffmpeg: string; data_dir: string }>("GET", "/api/health"),
  dialog: (mode: "open_files" | "open_file" | "open_folder", title: string) =>
    call<{ paths: string[] }>("POST", "/api/dialog", { mode, title }),
  listProjects: () => call<{ projects: ProjectSummary[] }>("GET", "/api/projects"),
  createProject: (paths: string[], preset: "quick_short" | "blank", ownership: Ownership, country: string) =>
    call<{ project: Project; import_errors: { path: string; error: string }[] }>("POST", "/api/projects",
      { paths, preset, ownership, country }),
  getProject: (id: string) =>
    call<{ project: Project; read_only: boolean; statuses: Record<string, string>; renders: RenderRecord[] }>(
      "GET", `/api/projects/${id}`),
  saveProject: (id: string, project: Project, baseRevision: number, keepalive = false) =>
    call<{ revision: number; updated_at: string }>("PUT", `/api/projects/${id}`,
      { base_revision: baseRevision, project }, keepalive ? { keepalive: true } : {}),
  addSources: (id: string, paths: string[], ownership: Ownership) =>
    call<{ sources: Record<string, Source>; errors: { path: string; error: string }[] }>(
      "POST", `/api/projects/${id}/sources`, { paths, ownership }),
  resolve: (project: Project, signal?: AbortSignal) =>
    call<Timeline>("POST", "/api/resolve", { project }, { signal }),
  exactFrame: (id: string, project: Project, t: number) =>
    call<Blob>("POST", `/api/projects/${id}/frame`, { project, t }),
  render: (id: string, revision: number) => call<{ job_id: string }>("POST", `/api/projects/${id}/render`, { revision }),
  renders: (id: string) => call<{ renders: RenderRecord[] }>("GET", `/api/projects/${id}/renders`),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  jobs: (projectId?: string) => call<{ jobs: Job[] }>("GET", projectId ? `/api/jobs?project_id=${encodeURIComponent(projectId)}` : "/api/jobs"),
  checkpoints: (id: string) => call<{ checkpoints: Checkpoint[] }>("GET", `/api/jobs/${id}/checkpoints`),
  cancelJob: (id: string) => call<{ cancelled: boolean }>("POST", `/api/jobs/${id}/cancel`),
  render_: (id: string) => call<RenderRecord>("GET", `/api/renders/${id}`),
  openRender: (id: string) => call("POST", `/api/renders/${id}/open`),
  revealRender: (id: string) => call("POST", `/api/renders/${id}/reveal`),
  deleteRender: (id: string) =>
    call<{ ok: boolean; freed_bytes: number; recycle_bin: boolean }>("DELETE", `/api/renders/${id}`),
  pruneRenders: (pid: string, keep: number) =>
    call<{ ok: boolean; deleted: number; freed_bytes: number; recycle_bin: boolean }>(
      "POST", `/api/projects/${pid}/renders/prune`, { keep }),
  deletePreview: (pid: string) =>
    call<{
      title: string; exports: number; exports_bytes: number; media_files: string[]; media_bytes: number;
      total_bytes: number
    }>("GET", `/api/projects/${pid}/delete-preview`),
  deleteProject: (pid: string) =>
    call<{ ok: boolean; freed_bytes: number; recycle_bin: boolean }>("DELETE", `/api/projects/${pid}`),
  mediaInfo: (sid: string) => call<{ proxy_state: string; has_poster: boolean; has_filmstrip: boolean; exists: boolean }>(
    "GET", `/api/media/${sid}/info`),
  relinkCheck: (path: string, source: Source) =>
    call<{
      ok: boolean; error?: string; identical?: boolean; compatible?: boolean; reasons?: string[];
      fingerprint?: Source["fingerprint"]; project_path?: string
    }>("POST", "/api/relink/check", { path, source }),
  relinkSearch: (folder: string, sources: Record<string, Source>) =>
    call<{ found: Record<string, { path: string; project_path: string; fingerprint: Source["fingerprint"] }> }>(
      "POST", "/api/relink/search", { folder, sources }),

  // ── Phase 2 ──────────────────────────────────────────────────────────
  createRanking: (paths: string[], ownership: Ownership, country: string, direction: "descending" | "ascending") =>
    call<{ project: Project; import_errors: { path: string; error: string }[] }>("POST", "/api/projects",
      { paths, preset: "ranking", ownership, country, direction }),
  createFromScript: (body: {
    kind: "script" | "reddit" | "ranking_list" | "blank"; text: string; title?: string | null; country: string
    reddit?: { community: string; title: string; source_url: string | null } | null; gameplay_clip_id?: string | null
    voice_provider?: VoiceProvider; from_topic?: boolean
  }) => call<{ project: Project; usernames_replaced: number }>("POST", "/api/projects/script", body),
  createOverGameplay: (paths: string[], gameplayClipId: string, layout: "split" | "pip", ownership: Ownership,
    country: string) =>
    call<{ project: Project; import_errors: { path: string; error: string }[] }>("POST", "/api/projects/gameplay",
      { paths, gameplay_clip_id: gameplayClipId, layout, ownership, country }),
  voices: (provider: VoiceProvider) =>
    call<{ provider: string; online: boolean; voices: VoiceOption[] }>("GET", `/api/voices?provider=${provider}`),
  generateTake: (pid: string, body: {
    scene_id: string; text: string; provider: string; voice_id: string; rate_pct: number; model_id?: string
  }) =>
    call<{ job_id: string }>("POST", `/api/projects/${pid}/takes`, body),
  uploadTake: (pid: string, sceneId: string, text: string, file: Blob, filename: string, method: "recorded" | "imported") => {
    const form = new FormData()
    form.append("file", file, filename)
    form.append("scene_id", sceneId)
    form.append("text", text)
    form.append("method", method)
    return call<{ scene_id: string; take: Take }>("POST", `/api/projects/${pid}/takes/upload`, undefined,
      { body: form })
  },
  speedTake: (pid: string, body: {
    scene_id: string; text: string; audio_name: string; speed: number; words: Take["words"]; timing: Take["timing"]
  }) => call<{ scene_id: string; take: Take; speed: number }>("POST", `/api/projects/${pid}/takes/speed`, body),
  gameplay: () => call<{ clips: GameplayClip[] }>("GET", "/api/gameplay"),
  importUrls: (body: {
    youtube?: string; instagram?: string; gameplay?: string; tags?: string[];
    layout?: "split" | "pip"; country?: string
  }) => call<{ job_id: string }>("POST", "/api/urls/import", body),
  providers: () => call<ProviderSettings>("GET", "/api/providers"),
  updateProviders: (patch: Partial<Omit<ProviderSettings, "opencode_configured" | "elevenlabs_configured">> &
  { opencode_key?: string; elevenlabs_key?: string }) => call<ProviderSettings>("PUT", "/api/providers", patch),
  providerOptions: (provider: AIProvider, kind: "models" | "voices" = "models") =>
    call<{ options: ProviderOption[] }>("GET", `/api/providers/${provider}/options?kind=${kind}`),
  checkOpenCodeAccess: () => call<{ ok: boolean }>("GET", "/api/providers/opencode/access"),
  draftScript: (topic: string, country: string) => call<{ job_id: string }>("POST", "/api/drafts/topic", { topic, country }),
  draftPublish: (projectId: string, revision: number, notes: string) =>
    call<{ job_id: string }>("POST", `/api/projects/${projectId}/publish-draft`, { revision, notes }),
  draftIntro: (projectId: string, revision: number, notes: string) =>
    call<{ job_id: string }>("POST", `/api/projects/${projectId}/intro-draft`, { revision, notes }),
  addGameplay: (paths: string[], tags: string[]) =>
    call<{ clips: GameplayClip[]; errors: { path: string; error: string }[] }>("POST", "/api/gameplay", { paths, tags }),
  sampleGameplay: () => call<{ job_id: string }>("POST", "/api/gameplay/sample"),
  editGameplay: (id: string, patch: { display_name?: string; tags?: string[] }) =>
    call<GameplayClip>("PATCH", `/api/gameplay/${id}`, patch),
  deleteGameplay: (id: string) => call<{ ok: boolean }>("DELETE", `/api/gameplay/${id}`),
  pickGameplay: (id: string, seconds: number, projectId: string | null, sceneId: string | null) =>
    call<GameplayPick>("POST", `/api/gameplay/${id}/pick`, { seconds, project_id: projectId, scene_id: sceneId }),
  sampleMusic: (pid: string) => call<{ sources: Record<string, Source> }>("POST", `/api/projects/${pid}/music/sample`),
  previewClip: (pid: string, project: Project, sceneId: string, t0: number, t1: number) =>
    call<Blob>("POST", `/api/projects/${pid}/preview-clip`, { project, scene_id: sceneId, t0, t1 }),
}

export interface GameplayPick {
  source_id: string
  source: Source
  segment_id: string
  segment: Segment
  loop_needed: boolean
  overlap_s: number
}

export const rasterUrl = (rid: string) => `/api/raster/${rid}.png`
export const takeUrl = (audioPath: string) => `/api/takes/${audioPath.split("/").pop() ?? ""}`
export const sfxUrl = (name: string) => name.startsWith("src_") ? mediaUrl(name, "original") : `/api/sfx/${name}`

export const mediaUrl = (sid: string, variant: "preview" | "original" = "preview", bust = "") =>
  `/api/media/${sid}/file?variant=${variant}${bust ? `&v=${bust}` : ""}`
export const posterUrl = (sid: string, bust = "") => `/api/media/${sid}/poster${bust ? `?v=${bust}` : ""}`
export const filmstripUrl = (sid: string, bust = "") => `/api/media/${sid}/filmstrip${bust ? `?v=${bust}` : ""}`

/** Upload one browser file into the app's imports folder, reporting progress. Returns its path on disk. */
export function uploadFile(file: File, onProgress: (fraction: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", "/api/uploads")
    xhr.setRequestHeader("X-Studio-Token", token)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText || "{}")
      if (xhr.status >= 200 && xhr.status < 300) resolve(data.path)
      else reject(new ApiError(data.detail ?? `Upload failed (${xhr.status})`, xhr.status, data))
    }
    xhr.onerror = () => reject(new ApiError("Upload failed.", 0))
    const form = new FormData()
    form.append("file", file)
    xhr.send(form)
  })
}
