import type { Cluster, GalaxyNode } from '../types'

interface Props {
  node: GalaxyNode | null
  cluster: Cluster | null
  seed: string | null
  degree: number
  onBuildFrom: (login: string) => void
}

const fmt = (n: number) => n.toLocaleString('en-US')

function distance(hop: number, seed: string | null) {
  if (hop === 0) return 'This galaxy is built around them'
  return `${hop} ${hop === 1 ? 'hop' : 'hops'} from ${seed}`
}

export function UserBox({ node, cluster, seed, degree, onBuildFrom }: Props) {
  return (
    <section className="box">
      <h2 className="box-head">Selected</h2>
      <div className="box-body">
        {!node ? (
          <p className="muted">Click a star to see who it is. Drag a star to move it.</p>
        ) : (
          <>
            <div className="user-top">
              {node.avatar && <img src={node.avatar} width={48} height={48} alt="" loading="lazy" />}
              <div>
                <div className="user-name">
                  <a href={`https://github.com/${node.id}`} target="_blank" rel="noreferrer">
                    {node.name || node.id}
                  </a>
                </div>
                <div className="muted">@{node.id}</div>
              </div>
            </div>
            {node.bio && <p>{node.bio}</p>}
            <dl className="facts">
              <dt>Followers</dt>
              <dd className="num">{fmt(node.followers)}</dd>
              <dt>Cluster</dt>
              <dd>
                {cluster && <span className="swatch" style={{ background: cluster.color }} />}{' '}
                {cluster ? `${cluster.id + 1}. ${cluster.label}` : '–'}
              </dd>
              <dt>Links here</dt>
              <dd className="num">{fmt(degree)}</dd>
              <dt>Distance</dt>
              <dd>{distance(node.hop, seed)}</dd>
              {node.langs.length > 0 && (
                <>
                  <dt>Languages</dt>
                  <dd>{node.langs.join(', ')}</dd>
                </>
              )}
            </dl>
            {node.repos.length > 0 && (
              <>
                <h3 className="sub-head">Top repos</h3>
                <ul className="repos">
                  {node.repos.map((r) => (
                    <li key={r.name}>
                      <a href={`https://github.com/${r.name}`} target="_blank" rel="noreferrer">
                        {r.name.split('/')[1] ?? r.name}
                      </a>{' '}
                      <span className="muted small">
                        {[r.lang, `${fmt(r.stars)} ${r.stars === 1 ? 'star' : 'stars'}`]
                          .filter(Boolean).join(' · ')}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {node.hop > 0 && (
              <button type="button" className="link" onClick={() => onBuildFrom(node.id)}>
                Build a galaxy from {node.id}
              </button>
            )}
          </>
        )}
      </div>
    </section>
  )
}
