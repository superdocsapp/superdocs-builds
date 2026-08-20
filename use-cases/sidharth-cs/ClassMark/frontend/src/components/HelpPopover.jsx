// Anchored Help/About popover. Pure presentational — open/close state and
// outside-click/Escape handling live in AppHeader (see helpToggle); this
// component only renders content. Never touches workflow or auth state.
import {
  HELP_TITLE,
  HELP_INTRO,
  HELP_SECTIONS,
  HELP_WORKFLOW,
  HELP_EXAMPLES_TITLE,
  HELP_EXAMPLES,
  HELP_REVIEW_TYPES_TITLE,
  HELP_REVIEW_TYPES,
  HELP_REVIEW_DEPTH_TITLE,
  HELP_REVIEW_DEPTH,
  HELP_HONESTY,
} from '../lib/helpContent.js'

export default function HelpPopover({ open, panelRef }) {
  if (!open) return null

  return (
    <div
      ref={panelRef}
      id="help-popover"
      role="dialog"
      aria-label={HELP_TITLE}
      tabIndex={-1}
      className="help-popover"
    >
      <h2 className="help-title">{HELP_TITLE}</h2>
      <p className="help-intro">{HELP_INTRO}</p>

      {HELP_SECTIONS.map((s) => (
        <section key={s.n} className="help-section">
          <h3>
            <span className="help-num" aria-hidden="true">{s.n}</span>
            {s.title}
          </h3>
          <p>{s.body}</p>
          {s.bullets && (
            <ul className="help-bullets">
              {s.bullets.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <div className="help-flow" aria-label="Workflow summary">
        {HELP_WORKFLOW.map((step, i) => (
          <span key={step} className="help-flow-step">
            <span className="help-flow-num" aria-hidden="true">{i + 1}</span>
            {step}
          </span>
        ))}
      </div>

      <details className="help-examples">
        <summary>{HELP_EXAMPLES_TITLE}</summary>
        <p>Your review instruction can be tailored to the assignment:</p>
        <ul>
          {HELP_EXAMPLES.map((ex) => (
            <li key={ex}>
              <em>{ex}</em>
            </li>
          ))}
        </ul>
      </details>

      <section className="help-review-options">
        <h3>{HELP_REVIEW_TYPES_TITLE}</h3>
        <ul className="help-bullets">
          {HELP_REVIEW_TYPES.map((reviewType) => <li key={reviewType}>{reviewType}</li>)}
        </ul>
        <h3>{HELP_REVIEW_DEPTH_TITLE}</h3>
        <p>{HELP_REVIEW_DEPTH}</p>
      </section>

      <p className="help-honesty">{HELP_HONESTY}</p>
    </div>
  )
}
