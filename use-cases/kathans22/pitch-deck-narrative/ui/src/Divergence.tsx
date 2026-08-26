import type { DivergenceReport } from './report'
import { SECTION_TITLES, fmt, pairLabel } from './report'
import './Divergence.css'

type Props = {
  report: DivergenceReport
}

export default function Divergence({ report }: Props) {
  const { evaluation, report: inner, section_weights } = report
  const verticalMean = evaluation.mean_vertical_overlap
  const sharedMean = evaluation.mean_shared_overlap
  const meanMax = evaluation.thresholds.vertical_mean_max
  const cellMax = evaluation.thresholds.vertical_section_max
  const passed = evaluation.passed
  const sections = Object.keys(section_weights).sort(
    (a, b) => Number(a) - Number(b),
  )
  const pairs = inner.pairs

  return (
    <main className="div">
      <p className="div-kicker">ClarityDocs · speaking scripts · not a slide deck</p>
      <p
        className={passed ? 'div-verdict div-verdict-pass' : 'div-verdict div-verdict-fail'}
      >
        {passed ? 'Pass' : 'Fail'}
      </p>
      <h1 className="div-title">Divergence</h1>
      <p className="div-lede">
        Pairwise lexical overlap. Vertical-tagged sections must differ in substance.
        Shared sections may overlap — the product is held constant. The inverse of
        Build&nbsp;1’s identical core-hash, made numeric.
      </p>
      <p className="div-rule">
        Vertical mean {fmt(verticalMean)} {passed ? '<' : '≥'} {fmt(meanMax)}. No
        vertical cell at or above {fmt(cellMax)}. Shared overlap is reported, not
        gated.
      </p>

      <section className="div-means" aria-label="Mean overlap by weight class">
        <article className="div-mean">
          <p className="div-mean-label">Vertical mean</p>
          <p className="div-mean-value">{fmt(verticalMean)}</p>
          <p className="div-mean-note">
            Must stay below {fmt(meanMax)}. {inner.aggregates.vertical_cells} pair×section
            cells.
          </p>
        </article>
        <article className="div-mean">
          <p className="div-mean-label">Shared mean</p>
          <p className="div-mean-value">{fmt(sharedMean)}</p>
          <p className="div-mean-note">
            Expected higher. Opening, overview, call to action.{' '}
            {inner.aggregates.shared_cells} cells.
          </p>
        </article>
      </section>

      <section className="div-grid-wrap" aria-label="Per section per pair overlap">
        <h2 className="div-grid-title">Every pair, every section</h2>
        <table className="div-grid">
          <thead>
            <tr>
              <th scope="col">§</th>
              <th scope="col">Weight</th>
              {pairs.map((p) => (
                <th key={`${p.vertical_a}-${p.vertical_b}`} scope="col">
                  {pairLabel(p.vertical_a, p.vertical_b)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sections.map((n) => {
              const weight = section_weights[n]
              return (
                <tr key={n} className={weight === 'vertical' ? 'is-vertical' : 'is-shared'}>
                  <th scope="row">
                    <span className="div-sec-n">{n}</span>
                    <span className="div-sec-title">{SECTION_TITLES[n] ?? n}</span>
                  </th>
                  <td className="div-weight">{weight}</td>
                  {pairs.map((p) => {
                    const score = p.sections[n]
                    const hot =
                      weight === 'vertical' &&
                      typeof score === 'number' &&
                      score >= cellMax
                    return (
                      <td
                        key={`${n}-${p.vertical_a}-${p.vertical_b}`}
                        className={hot ? 'div-cell is-hot' : 'div-cell'}
                      >
                        {typeof score === 'number' ? fmt(score) : '—'}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
        {(report.coverage_notes ?? []).length > 0 ? (
          <p className="div-notes">
            {report.coverage_notes!.map((n) => (
              <span key={`${n.vertical}-${n.section}`}>
                {n.vertical} §{n.section}: {n.issue.replaceAll('_', ' ')}.
              </span>
            ))}
          </p>
        ) : null}
      </section>
    </main>
  )
}
