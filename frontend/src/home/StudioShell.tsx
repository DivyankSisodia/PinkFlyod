import { useEffect, type ReactNode } from "react"
import { WorkspaceIcon } from "./WorkspaceIcon"
import "./workspace.css"

type Page = "home" | "gameplay" | "settings" | "activity"

function jumpTo(id: string) {
  const target = document.getElementById(id)
  target?.focus({ preventScroll: true })
  target?.scrollIntoView({ block: "start" })
}

export function StudioShell({ page, children, onFilesDrop }: {
  page: Page; children: ReactNode; onFilesDrop?: (files: FileList) => void
}) {
  const labels = { home: "New short", gameplay: "Gameplay library", activity: "Activity", settings: "AI settings" }
  const hash = location.hash
  useEffect(() => {
    if (page !== "home") window.scrollTo(0, 0)
    else if (hash === "#/local" || hash.startsWith("#/draft/")) jumpTo("local-start")
    else if (hash === "#/recent") jumpTo("recent-projects")
    else window.scrollTo(0, 0)
  }, [page, hash])

  return (
    <div className="link-studio" onDragOver={(event) => {
      if (onFilesDrop && event.dataTransfer.types.includes("Files")) event.preventDefault()
    }} onDrop={(event) => {
      if (!onFilesDrop || !event.dataTransfer.files.length) return
      event.preventDefault()
      onFilesDrop(event.dataTransfer.files)
    }}>
      <aside className="studio-sidebar">
        <a className="studio-brand" href="#/" onClick={() => page === "home" && jumpTo("new-short")}>
          <span className="studio-mark"><WorkspaceIcon name="brand" size={23} /></span>
          <span>Shorts<span className="studio-brand-light"> Studio</span></span>
        </a>
        <nav className="studio-nav" aria-label="Workspace">
          <a href="#/" aria-current={page === "home" && hash !== "#/local" && hash !== "#/recent" ? "page" : undefined}
            onClick={() => page === "home" && jumpTo("new-short")}>
            <WorkspaceIcon name="add" size={18} /> New short
          </a>
          <a href="#/local" aria-current={page === "home" && hash === "#/local" ? "page" : undefined}
            onClick={() => page === "home" && jumpTo("local-start")}>
            <WorkspaceIcon name="folder" size={18} /> Local files &amp; scripts
          </a>
          <a href="#/library/gameplay" aria-current={page === "gameplay" ? "page" : undefined} data-testid="open-library">
            <WorkspaceIcon name="game" size={18} /> Gameplay library
          </a>
          <a href="#/recent" aria-current={page === "home" && hash === "#/recent" ? "page" : undefined}
            onClick={() => page === "home" && jumpTo("recent-projects")}>
            <WorkspaceIcon name="recent" size={18} /> Recent projects
          </a>
          <a href="#/activity" aria-current={page === "activity" ? "page" : undefined}>
            <WorkspaceIcon name="activity" size={18} /> Activity
          </a>
          <a href="#/settings" aria-current={page === "settings" ? "page" : undefined}>
            <WorkspaceIcon name="settings" size={18} /> AI settings
          </a>
        </nav>
        <div className="studio-sidebar-foot"><span /> Local workspace</div>
      </aside>
      <main className="studio-main">
        <div className="studio-topbar">
          <span>Workspace</span><WorkspaceIcon name="chevron" size={13} /><strong>{labels[page]}</strong>
        </div>
        <div className="studio-content">{children}</div>
      </main>
    </div>
  )
}
