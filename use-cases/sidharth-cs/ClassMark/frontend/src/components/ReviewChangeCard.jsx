// One proposed change, displayed as a document-review card.
// No-op proposals (identical normalized text) are flagged and render NO
// Approve/Reject controls — nothing for the teacher to decide, and the
// backend never receives a decision for them.
import { explanationForDisplay, reviewActionsFor, stripHtml } from '../lib/text.js'

export default function ReviewChangeCard({ change, index, onDecide, busy }) {
  const actions = reviewActionsFor(change)
  const noOp = actions === 'noop'
  const decided = change.decision !== 'pending'
  const explanation = explanationForDisplay(change)
  return (
    <li className={`change-card change-${change.decision}${noOp ? ' change-noop' : ''}`}>
      <div className="change-head">
        <span className="change-num">Change {String(index + 1).padStart(2, '0')}</span>
        <span className="op-tag">{change.operation || 'edit'}</span>
        {noOp && <span className="noop-tag">No textual change</span>}
      </div>

      <div className="diff">
        <div className="diff-col diff-original">
          <h4>Original</h4>
          <p>{stripHtml(change.old_html) || <em className="muted">(no before text provided)</em>}</p>
        </div>
        <div className="diff-col diff-suggested">
          <h4>Suggested</h4>
          <p>{stripHtml(change.new_html) || <em className="muted">(no after text provided)</em>}</p>
        </div>
      </div>

      {explanation && <p className="explanation">{explanation}</p>}

      {noOp ? (
        <p className="noop-note" role="status">
          No textual change — this suggestion does not modify the document
          and requires no decision.
        </p>
      ) : decided ? (
        <p className={`decided decided-${change.decision}`} role="status">
          {change.decision === 'approved' ? '✓ Approved' : '✗ Rejected'}
        </p>
      ) : (
        <div className="decide">
          <button
            type="button"
            className="btn btn-reject"
            onClick={() => onDecide(change.chunk_id, 'rejected')}
            disabled={busy}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12"/>
            </svg>
            Reject
          </button>
          <button
            type="button"
            className="btn btn-approve"
            onClick={() => onDecide(change.chunk_id, 'approved')}
            disabled={busy}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M20 6 9 17l-5-5"/>
            </svg>
            Approve
          </button>
        </div>
      )}
    </li>
  )
}
