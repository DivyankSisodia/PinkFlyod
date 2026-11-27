import type { ReactNode } from "react"
import { useEditor } from "../../state/editor"

/** A range input whose drag is one undo step. */
export function Slider({ label, value, min, max, step, onChange, testid, fmt = (v) => v.toFixed(2), disabled }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void
  testid?: string; fmt?: (v: number) => string; disabled?: boolean
}) {
  const { beginGesture, endGesture } = useEditor.getState()
  return (
    <label className="slider">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} data-testid={testid} disabled={disabled}
        onPointerDown={beginGesture} onPointerUp={endGesture} onKeyUp={endGesture}
        onChange={(e) => onChange(Number(e.target.value))} />
      <span className="val">{fmt(value)}</span>
    </label>
  )
}

export function Choice<T extends string>({ value, options, onChange, label, testid }: {
  value: T; options: readonly { value: T; label: string }[]; onChange: (v: T) => void; label: string; testid?: string
}) {
  return (
    <div className="seg-buttons" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "on" : ""} role="radio" aria-checked={value === o.value}
          data-testid={testid ? `${testid}-${o.value}` : undefined} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

export function Section({ title, children, open = true, testid, extra }: {
  title: string; children: ReactNode; open?: boolean; testid?: string; extra?: ReactNode
}) {
  return (
    <details className="section" open={open} data-testid={testid}>
      <summary><span>{title}</span>{extra}</summary>
      <div className="group">{children}</div>
    </details>
  )
}

/** A text input that commits on blur or Enter (one undo step per edit, not per key). */
export function TextField({ value, onCommit, placeholder, testid, multiline, label, maxLength }: {
  value: string; onCommit: (v: string) => void; placeholder?: string; testid?: string; multiline?: boolean
  label?: string; maxLength?: number
}) {
  // Keyed on the stored value, so undo or an edit elsewhere refreshes the field.
  const common = {
    defaultValue: value, placeholder, "data-testid": testid, "aria-label": label ?? placeholder, maxLength,
    onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      if (e.target.value !== value) onCommit(e.target.value)
    },
  }
  return multiline
    ? <textarea key={value} {...common} rows={3} onKeyDown={(e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.target as HTMLTextAreaElement).blur()
    }} />
    : <input key={value} {...common} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
}

export const dbFmt = (v: number) => `${v > 0 ? "+" : ""}${v} dB`
export const secFmt = (v: number) => `${v.toFixed(2)} s`
