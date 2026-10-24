import { useState } from 'react'

interface Props {
  id?: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))

/** A number field with − and + buttons instead of the browser's tiny spinner arrows. */
export function Stepper({ id, value, min, max, step, onChange }: Props) {
  const [draft, setDraft] = useState<string | null>(null) // only while typing

  const commit = (raw: string) => {
    const parsed = Number.parseInt(raw, 10)
    const next = Number.isFinite(parsed) ? clamp(Math.round(parsed / step) * step, min, max) : value
    setDraft(null)
    if (next !== value) onChange(next)
  }

  return (
    <span className="stepper">
      <button type="button" aria-label="Fewer" disabled={value <= min}
        onClick={() => onChange(clamp(value - step, min, max))}>−</button>
      <input id={id} type="number" inputMode="numeric" min={min} max={max} step={step}
        value={draft ?? String(value)} onChange={(e) => setDraft(e.target.value)} onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && commit(e.currentTarget.value)} />
      <button type="button" aria-label="More" disabled={value >= max}
        onClick={() => onChange(clamp(value + step, min, max))}>+</button>
    </span>
  )
}
