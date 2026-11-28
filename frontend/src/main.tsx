import React from "react"
import ReactDOM from "react-dom/client"
import { initSession } from "./api"
import { App } from "./App"
import { connectEvents } from "./events"
import "./styles.css"
import "./styles-p2.css"
import "./styles-cleanup.css"
import "./styles-modern.css"

async function start() {
  await initSession()
  connectEvents()
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

start().catch((e) => {
  document.getElementById("root")!.textContent = `Shorts Studio could not start: ${e}`
})
