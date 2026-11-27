import { api, sessionToken } from "./api"

export type StudioEvent =
  | { type: "hello"; version: string }
  | { type: "job.queued" | "job.cancelled"; job_id: string; kind: string; project_id: string | null }
  | { type: "job.progress"; job_id: string; kind: string; project_id: string | null; pct: number; stage: string }
  | { type: "job.done"; job_id: string; kind: string; project_id: string | null; result: Record<string, unknown> }
  | { type: "job.failed"; job_id: string; kind: string; project_id: string | null; error: string; detail?: Record<string, unknown> }
  | { type: "media.updated"; source_id: string; made?: string[]; proxy_state?: string }

type Listener = (e: StudioEvent) => void
const listeners = new Set<Listener>()
let socket: WebSocket | null = null
let retry = 500

export function connectEvents(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws"
  socket = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(sessionToken())}`)
  socket.onopen = () => { retry = 500 }
  socket.onmessage = (m) => {
    const e = JSON.parse(m.data) as StudioEvent
    listeners.forEach((l) => l(e))
  }
  socket.onclose = () => {
    socket = null
    setTimeout(connectEvents, retry)
    retry = Math.min(retry * 2, 8000)
  }
}

export function onEvent(l: Listener): () => void {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Resolve with a job's result when it finishes (live over the socket, with a status check in case it already did). */
export function waitJob<T = Record<string, unknown>>(jobId: string, onProgress?: (pct: number, stage: string) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (fn: () => void) => { if (!settled) { settled = true; off(); clearInterval(poll); fn() } }
    const off = onEvent((e) => {
      if (!("job_id" in e) || e.job_id !== jobId) return
      if (e.type === "job.progress") onProgress?.(e.pct, e.stage)
      else if (e.type === "job.done") finish(() => resolve(e.result as T))
      else if (e.type === "job.failed") finish(() => reject(new Error(e.error)))
      else if (e.type === "job.cancelled") finish(() => reject(new Error("Cancelled.")))
    })
    const check = async () => {
      try {
        const j = await api.job(jobId)
        if (j.status === "done") finish(() => resolve(j.result as T))
        else if (j.status === "failed") finish(() => reject(new Error(j.error ?? "Failed.")))
        else if (j.status === "cancelled") finish(() => reject(new Error("Cancelled.")))
        else if (!settled && j.status === "running" && socket?.readyState !== WebSocket.OPEN) onProgress?.(j.pct, j.stage)
      } catch { /* the socket will tell us */ }
    }
    const poll = setInterval(check, 3000)
    void check()
  })
}
