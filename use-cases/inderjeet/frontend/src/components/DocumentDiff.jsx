import React from 'react'

export default function DocumentDiff({ original, proposed, sectionName }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0, color: 'var(--text-secondary)' }}>
        Itinerary Segment surgery: {sectionName || 'Flight Details'}
      </h3>
      <div className="grid-2">
        <div>
          <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--error-color)' }}>
            Original Segment (Removed)
          </strong>
          <div className="diff-view" style={{ borderLeft: '4px solid var(--error-color)' }}>
            <span className="diff-del">{original || 'Flight AA123 departs London Heathrow 10:00 AM.'}</span>
          </div>
        </div>
        <div>
          <strong style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--success-color)' }}>
            Proposed Update (Added)
          </strong>
          <div className="diff-view" style={{ borderLeft: '4px solid var(--success-color)' }}>
            <span className="diff-ins">{proposed || 'Flight AA456 departs London Heathrow 2:30 PM.'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
