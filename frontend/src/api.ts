import type { ApiError, BuildParams, Galaxy, Progress, Signal } from './types'

/** Static demo build (GitHub Pages): only the pre-built sample galaxies, no server. */
export const isStatic = import.meta.env.VITE_STATIC === '1'
const base = import.meta.env.BASE_URL

export interface SampleInfo {
  login: string
  people: number
  clusters: number
}

export async function listSamples(): Promise<SampleInfo[]> {
  try {
    const resp = await fetch(`${base}samples/index.json`)
    return resp.ok ? await resp.json() : []
  } catch {
    return []
  }
}

interface Handlers {
  onProgress: (p: Progress) => void
  onResult: (g: Galaxy) => void
  onError: (e: ApiError) => void
}

function fail(code: string, msg: string): ApiError {
  return { code, msg, reset_at: null }
}

async function loadSample(login: string, h: Handlers, signal: AbortSignal) {
  try {
    const resp = await fetch(`${base}samples/${login.toLowerCase()}.json`, { signal })
    if (!resp.ok) {
      h.onError(fail('NOT_IN_DEMO', `This demo only has the sample galaxies. Run the app locally to build ${login}.`))
      return
    }
    h.onResult(await resp.json())
  } catch (err) {
    if (!signal.aborted) h.onError(fail('NETWORK', `Could not load the sample: ${String(err)}`))
  }
}

/** Start a build. Returns a function that cancels it. */
export function buildGalaxy(p: BuildParams, h: Handlers): () => void {
  if (isStatic) {
    const ctrl = new AbortController()
    void loadSample(p.login, h, ctrl.signal)
    return () => ctrl.abort()
  }

  const qs = new URLSearchParams({ u: p.login, d: String(p.depth), n: String(p.max), s: p.signal })
  const source = new EventSource(`/api/galaxy/stream?${qs}`)
  let finished = false
  const close = () => {
    finished = true
    source.close()
  }
  source.addEventListener('progress', (e) => h.onProgress(JSON.parse((e as MessageEvent).data)))
  source.addEventListener('result', (e) => {
    close()
    h.onResult(JSON.parse((e as MessageEvent).data))
  })
  source.addEventListener('error', (e) => {
    const data = (e as MessageEvent).data
    close()
    if (data) h.onError(JSON.parse(data))
    else h.onError(fail('NETWORK', 'Lost the connection to the server. Is it running? Try again.'))
  })
  return () => {
    if (!finished) close()
  }
}

export async function recluster(key: string, k: number | null, s: Signal): Promise<Galaxy> {
  if (isStatic) throw fail('STATIC', 'Changing clusters needs the local server.')
  let resp: Response
  try {
    resp = await fetch('/api/recluster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, k, s }),
    })
  } catch {
    throw fail('NETWORK', 'Could not reach the server. Is it running?')
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw fail(resp.status === 404 ? 'EXPIRED' : 'BAD_INPUT', body.detail ?? 'Re-clustering failed.')
  }
  return resp.json()
}

export interface Health {
  ok: boolean
  token: boolean
  rate: { remaining: number; resetAt: string } | null
}

export async function health(): Promise<Health | null> {
  if (isStatic) return null
  try {
    const resp = await fetch('/api/health')
    return resp.ok ? await resp.json() : null
  } catch {
    return null
  }
}
