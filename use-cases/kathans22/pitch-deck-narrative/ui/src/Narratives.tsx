import { useEffect, useMemo, useState } from 'react'
import eligibility from './data/image-eligibility.json'
import edtech from './data/scripts/edtech.md?raw'
import fintech from './data/scripts/fintech.md?raw'
import healthcare from './data/scripts/healthcare.md?raw'
import legal from './data/scripts/legal.md?raw'
import { parseScript } from './parseScript'
import './Narratives.css'

const BUNDLED: Record<string, string> = {
  legal,
  fintech,
  healthcare,
  edtech,
}

const CODES = ['legal', 'fintech', 'healthcare', 'edtech'] as const

type Props = {
  initial?: string
}

export default function Narratives({ initial = 'fintech' }: Props) {
  const [code, setCode] = useState(initial)
  const [md, setMd] = useState(BUNDLED[initial] ?? BUNDLED.fintech)
  const [source, setSource] = useState('bundled evidence')

  useEffect(() => {
    let cancelled = false
    const bundled = BUNDLED[code] ?? ''
    setMd(bundled)
    setSource('bundled evidence')
    void (async () => {
      try {
        const res = await fetch(`/api/narratives/${code}`)
        if (!res.ok) return
        const text = await res.text()
        if (!cancelled && text.includes('Speaking script')) {
          setMd(text)
          setSource('live export')
        }
      } catch {
        /* bundled already showing */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code])

  const sections = useMemo(() => parseScript(md), [md])
  const images = sections.flatMap((s) => s.figures)
  const pack = eligibility.verticals.find((v) => v.vertical === code)

  return (
    <main className="div">
      <p className="div-kicker">ClarityDocs · speaking scripts · not a slide deck</p>
      <p className="div-verdict div-verdict-pass">Exports</p>
      <h1 className="div-title">Narratives</h1>
      <p className="div-lede">
        Speaker notes for the room. Figures, where warranted, are presenter
        visuals — never a slide canvas.
      </p>
      <p className="div-rule">
        Reading {source}. Markdown and DOCX names stay pitch-script, not deck.
      </p>

      <section className="div-grid-wrap nar-list" aria-label="Available exports">
        <h2 className="div-grid-title">Four verticals</h2>
        <table className="div-grid">
          <thead>
            <tr>
              <th scope="col">Vertical</th>
              <th scope="col">Markdown</th>
              <th scope="col">DOCX</th>
              <th scope="col">Images</th>
            </tr>
          </thead>
          <tbody>
            {CODES.map((c) => (
              <tr key={c} className={c === code ? 'is-vertical' : 'is-shared'}>
                <th scope="row">
                  <button type="button" className="nar-pick" onClick={() => setCode(c)}>
                    {c}
                  </button>
                </th>
                <td className="div-cell">pitch-script-{c}-claritydocs.md</td>
                <td className="div-cell">
                  <a className="nar-a" href={`/api/narratives/${c}?format=docx`}>
                    docx
                  </a>
                </td>
                <td className="div-weight">
                  {imageSummary(c, c === code ? images.length : null)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="nar-script" aria-label={`Speaker notes for ${code}`}>
        <h2 className="div-grid-title">{code}</h2>
        {pack ? (
          <p className="div-notes">
            {pack.sections.map((s) => (
              <span key={s.section_number}>
                §{s.section_number} {s.warranted ? 'image warranted' : 'no image'}: {s.reason}.
              </span>
            ))}
          </p>
        ) : null}

        {images.length > 0 ? (
          <div className="nar-gallery">
            {images.map((fig) => (
              <figure key={fig.src} className="nar-figure">
                <img src={fig.src} alt={fig.alt} />
                <figcaption>{fig.alt || 'Presenter visual (not a slide)'}</figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <p className="div-notes">
            <span>No presenter visual in this export — eligibility is decided per section, never forced.</span>
          </p>
        )}

        {sections.map((sec) => (
          <article key={sec.n} className="nar-sec">
            <p className="div-mean-label">
              §{sec.n} · {sec.title}
            </p>
            {sec.talkingPoint ? (
              <>
                <p className="div-mean-label">Talking point</p>
                <p className="nar-talk">{sec.talkingPoint}</p>
              </>
            ) : null}
            {sec.notes.map((note, i) => (
              <div key={`${sec.n}-n-${i}`}>
                <p className="div-mean-label">Speaker notes</p>
                <p className="nar-notes">{note}</p>
              </div>
            ))}
          </article>
        ))}
      </section>
    </main>
  )
}

function imageSummary(_code: string, liveCount: number | null): string {
  if (liveCount && liveCount > 0) return `${liveCount} embedded`
  return '2 warranted'
}
