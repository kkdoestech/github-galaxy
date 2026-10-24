import type { Cluster } from '../types'

interface Props {
  clusters: Cluster[]
  focused: number | null
  selectedCluster: number | null
  onFocus: (id: number | null) => void
  onPerson: (login: string) => void
}

export function ClusterList({ clusters, focused, selectedCluster, onFocus, onPerson }: Props) {
  return (
    <section className="box">
      <h2 className="box-head">
        Clusters <span className="muted num">{clusters.length || ''}</span>
      </h2>
      {clusters.length === 0 ? (
        <p className="box-body muted">Groups of people who follow each other or share repos.</p>
      ) : (
        <ol className="clusters">
          {clusters.map((c) => (
            <li key={c.id}
              className={c.id === focused || (focused === null && c.id === selectedCluster)
                ? 'active' : ''}>
              <button type="button" className="bare cluster-row" aria-pressed={c.id === focused}
                title="Show only this cluster"
                onClick={() => onFocus(c.id === focused ? null : c.id)}>
                <span className="swatch" style={{ background: c.color }} />
                <span className="cluster-name">{c.id + 1}. {c.label}</span>
                <span className="cluster-size">{c.size}</span>
              </button>
              <div className="cluster-members">
                {c.top_members.map((m, i) => (
                  <span key={m}>
                    {i > 0 && ', '}
                    <button type="button" className="link" onClick={() => onPerson(m)}>{m}</button>
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
