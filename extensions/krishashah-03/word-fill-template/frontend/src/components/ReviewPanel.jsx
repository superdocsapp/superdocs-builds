import { humanizeLabel } from '../format.js'

const STATUS_LABELS = {
  ready: 'Ready',
  missing: 'Missing',
}

export default function ReviewPanel({ proposedChanges, conditions, onApply, isApplying }) {
  const readyCount = proposedChanges.filter((change) => change.status === 'ready').length

  return (
    <section className="panel">
      <h2>Review</h2>
      <p className="muted-text">Proposed Changes</p>

      <ul className="change-list">
        {proposedChanges.map((change) => (
          <li key={change.field} className={`change-item change-item--${change.status}`}>
            <div className="change-label">{humanizeLabel(change.field)}</div>
            <div className="change-diff">
              <span className="placeholder-text">{change.placeholder}</span>
              <span className="arrow">→</span>
              <span className="proposed-value">
                {change.proposed_value === null || change.proposed_value === undefined
                  ? 'No value provided'
                  : String(change.proposed_value)}
              </span>
            </div>
            <span className={`status-badge status-badge--${change.status}`}>
              {STATUS_LABELS[change.status] || change.status}
            </span>
          </li>
        ))}
      </ul>

      {conditions && conditions.length > 0 && (
        <div className="condition-summary">
          <h3>Conditional Sections</h3>
          <ul>
            {conditions.map((condition) => (
              <li key={condition.condition_key}>
                {humanizeLabel(condition.condition_key)}:{' '}
                {condition.resolved
                  ? condition.include
                    ? 'Section will be included'
                    : 'Section will be removed'
                  : 'Unresolved — section left as-is'}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        className="primary-button"
        onClick={onApply}
        disabled={isApplying || readyCount === 0}
      >
        {isApplying ? 'Applying…' : 'Apply to Word'}
      </button>
    </section>
  )
}
