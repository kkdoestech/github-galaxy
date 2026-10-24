import type { Galaxy } from '../types'

interface Props {
  galaxy: Galaxy | null
  onFocus: (cluster: number) => void
  onPerson: (login: string) => void
}

/** Which cluster the person the galaxy was built around landed in. */
export function SeedBox({ galaxy, onFocus, onPerson }: Props) {
  const seed = galaxy?.nodes.find((n) => n.id === galaxy.seed)
  const cluster = seed ? galaxy?.clusters[seed.cluster] : undefined
  return (
    <section className="box">
      <h2 className="box-head">{galaxy ? `${galaxy.seed}'s cluster` : 'Your cluster'}</h2>
      <div className="box-body">
        {!galaxy || !seed || !cluster ? (
          <p className="muted">Build a galaxy to see which group you land in.</p>
        ) : (
          <>
            <p>
              <span className="swatch" style={{ background: cluster.color }} />{' '}
              {galaxy.seed} is in cluster {cluster.id + 1} of {galaxy.clusters.length},{' '}
              <strong>{cluster.label}</strong>, with {cluster.size - 1} other{' '}
              {cluster.size === 2 ? 'person' : 'people'}.
            </p>
            {cluster.top_langs.length > 0 && <p>Top languages: {cluster.top_langs.join(', ')}.</p>}
            <p>
              Most followed:{' '}
              {cluster.top_members.map((m, i) => (
                <span key={m}>
                  {i > 0 && ', '}
                  <button type="button" className="link" onClick={() => onPerson(m)}>{m}</button>
                </span>
              ))}
            </p>
            {cluster.top_repos.length > 0 && (
              <p>
                Shared repos:{' '}
                {cluster.top_repos.map((r, i) => (
                  <span key={r}>
                    {i > 0 && ', '}
                    <a href={`https://github.com/${r}`} target="_blank" rel="noreferrer">{r}</a>
                  </span>
                ))}
              </p>
            )}
            <button type="button" className="link" onClick={() => onFocus(cluster.id)}>
              Show only this cluster
            </button>
          </>
        )}
      </div>
    </section>
  )
}
