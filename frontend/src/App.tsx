import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { buildGalaxy, health, isStatic, listSamples, recluster, type SampleInfo } from './api'
import { ClusterList } from './components/ClusterList'
import { Galaxy3D, type Galaxy3DHandle } from './components/Galaxy3D'
import { HowItWorks } from './components/HowItWorks'
import { SearchBar } from './components/SearchBar'
import { SeedBox } from './components/SeedBox'
import { StatusLine, type Status } from './components/StatusLine'
import { UserBox } from './components/UserBox'
import type { ApiError, BuildParams, Galaxy, GalaxyNode, Signal } from './types'

const clampInt = (raw: string | null, min: number, max: number, fallback: number) => {
  const v = Number.parseInt(raw ?? '', 10)
  return Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : fallback
}

function readUrl(): BuildParams {
  const q = new URLSearchParams(window.location.search)
  const k = q.get('k')
  return {
    login: (q.get('u') ?? '').trim(),
    depth: clampInt(q.get('d'), 1, 3, 2),
    max: Math.round(clampInt(q.get('n'), 100, 3000, 800) / 100) * 100,
    signal: q.get('s') === 'follow' ? 'follow' : 'collab',
    k: k ? clampInt(k, 2, 20, 2) : null,
  }
}

function writeUrl(p: BuildParams) {
  const q = new URLSearchParams({ u: p.login, d: String(p.depth), n: String(p.max), s: p.signal })
  if (p.k) q.set('k', String(p.k))
  window.history.replaceState(null, '', `?${q}`)
}

function load(key: string, fallback: boolean) {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === '1'
  } catch {
    return fallback
  }
}

function save(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // private mode: the toggle just won't be remembered
  }
}

function download(name: string, href: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
}

interface View {
  galaxy: Galaxy | null
  transition: 'build' | 'update'
  fromSample: boolean
}

