import { useEffect, useState, type FormEvent } from "react"
import { api, type AIProvider, type ProviderOption, type ProviderSettings } from "../api"
import { StudioShell } from "./StudioShell"

type OptionKind = "models" | "voices"
const MANUAL_ID = "#manual"

function ProviderCard({ provider, settings, onSaved }: {
  provider: AIProvider; settings: ProviderSettings; onSaved: (settings: ProviderSettings) => void
}) {
  const eleven = provider === "elevenlabs"
  const connected = eleven ? settings.elevenlabs_configured : settings.opencode_configured
  const name = eleven ? "ElevenLabs" : "OpenCode Go"
  const [key, setKey] = useState("")
  const [model, setModel] = useState(eleven ? settings.elevenlabs_model : settings.opencode_model)
  const [voice, setVoice] = useState(settings.elevenlabs_voice)
  const [options, setOptions] = useState<Partial<Record<OptionKind, ProviderOption[]>>>({})
  const [manual, setManual] = useState<Partial<Record<OptionKind, boolean>>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState("")
  const [failed, setFailed] = useState(false)

  async function save(event?: FormEvent, remove = false) {
    event?.preventDefault()
    setBusy(remove ? "Removing key…" : "Saving…")
    setFailed(false)
    setNote("")
    const credential = remove ? "" : key.trim() || undefined
    try {
      const next = await api.updateProviders(eleven
        ? { elevenlabs_key: credential, elevenlabs_model: model.trim(), elevenlabs_voice: voice.trim() }
        : { opencode_key: credential, opencode_model: model.trim() })
      setKey("")
      setModel(eleven ? next.elevenlabs_model : next.opencode_model)
      setVoice(next.elevenlabs_voice)
      onSaved(next)
      if (credential !== undefined) setOptions({})
      setNote(remove ? "API key removed." : "Settings saved on this device.")
    } catch (error) {
      setFailed(true)
      setNote((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function load(kind: OptionKind) {
    setBusy(kind === "models" ? "Loading models…" : "Loading speakers…")
    setFailed(false)
    setNote("")
    try {
      const result = await api.providerOptions(provider, kind)
      setOptions((previous) => ({ ...previous, [kind]: result.options }))
      setManual((previous) => ({ ...previous, [kind]: false }))
      setNote(result.options.length ? `${result.options.length} ${kind === "models" ? "models" : "speakers"} available.` : "No choices returned for this key.")
    } catch (error) {
      setFailed(true)
      setNote((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function checkGoAccess() {
    setBusy("Checking Go subscription…")
    setFailed(false)
    try {
      await api.checkOpenCodeAccess()
      setNote("The saved key has access to OpenCode Go.")
    } catch (error) {
      setFailed(true)
      setNote((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function choice(kind: OptionKind, title: string, value: string, setter: (value: string) => void) {
    const id = `${provider}-${kind}`
    const entries = options[kind] ?? []
    const chooseFromList = entries.length > 0 && !manual[kind]
    const noun = kind === "models" ? "model" : "speaker"
    return (
      <div className="studio-config-label">
        <label htmlFor={id}>{title}</label>
        <div className="studio-setting-row">
          {chooseFromList ? (
            <select id={id} value={value} onChange={(event) => {
              if (event.target.value === MANUAL_ID) setManual((previous) => ({ ...previous, [kind]: true }))
              else setter(event.target.value)
            }}>
              <option value="">Choose a {noun}</option>
              {value && !entries.some((entry) => entry.id === value) && <option value={value}>{value}</option>}
              {entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
              <option value={MANUAL_ID}>Enter {noun} ID manually…</option>
            </select>
          ) : <input id={id} type="text" value={value} onChange={(event) => setter(event.target.value)}
            placeholder={`Enter a ${noun} ID or load options`} />}
          <button type="button" disabled={!!busy || !connected} onClick={() => {
            if (entries.length && manual[kind]) setManual((previous) => ({ ...previous, [kind]: false }))
            else void load(kind)
          }}>
            {entries.length && manual[kind] ? `Show ${noun}s` : `Load ${noun}s`}
          </button>
        </div>
      </div>
    )
  }

  return (
    <form className="studio-card studio-config" onSubmit={(event) => void save(event)}>
      <header className="studio-card-head studio-preview-head">
        <div><h2>{name}</h2><p>{eleven ? "Generate narration and caption timings." : "Draft a Short script from a topic."}</p></div>
        <span className={`studio-state${connected ? " studio-state-done" : ""}`}>{connected ? "Key saved" : "Key needed"}</span>
      </header>
      <label className="studio-config-label" htmlFor={`${provider}-key`}>{name} API key
        <input id={`${provider}-key`} type="password" autoComplete="new-password" value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={connected ? "Enter a new key to replace it" : "Paste your API key"} />
      </label>
      {choice("models", eleven ? "Voice model" : "Writing model", model, setModel)}
      {eleven && choice("voices", "Speaker", voice, setVoice)}
      <div className="studio-setting-actions">
        <button className="studio-save" type="submit" disabled={!!busy}>Save {name}</button>
        {connected && <button type="button" disabled={!!busy} onClick={() => void save(undefined, true)}>Remove key</button>}
      </div>
      {!eleven && connected && <div className="row">
        <button type="button" disabled={!!busy} onClick={() => void checkGoAccess()}>Check Go subscription</button>
      </div>}
      <p className={failed ? "studio-field-error" : "hint"} role="status">{busy ?? note}</p>
    </form>
  )
}

export function AISettingsPage() {
  const [settings, setSettings] = useState<ProviderSettings | null>(null)
  const [error, setError] = useState("")
  useEffect(() => { api.providers().then(setSettings).catch((e) => setError(e.message)) }, [])

  return (
    <StudioShell page="settings">
      <header className="studio-intro">
        <h1>AI settings</h1>
        <p>Choose the models for writing and voiceover. API keys stay in this workspace’s local settings.</p>
      </header>
      {settings ? <div className="studio-settings-grid">
        <ProviderCard provider="opencode" settings={settings} onSaved={setSettings} />
        <ProviderCard provider="elevenlabs" settings={settings} onSaved={setSettings} />
      </div> : <p className={error ? "error-text" : "hint"} role="status">{error || "Loading AI settings…"}</p>}
    </StudioShell>
  )
}
