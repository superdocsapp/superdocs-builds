import { REVIEW_DEPTHS, REVIEW_MODES, isCustomReview } from '../lib/reviewConfig.js'

// The browser presents semantic teacher choices only. The backend is the
// single authority that maps them to a SuperDocs configuration and constructs
// the final integrity-preserving instruction.
export default function ReviewInstruction({
  mode,
  depth,
  additionalInstructions,
  onModeChange,
  onDepthChange,
  onAdditionalInstructionsChange,
  onStart,
  busy,
}) {
  const custom = isCustomReview(mode)
  const customMissingInstruction = custom && !additionalInstructions.trim()

  return (
    <div className="panel">
      <h3 className="panel-title">Configure your review</h3>
      <p className="panel-desc">
        Choose what to review. Classmark will propose changes for you to
        approve or reject before anything is returned to the student.
      </p>

      <fieldset className="review-fieldset">
        <legend className="field-label">Review type</legend>
        <div className="review-mode-grid">
          {REVIEW_MODES.map((option) => (
            <label
              key={option.value}
              className={`review-option ${mode === option.value ? 'review-option-selected' : ''}`}
            >
              <input
                type="radio"
                name="review-mode"
                value={option.value}
                checked={mode === option.value}
                onChange={() => onModeChange(option.value)}
                disabled={busy}
              />
              <span className="review-option-copy">
                <strong>{option.label}</strong>
                <small>{option.description}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="review-fieldset review-depth-fieldset">
        <legend className="field-label">Review depth</legend>
        <div className="review-depth-grid">
          {REVIEW_DEPTHS.map((option) => (
            <label
              key={option.value}
              className={`review-depth-option ${depth === option.value ? 'review-depth-selected' : ''}`}
            >
              <input
                type="radio"
                name="review-depth"
                value={option.value}
                checked={depth === option.value}
                onChange={() => onDepthChange(option.value)}
                disabled={busy}
              />
              <span>
                <strong>{option.label}</strong>
                <small>{option.description}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="field-label" htmlFor="additional-instructions">
        {custom ? 'Tell SuperDocs exactly what you want reviewed' : 'Additional instructions (optional)'}
      </label>
      <textarea
        id="additional-instructions"
        className="instruction-textarea"
        value={additionalInstructions}
        onChange={(e) => onAdditionalInstructionsChange(e.target.value)}
        placeholder={custom
          ? 'For example: Focus on sentence fragments and preserve the student’s informal voice.'
          : 'For example: Pay particular attention to paragraph transitions.'}
        rows={custom ? 5 : 3}
        disabled={busy}
        required={custom}
      />
      {customMissingInstruction && (
        <p className="field-hint field-hint-warning">Custom review needs instructions before it can start.</p>
      )}

      <div className="review-assurance">
        Suggestions stay under your control: you approve or reject every proposed change.
      </div>
      <div className="panel-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={onStart}
          disabled={busy || customMissingInstruction}
        >
          {busy ? 'Starting review…' : 'Start review'}
        </button>
      </div>
    </div>
  )
}
