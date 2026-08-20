// Stage panels for the post-approval chain and terminal states.
// Every panel has ONE obvious primary action.
import { countDecisions } from '../lib/text.js'

export function ReviewSummary({ counts, onSubmit, busy }) {
  const { approved, rejected, pending, noop } = counts
  const actionable = approved + rejected + pending
  const ready = actionable > 0 && pending === 0
  return (
    <div className="panel review-summary">
      <h3 className="panel-title">
        {ready
          ? 'Ready to apply feedback'
          : `${actionable} ${actionable === 1 ? 'change requires' : 'changes require'} your decision`}
      </h3>
      <ul className="summary-counts">
        <li className="count-ok"><strong>{approved}</strong> approved</li>
        <li className="count-bad"><strong>{rejected}</strong> rejected</li>
        <li className={pending ? 'count-warn' : 'count-muted'}><strong>{pending}</strong> pending</li>
      </ul>
      {noop > 0 && (
        <p className="noop-excluded">
          {noop} {noop === 1 ? 'suggestion excluded' : 'suggestions excluded'} — no textual change
        </p>
      )}
      {ready && (
        <button type="button" className="btn btn-primary" onClick={onSubmit} disabled={busy}>
          {busy ? 'Submitting decisions…' : 'Submit review decisions'}
        </button>
      )}
    </div>
  )
}

export function NoChangesState({ onReset }) {
  return (
    <div className="panel">
      <h3 className="panel-title">Review produced no proposed changes</h3>
      <p className="panel-desc">
        Nothing was approved or rejected, so there is no reviewed document to
        export. This is the real result from the review engine — try a
        different instruction or start a new review.
      </p>
      <button type="button" className="btn btn-ghost" onClick={onReset}>Start a new review</button>
    </div>
  )
}

export function ExportPanel({ busy, onExport }) {
  return (
    <div className="panel">
      <h3 className="panel-title">Review complete</h3>
      <p className="panel-desc">The reviewed document is ready to export.</p>
      <button type="button" className="btn btn-primary" onClick={onExport} disabled={busy}>
        {busy ? 'Exporting…' : 'Export reviewed document'}
      </button>
    </div>
  )
}

export function DownloadPanel({ filename, downloadHref }) {
  return (
    <div className="panel transfer">
      <h3 className="panel-title">Reviewed document exported</h3>
      <p className="file-name"><span className="doc-icon" aria-hidden="true">DOCX</span>{filename}</p>
      <a className="btn btn-secondary" href={downloadHref}>Download reviewed document</a>
    </div>
  )
}

export function DriveUploadPanel({ busy, onUpload, filename }) {
  return (
    <div className="panel transfer">
      <h3 className="panel-title">Upload to Google Drive</h3>
      <div className="transfer-flow">
        <span className="file-name">{filename}</span>
        <span className="arrow" aria-hidden="true">↓</span>
        <span className="drive-target">Google Drive</span>
      </div>
      <button type="button" className="btn btn-primary" onClick={onUpload} disabled={busy}>
        {busy ? 'Uploading…' : 'Upload reviewed file'}
      </button>
    </div>
  )
}

export function AttachPanel({ busy, onAttach, filename, assignmentTitle }) {
  return (
    <div className="panel transfer">
      <h3 className="panel-title">Attach reviewed file to this submission</h3>
      <dl className="transfer-dl">
        <dt>Reviewed file</dt>
        <dd className="file-name">{filename}</dd>
        <dt>Destination</dt>
        <dd>{assignmentTitle} · Student submission</dd>
      </dl>
      <button type="button" className="btn btn-primary" onClick={onAttach} disabled={busy}>
        {busy ? 'Attaching…' : 'Attach to submission'}
      </button>
    </div>
  )
}

export function ReturnPanel({ busy, onReturn }) {
  return (
    <div className="panel">
      <h3 className="panel-title">Ready to return</h3>
      <p className="panel-desc">The reviewed document is attached to the student&apos;s submission.</p>
      <button type="button" className="btn btn-primary" onClick={onReturn} disabled={busy}>
        {busy ? 'Returning…' : 'Return submission to student'}
      </button>
    </div>
  )
}

export function VerifyPanel({ busy, onVerify }) {
  return (
    <div className="panel">
      <h3 className="panel-title">Submission returned</h3>
      <p className="panel-desc">Verify the reviewed file is still attached to the returned submission.</p>
      <button type="button" className="btn btn-primary" onClick={onVerify} disabled={busy}>
        {busy ? 'Verifying…' : 'Verify post-return state'}
      </button>
    </div>
  )
}

export function VerificationChecks({ checks }) {
  const labels = {
    submission_exists: 'Submission exists',
    submission_id_unchanged: 'Same submission preserved',
    reviewed_file_attached: 'Reviewed file attached',
  }
  return (
    <ul className="check-list">
      {Object.entries(checks || {}).map(([k, v]) => (
        <li key={k} className={v ? 'check-ok' : 'check-bad'}>
          <span className="check-icon" aria-hidden="true">{v ? '✓' : '✗'}</span>
          {labels[k] || k}
        </li>
      ))}
    </ul>
  )
}

export function FinalSuccess({ workflow, onReset, onDownload, downloadHref, filename }) {
  const { approved, rejected } = countDecisions(workflow.pending_changes)
  return (
    <div className="final-success">
      <div className="success-mark" aria-hidden="true">✓</div>
      <h2>Review complete</h2>
      <p className="panel-desc">The reviewed submission has been returned to the student.</p>
      <p className="summary-line">
        <strong>{approved}</strong> approved · <strong>{rejected}</strong> rejected
      </p>
      <p className="file-name">{filename || 'reviewed.docx'}</p>
      <VerificationChecks checks={workflow.verification?.checks || {}} />
      <div className="panel-actions">
        <a className="btn btn-secondary" href={downloadHref}>Download reviewed document</a>
        <button type="button" className="btn btn-ghost" onClick={onReset}>Start another review</button>
      </div>
      <p className="muted note">
        This verifies at the API level. Open Google Classroom as the student to
        confirm the returned submission shows the reviewed document.
      </p>
    </div>
  )
}

export function TerminalState({ workflow, onReset }) {
  const reason = workflow.state === 'blocked' ? workflow.blocker_reason : workflow.error
  return (
    <div className="panel">
      <h3 className="panel-title">
        {workflow.state === 'blocked' ? 'Review blocked' : 'Review could not continue'}
      </h3>
      <p className="panel-desc">
        {workflow.state === 'blocked'
          ? 'The native approval did not complete, so nothing can be exported or returned.'
          : 'The workflow stopped. Your review decisions (if any) are preserved.'}
      </p>
      {reason && (
        <details className="tech-details">
          <summary>Why this happened</summary>
          <p className="tech-reason">{reason}</p>
        </details>
      )}
      <button type="button" className="btn btn-ghost" onClick={onReset}>Start a new review</button>
    </div>
  )
}
