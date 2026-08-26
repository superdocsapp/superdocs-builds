import './Divergence.css'
import './Verticals.css'

export type VerticalPack = {
  code: string
  display_name: string
  buyer_role: string
  regulatory_trigger: string
  document_pain: string
  typical_objection: string
  proof_point: string
  terminology: string[]
}

export type VerticalsFile = {
  product: string
  note: string
  packs: VerticalPack[]
}

type Props = {
  file: VerticalsFile
}

const FIELDS: { key: keyof VerticalPack; label: string }[] = [
  { key: 'buyer_role', label: 'Buyer' },
  { key: 'regulatory_trigger', label: 'Regulatory trigger' },
  { key: 'document_pain', label: 'Document pain' },
  { key: 'typical_objection', label: 'Objection' },
  { key: 'proof_point', label: 'Proof' },
]

export default function Verticals({ file }: Props) {
  return (
    <main className="div">
      <p className="div-kicker">ClarityDocs · speaking scripts · not a slide deck</p>
      <p className="div-verdict div-verdict-pass">Knowledge files</p>
      <h1 className="div-title">Verticals</h1>
      <p className="div-lede">
        One product. Four named pitches. Buyer, trigger, pain, objection, and proof
        are data in YAML — not blanks in a shared skeleton.
      </p>
      <p className="div-rule">{file.note}</p>

      <section className="vert-list" aria-label="Vertical knowledge packs">
        {file.packs.map((pack) => (
          <article key={pack.code} className="vert-card">
            <p className="div-mean-label">{pack.code}</p>
            <h2 className="vert-name">{pack.display_name}</h2>
            {FIELDS.map((f) => (
              <div key={f.key} className="vert-field">
                <p className="div-mean-label">{f.label}</p>
                <p className="vert-body">{String(pack[f.key])}</p>
              </div>
            ))}
            <p className="div-mean-label">Terminology</p>
            <p className="vert-terms">
              {pack.terminology.map((t) => (
                <span key={t}>{t}</span>
              ))}
            </p>
          </article>
        ))}
      </section>
    </main>
  )
}
