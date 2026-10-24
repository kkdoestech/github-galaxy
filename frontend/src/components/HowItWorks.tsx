import { useState } from 'react'
import type { Galaxy } from '../types'

const W = 276
const H = 112
const PAD = { left: 26, right: 2, top: 10, bottom: 18 }
const BAR_ON = '#BFBDB6' // ayu editor.fg: the k smallest eigenvalues
const BAR_OFF = '#3A4150' // recessive: the rest
const GAP = '#E6B450' // the jump that picks k

/** Bar with rounded top ends, anchored to the baseline. */
function bar(x: number, y: number, w: number, h: number) {
  const r = Math.min(3, w / 2, h)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

export function HowItWorks({ galaxy }: { galaxy: Galaxy | null }) {
  const [hover, setHover] = useState<number | null>(null)
  const sp = galaxy?.spectral
  const values = sp?.eigenvalues ?? []

  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const yMax = Math.max(0.5, Math.ceil(Math.max(0, ...values) * 5) / 5)
  const slot = values.length ? plotW / values.length : 0
  const barW = Math.max(2, slot - 2) // 2px gap between bars
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH
  const k = sp?.k ?? 0

  let readout = ''
  if (sp && hover !== null) {
    const v = values[hover]
    const jump = hover > 0 ? v - values[hover - 1] : null
    readout = `λ${hover + 1} = ${v.toFixed(3)}${jump !== null ? `, up ${jump.toFixed(3)} from λ${hover}` : ''}`
  } else if (sp) {
    readout = `k = ${sp.k}${sp.k !== sp.k_auto ? ` (auto picked ${sp.k_auto})` : ''}, modularity ${sp.modularity.toFixed(2)}`
  }

  return (
    <section className="box">
      <h2 className="box-head">How it works</h2>
      <div className="box-body">
        {sp && values.length > 1 && (
          <>
            <div className="sub-head">Smallest Laplacian eigenvalues</div>
            <div className="chart-readout muted num" aria-live="polite">{readout}</div>
            <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
              aria-label={`Bar chart of the ${values.length} smallest eigenvalues. The first ${k} are highlighted.`}
              onMouseLeave={() => setHover(null)}>
              {[0, yMax / 2, yMax].map((t) => (
                <g key={t}>
                  <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="#1B1F29" />
                  <text x={PAD.left - 5} y={y(t) + 3.5} textAnchor="end">{t.toFixed(1)}</text>
                </g>
              ))}
              {values.map((v, i) => {
                const x = PAD.left + i * slot + 1
                const h = Math.max(1, (v / yMax) * plotH)
                return (
                  <path key={i} d={bar(x, PAD.top + plotH - h, barW, h)}
                    fill={i < k ? BAR_ON : BAR_OFF} opacity={hover === null || hover === i ? 1 : 0.6} />
                )
              })}
              {k > 0 && k < values.length && (() => {
                const x = PAD.left + k * slot
                return (
                  <g>
                    <line x1={x} x2={x} y1={y(values[k - 1])} y2={y(values[k])} stroke={GAP}
                      strokeWidth={2} />
                    <text x={x + 4} y={y(values[k]) - 2} style={{ fill: GAP }}>gap</text>
                  </g>
                )
              })()}
              {[1, 5, 10, 15, 20].filter((n) => n <= values.length).map((n) => (
                <text key={n} x={PAD.left + (n - 0.5) * slot} y={H - 4} textAnchor="middle">{n}</text>
              ))}
              {values.map((_, i) => (
                <rect key={i} x={PAD.left + i * slot} y={PAD.top - 6} width={slot} height={plotH + 6}
                  fill="transparent" onMouseEnter={() => setHover(i)} />
              ))}
            </svg>
          </>
        )}
        <p className="small">
          Each star is a person. Follows{galaxy?.params.signal === 'collab' ? ' and shared repos' : ''}{' '}
          link people into a weighted graph <i>W</i>, and the normalized Laplacian{' '}
          <i>L = I − D<sup>−½</sup>WD<sup>−½</sup></i> is built from it.
        </p>
        <p className="small">
          Its smallest eigenvalues stay low for groups that are only loosely tied to the rest. A
          big jump after the first <i>k</i> of them suggests <i>k</i> groups. Each person's row of
          those <i>k</i> eigenvectors is then sorted into groups with k-means.
        </p>
        <p className="small muted">
          Modularity above 0.3 usually means real groups. The auto pick takes the three biggest
          jumps and keeps the one with the best modularity.
        </p>
        {sp && values.length > 1 && (
          <details>
            <summary>Show the values</summary>
            <table className="values">
              <thead>
                <tr><th>#</th><th>λ</th><th>Jump</th></tr>
              </thead>
              <tbody>
                {values.map((v, i) => (
                  <tr key={i}>
                    <td>{i + 1}{i === k - 1 ? ' (k)' : ''}</td>
                    <td>{v.toFixed(3)}</td>
                    <td>{i > 0 ? (v - values[i - 1]).toFixed(3) : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>
    </section>
  )
}
