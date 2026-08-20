// Actionable error surface. The message is always human-readable (the API
// layer guarantees that); raw detail hides behind an expander.
export default function ErrorBanner({ title, message, onRetry, retryLabel = 'Try again', detail }) {
  if (!message) return null
  return (
    <div className="error-banner" role="alert">
      {title && <strong>{title}</strong>}
      <p>{message}</p>
      <div className="error-actions">
        {onRetry && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
            {retryLabel}
          </button>
        )}
        {detail && (
          <details className="tech-details">
            <summary>Technical details</summary>
            <pre className="tech-pre">{typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  )
}
