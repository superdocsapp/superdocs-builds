// Raw identifiers live here, expanded only on demand — never in the
// primary interface.
export default function TechnicalDetails({ rows }) {
  const entries = Object.entries(rows || {}).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (entries.length === 0) return null
  return (
    <details className="tech-details">
      <summary>Technical details</summary>
      <dl>
        {entries.map(([k, v]) => (
          <div key={k} className="tech-row">
            <dt>{k}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
