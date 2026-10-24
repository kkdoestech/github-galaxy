import type { FormEvent } from 'react'
import { isStatic } from '../api'
import type { BuildParams } from '../types'
import { Stepper } from './Stepper'

interface Props {
  params: BuildParams
  busy: boolean
  onChange: (p: BuildParams) => void
  onSubmit: () => void
  onCancel: () => void
}

export function SearchBar({ params, busy, onChange, onSubmit, onCancel }: Props) {
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (params.login.trim()) onSubmit()
  }
  return (
    <form className="search" onSubmit={submit}>
      <label htmlFor="login" className="sr-only">GitHub username</label>
      <input id="login" type="search" placeholder="GitHub username" autoComplete="off"
        spellCheck={false} value={params.login}
        onChange={(e) => onChange({ ...params, login: e.target.value.trim() })} />
      <label title="How far from this person to look. 2 = friends of friends.">
        Depth
        <select value={params.depth} disabled={isStatic}
          onChange={(e) => onChange({ ...params, depth: Number(e.target.value) })}>
          <option value={1}>1 hop</option>
          <option value={2}>2 hops</option>
          <option value={3}>3 hops</option>
        </select>
      </label>
      <span className="search-group">
        <label htmlFor="max-people">Max people</label>
        <Stepper id="max-people" value={params.max} min={100} max={3000} step={100}
          onChange={(max) => onChange({ ...params, max })} />
      </span>
      <button type="submit" className="primary" disabled={busy || !params.login}>
        {busy ? 'Building…' : 'Build galaxy'}
      </button>
      {busy && <button type="button" onClick={onCancel}>Cancel</button>}
    </form>
  )
}
