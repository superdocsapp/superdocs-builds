import React, { useState } from 'react'

export default function ReviewCard({ traveler, onDecision }) {
  const [letterText, setLetterText] = useState(traveler.explanation_letter || '')

  const handleApprove = () => {
    onDecision(traveler.id, 'APPROVED', letterText)
  }

  const handleReject = () => {
    onDecision(traveler.id, 'REJECTED', letterText)
  }

  return (
    <div className="card" style={{ borderLeft: traveler.approval_status === 'APPROVED' ? '6px solid var(--success-color)' : traveler.approval_status === 'REJECTED' ? '6px solid var(--error-color)' : '6px solid var(--warning-color)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h3 style={{ margin: '0 0 0.5rem 0' }}>{traveler.passenger_name}</h3>
          <span style={{ marginRight: '1rem', color: 'var(--text-secondary)' }}>Email: {traveler.email}</span>
          <span style={{ marginRight: '1rem' }}>Language: <strong style={{ textTransform: 'uppercase' }}>{traveler.language}</strong></span>
          <span>Status: <strong>{traveler.loyalty_status}</strong></span>
        </div>
        <span className={`badge badge-${traveler.approval_status.toLowerCase()}`}>
          {traveler.approval_status}
        </span>
      </div>

      <div style={{ marginTop: '1.5rem' }}>
        <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.5rem' }}>
          Empathetic Explanation Letter (Verify/Edit):
        </label>
        <textarea
          style={{ width: '100%', minHeight: '120px', padding: '0.75rem', borderRadius: '6px', border: '1px solid var(--border-color)', boxSizing: 'border-box', fontFamily: 'inherit' }}
          value={letterText}
          onChange={(e) => setLetterText(e.target.value)}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--border-color)' }}>
        <div>
          <span>Voucher Claim Status: </span>
          <strong style={{ color: traveler.voucher_status === 'ELIGIBLE' ? 'var(--success-color)' : 'var(--text-secondary)' }}>
            {traveler.voucher_status}
          </strong>
        </div>
        
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button className="button button-success" onClick={handleApprove}>
            Approve Bundle
          </button>
          <button className="button button-error" onClick={handleReject}>
            Reject Bundle
          </button>
        </div>
      </div>
    </div>
  )
}
