import { useState } from 'react'

import { humanizeLabel } from '../format.js'

export default function GapList({ gaps, onRevalidate }) {
  const [corrections, setCorrections] = useState({})

  if (!gaps || gaps.length === 0) {
    return (
      <section className="panel">
        <h2>Missing Information</h2>
        <p className="success-text">None</p>
      </section>
    )
  }

  function handleChange(field, value) {
    setCorrections((prev) => ({ ...prev, [field]: value }))
  }

  function handleSubmit() {
    const nonEmpty = Object.fromEntries(
      Object.entries(corrections).filter(([, value]) => value.trim() !== ''),
    )
    onRevalidate(nonEmpty)
  }

  return (
    <section className="panel">
      <h2>⚠ Missing Information</h2>
      <ul className="gap-list">
        {gaps.map((gap) => (
          <li key={gap.field} className="gap-item">
            <label htmlFor={`gap-${gap.field}`}>
              <span>{humanizeLabel(gap.field)}</span>
              <span className="gap-reason">{gap.reason}</span>
            </label>
            <input
              id={`gap-${gap.field}`}
              type="text"
              value={corrections[gap.field] || ''}
              onChange={(event) => handleChange(gap.field, event.target.value)}
              placeholder="Enter value"
            />
          </li>
        ))}
      </ul>
      <button type="button" className="secondary-button" onClick={handleSubmit}>
        Revalidate
      </button>
    </section>
  )
}