export default function App() {
  const [params, setParams] = useState<BuildParams>(readUrl)
  const [view, setView] = useState<View>({ galaxy: null, transition: 'build', fromSample: false })
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [selected, setSelected] = useState<string | null>(null)
  const [focusCluster, setFocusCluster] = useState<number | null>(null)
  const [regrouping, setRegrouping] = useState(false)
  const [rotate, setRotate] = useState(() => load('galaxy.rotate', true))
  const [showLinks, setShowLinks] = useState(() => load('galaxy.links', true))
  const [remaining, setRemaining] = useState<number | null>(null)
  const [samples, setSamples] = useState<SampleInfo[]>([])
  const [find, setFind] = useState('')
  const [findMiss, setFindMiss] = useState('')
  const cancelRef = useRef<(() => void) | null>(null)
  const sceneRef = useRef<Galaxy3DHandle>(null)
  const galaxy = view.galaxy

  const show = useCallback((g: Galaxy, transition: View['transition'], fromSample = false) => {
    setView({ galaxy: g, transition, fromSample })
    setSelected(null)
    setFocusCluster(null)
  }, [])

  const regroup = useCallback(async (g: Galaxy, k: number | null, signal: Signal,
    fromSample = false) => {
    setRegrouping(true)
    try {
      const next = await recluster(g.key, k, signal)
      show(next, 'update')
      setStatus({ kind: 'done' })
      return next
    } catch (err) {
      const e = err as ApiError
      const msg = e.code === 'EXPIRED' && fromSample
        ? 'This is a pre-built sample. Build it to change the grouping.'
        : e.msg
      setStatus({ kind: 'error', error: { ...e, msg } })
      return null
    } finally {
      setRegrouping(false)
    }
  }, [show])

  const start = useCallback((p: BuildParams) => {
    cancelRef.current?.()
    setStatus({ kind: 'building', login: p.login, progress: null })
    cancelRef.current = buildGalaxy(p, {
      onProgress: (progress) => setStatus({ kind: 'building', login: p.login, progress }),
      onResult: (g) => {
        cancelRef.current = null
        setParams((old) => ({ ...old, login: g.seed }))
        writeUrl({ ...p, login: g.seed })
        show(g, 'build', isStatic)
        setStatus({ kind: 'done', note: isStatic ? `Sample built ${g.built_at.slice(0, 10)}.` : '' })
        if (p.k && p.k !== g.spectral.k && !isStatic) void regroup(g, p.k, p.signal)
        void health().then((h) => setRemaining(h?.rate?.remaining ?? null))
      },
      onError: (error) => {
        cancelRef.current = null
        setStatus({ kind: 'error', error })
      },
    })
  }, [regroup, show])

  // first load only: a shared link builds right away; the static demo opens its first sample
  const startRef = useRef(start)
  useEffect(() => {
    startRef.current = start
  }, [start])
  useEffect(() => {
    let alive = true
    void listSamples().then((list) => {
      if (!alive) return
      setSamples(list)
      const p = readUrl()
      if (p.login) startRef.current(p)
      else if (isStatic && list[0]) startRef.current({ ...p, login: list[0].login })
    })
    return () => {
      alive = false
      cancelRef.current?.()
    }
  }, [])

  const openSample = async (login: string) => {
    cancelRef.current?.()
    try {
      const resp = await fetch(`${import.meta.env.BASE_URL}samples/${login}.json`)
      if (!resp.ok) throw new Error(String(resp.status))
      const g: Galaxy = await resp.json()
      setParams((p) => ({ ...p, login: g.seed, depth: g.params.depth, max: g.params.max }))
      writeUrl({ login: g.seed, depth: g.params.depth, max: g.params.max, signal: g.params.signal, k: null })
      show(g, 'build', true)
      setStatus({ kind: 'done', note: `Sample built ${g.built_at.slice(0, 10)}.` })
    } catch {
      setStatus({ kind: 'error', error: { code: 'NETWORK', msg: `Could not open the ${login} sample.`, reset_at: null } })
    }
  }

  const clearFocus = useCallback(() => {
    setSelected(null)
    setFocusCluster(null)
    sceneRef.current?.resetView()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement
      if (e.key === 'Escape' && !typing) clearFocus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clearFocus])

  const nodeById = useMemo(() => new Map(galaxy?.nodes.map((n) => [n.id, n]) ?? []), [galaxy])
  const degree = useMemo(() => {
    const d = new Map<string, number>()
    for (const l of galaxy?.links ?? []) {
      d.set(l.source, (d.get(l.source) ?? 0) + 1)
      d.set(l.target, (d.get(l.target) ?? 0) + 1)
    }
    return d
  }, [galaxy])
  const selectedNode = selected ? (nodeById.get(selected) ?? null) : null

  const selectPerson = (login: string) => {
    if (!nodeById.has(login)) return
    setFocusCluster(null)
    setSelected(login)
  }

  const onCanvasSelect = useCallback((node: GalaxyNode | null) => {
    setFocusCluster(null)
    setSelected(node?.id ?? null)
  }, [])

  const onFind = (e: FormEvent) => {
    e.preventDefault()
    const q = find.trim().toLowerCase()
    if (!q || !galaxy) return
    const hit = galaxy.nodes.find((n) => n.id.toLowerCase() === q)
      ?? galaxy.nodes.find((n) => n.id.toLowerCase().startsWith(q) || n.name?.toLowerCase() === q)
    setFindMiss(hit ? '' : `No one called ${find.trim()} in this galaxy.`)
    if (hit) selectPerson(hit.id)
  }

  const changeGrouping = (next: { k?: number | null; signal?: Signal }) => {
    const p = { ...params, ...next }
    setParams(p)
    if (!galaxy) return
    writeUrl({ ...p, login: galaxy.seed })
    void regroup(galaxy, p.k, p.signal, view.fromSample)
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setStatus({ kind: 'done', note: 'Link copied.' })
    } catch {
      setStatus({ kind: 'done', note: `Copy this link: ${window.location.href}` })
    }
  }

  const busy = status.kind === 'building'
  const kOptions = Array.from({ length: 19 }, (_, i) => i + 2)

  return (
    <div className="app">
      <header className="top">
        <div className="brand">GitHub Galaxy</div>
        <SearchBar params={params} busy={busy} onChange={setParams}
          onSubmit={() => start({ ...params, k: null })}
          onCancel={() => {
            cancelRef.current?.()
            cancelRef.current = null
            setStatus({ kind: galaxy ? 'done' : 'idle' })
          }} />
      </header>
      <StatusLine status={status} galaxy={galaxy} remaining={remaining} />

      <main className="cols">
        <aside className="col left">
          <ClusterList clusters={galaxy?.clusters ?? []} focused={focusCluster}
            selectedCluster={selectedNode?.cluster ?? null}
            onFocus={(c) => {
              setSelected(null)
              setFocusCluster(c)
              if (c === null) sceneRef.current?.resetView()
            }}
            onPerson={selectPerson} />
          <section className="box">
            <h2 className="box-head">Grouping</h2>
            <div className="box-body">
              <div className="field">
                <label htmlFor="signal">Signal</label>
                <select id="signal" value={params.signal} disabled={!galaxy || regrouping || isStatic}
                  onChange={(e) => changeGrouping({ signal: e.target.value as Signal })}>
                  <option value="collab">Follows + shared repos</option>
                  <option value="follow">Follows only</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="k">Clusters</label>
                <select id="k" value={params.k ?? ''} disabled={!galaxy || regrouping || isStatic}
                  onChange={(e) => changeGrouping({ k: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Auto{galaxy ? ` (${galaxy.spectral.k_auto})` : ''}</option>
                  {kOptions.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
              <p className="muted small">
                {isStatic
                  ? 'Changing the grouping needs the local server.'
                  : regrouping
                    ? 'Regrouping…'
                    : 'Changing these reruns the clustering only. Nothing new is fetched.'}
              </p>
            </div>
          </section>
        </aside>

        <section className="center">
          <div className="toolbar">
            <form onSubmit={onFind} role="search">
              <label htmlFor="find" className="sr-only">Find a person</label>
              <input id="find" type="search" list="people" placeholder="Find a person in this galaxy"
                value={find} disabled={!galaxy}
                onChange={(e) => { setFind(e.target.value); setFindMiss('') }} />
              <datalist id="people">
                {galaxy?.nodes.map((n) => <option key={n.id} value={n.id}>{n.name ?? ''}</option>)}
              </datalist>
              <button type="submit" disabled={!galaxy}>Find</button>
            </form>
            {findMiss && <span className="status-error small">{findMiss}</span>}
            <div className="toolbar-right">
              <button type="button" className="link" onClick={clearFocus} disabled={!galaxy}>
                Reset view
              </button>
              <label>
                <input type="checkbox" checked={rotate}
                  onChange={(e) => { setRotate(e.target.checked); save('galaxy.rotate', e.target.checked) }} />
                Rotate
              </label>
              <label>
                <input type="checkbox" checked={showLinks}
                  onChange={(e) => { setShowLinks(e.target.checked); save('galaxy.links', e.target.checked) }} />
                Links
              </label>
            </div>
          </div>
          <Galaxy3D ref={sceneRef} galaxy={galaxy} transition={view.transition} selected={selected}
            focusCluster={focusCluster} rotate={rotate} showLinks={showLinks}
            onSelect={onCanvasSelect}>
            {!galaxy && busy && (
              <div className="empty">
                <p className="muted">
                  Fetching {status.login}'s network. Bigger networks take a minute or two.
                </p>
              </div>
            )}
            {!galaxy && !busy && (
              <div className="empty">
                <p>Enter a GitHub username to build their galaxy.</p>
                {samples.length > 0 && (
                  <p className="muted">
                    Or open a sample:{' '}
                    {samples.map((s, i) => (
                      <span key={s.login}>
                        {i > 0 && ', '}
                        <button type="button" className="link" onClick={() => void openSample(s.login)}>
                          {s.login}
                        </button>
                      </span>
                    ))}
                  </p>
                )}
              </div>
            )}
          </Galaxy3D>
        </section>

        <aside className="col right">
          <UserBox node={selectedNode}
            cluster={selectedNode ? (galaxy?.clusters[selectedNode.cluster] ?? null) : null}
            seed={galaxy?.seed ?? null} degree={selected ? (degree.get(selected) ?? 0) : 0}
            onBuildFrom={(login) => {
              const p = { ...params, login, k: null }
              setParams(p)
              start(p)
            }} />
          <SeedBox galaxy={galaxy} onPerson={selectPerson}
            onFocus={(c) => { setSelected(null); setFocusCluster(c) }} />
          <HowItWorks galaxy={galaxy} />
        </aside>
      </main>

      <footer className="foot">
        <span>
          <button type="button" className="link" disabled={!galaxy}
            onClick={() => galaxy && download(`${galaxy.seed}-galaxy.json`,
              URL.createObjectURL(new Blob([JSON.stringify(galaxy)], { type: 'application/json' })))}>
            Download JSON
          </button>
          <span className="sep">|</span>
          <button type="button" className="link" disabled={!galaxy}
            onClick={() => {
              const png = sceneRef.current?.screenshot()
              if (png && galaxy) download(`${galaxy.seed}-galaxy.png`, png)
            }}>
            Save PNG
          </button>
          <span className="sep">|</span>
          <button type="button" className="link" disabled={!galaxy} onClick={() => void copyLink()}>
            Copy share link
          </button>
        </span>
        <span className="muted">
          Drag to rotate, scroll to zoom, right-drag to pan. Esc resets the view.
        </span>
      </footer>
    </div>
  )
}
