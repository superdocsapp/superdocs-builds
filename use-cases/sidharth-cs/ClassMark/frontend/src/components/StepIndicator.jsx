// Two navigational aids:
//  - Breadcrumb for the selection phase (Course › Assignment › Submission)
//  - Workflow stepper showing review progress (done / active / upcoming)

const WORKFLOW_STAGES = [
  { key: 'document_retrieved', label: 'Document retrieved' },
  { key: 'superdocs_uploaded', label: 'Uploaded to SuperDocs' },
  { key: 'awaiting_approval', label: 'Teacher review' },
  { key: 'approval_complete', label: 'Approval complete' },
  { key: 'exported', label: 'Export' },
  { key: 'drive_uploaded', label: 'Upload to Drive' },
  { key: 'attached', label: 'Attach to Classroom' },
  { key: 'returned', label: 'Return' },
  { key: 'verified', label: 'Verify' },
]

const STAGE_INDEX = Object.fromEntries(
  WORKFLOW_STAGES.map((s, i) => [s.key, i])
)

export function stageIndexFor(state) {
  if (state === 'review_generated') return 2 // review reached, no changes
  if (state === 'blocked' || state === 'error') return STAGE_INDEX.awaiting_approval + 0.5
  return STAGE_INDEX[state] ?? 0
}

export function Breadcrumb({ crumbs }) {
  return (
    <nav className="breadcrumb" aria-label="Selection progress">
      {crumbs.map((c, i) => (
        <span key={i} className="crumb">
          {i > 0 && <span className="crumb-sep" aria-hidden="true">›</span>}
          <span className={c.active ? 'crumb-active' : ''}>{c.label}</span>
        </span>
      ))}
    </nav>
  )
}

export function WorkflowStepper({ state }) {
  const current = stageIndexFor(state)
  return (
    <ol className="stepper" aria-label="Review progress">
      {WORKFLOW_STAGES.map((s, i) => {
        const cls =
          i < current ? 'done' : i === current ? 'active' : 'upcoming'
        return (
          <li key={s.key} className={`step-${cls}`}>
            <span className="step-dot" aria-hidden="true">
              {i < current ? '✓' : ''}
            </span>
            <span className="step-label">{s.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
