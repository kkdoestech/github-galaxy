import type { ApiError, Galaxy, Progress } from '../types'

export type Status =
  | { kind: 'idle' }
  | { kind: 'building'; login: string; progress: Progress | null }
  | { kind: 'done'; note?: string }
  | { kind: 'error'; error: ApiError }

/** Rough share of the whole build each stage represents, for one steady progress bar. */
const STAGES: Record<string, [number, number]> = {
  queue: [0, 0],
  seed: [0, 3],
  follows: [3, 55],
  profiles: [55, 96],
  clustering: [96, 99],
}

function percent(p: Progress | null) {
  if (!p) return 1
  const [from, to] = STAGES[p.stage] ?? [0, 100]
  const share = p.total ? p.done / p.total : 0
  return from + (to - from) * share
}

const fmt = (n: number) => n.toLocaleString('en-US')

function resetTime(iso: string | null) {
  if (!iso) return ''
  const t = new Date(iso)
  return Number.isNaN(t.getTime())
    ? ''
    : ` Try again after ${t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`
}

interface Props {
  status: Status
  galaxy: Galaxy | null
  remaining: number | null
}

export function StatusLine({ status, galaxy, remaining }: Props) {
  let body
  if (status.kind === 'building') {
    body = <span>{status.progress?.msg ?? `Starting ${status.login}…`}</span>
  } else if (status.kind === 'error') {
    body = (
      <span className="status-error">
        {status.error.msg}
        {status.error.code === 'RATE_LIMITED' && resetTime(status.error.reset_at)}
      </span>
    )
  } else if (galaxy) {
    const s = galaxy.stats
    body = (
      <span>
        <strong>{galaxy.seed}</strong>: {fmt(s.people)} people, {fmt(s.links)} links,{' '}
        {galaxy.spectral.k} clusters.
        {remaining !== null && ` GitHub API: ${fmt(remaining)} points left this hour.`}
        {status.kind === 'done' && status.note && ` ${status.note}`}
      </span>
    )
  } else {
    body = <span>Enter a GitHub username to build their galaxy.</span>
  }

  return (
    <div className="status" role="status" aria-live="polite">
      {body}
      {status.kind === 'building' && (
        <div className="progress" aria-hidden="true">
          <div style={{ width: `${percent(status.progress)}%` }} />
        </div>
      )}
    </div>
  )
}
