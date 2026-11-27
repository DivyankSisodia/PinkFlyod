import { useEffect, useState } from "react"
import { Editor } from "./editor/Editor"
import { ActivityPage } from "./home/Activity"
import { AISettingsPage } from "./home/AISettings"
import { Home } from "./home/Home"
import { GameplayLibraryPage } from "./library/GameplayLibrary"

type Route = { page: "home"; draftId?: string } | { page: "editor"; id: string } | { page: "gameplay" }
  | { page: "settings" } | { page: "activity"; jobId?: string }
function route(): Route {
  const hash = location.hash
  const m = hash.match(/^#\/p\/(prj_[0-9A-Za-z]+)/)
  if (m) return { page: "editor", id: m[1] }
  if (hash.startsWith("#/library/gameplay")) return { page: "gameplay" }
  if (hash === "#/settings") return { page: "settings" }
  const activity = hash.match(/^#\/activity(?:\/(job_[0-9A-Za-z]+))?$/)
  if (activity) return { page: "activity", jobId: activity[1] }
  return { page: "home", draftId: hash.match(/^#\/draft\/(job_[0-9A-Za-z]+)$/)?.[1] }
}

export function navigate(hash: string) {
  location.hash = hash
}

export function App() {
  const [r, setR] = useState(route())
  useEffect(() => {
    const on = () => setR(route())
    window.addEventListener("hashchange", on)
    return () => window.removeEventListener("hashchange", on)
  }, [])
  if (r.page === "editor") return <Editor key={r.id} projectId={r.id} />
  if (r.page === "gameplay") return <GameplayLibraryPage />
  if (r.page === "settings") return <AISettingsPage />
  if (r.page === "activity") return <ActivityPage jobId={r.jobId} />
  return <Home draftId={r.draftId} />
}
