// Generic selectable list for courses / assignments / submissions.
// Handles loading (skeletons), empty, error, and item rendering.
import ErrorBannerInline from './ErrorBanner.jsx'

export function SkeletonRows({ rows = 4 }) {
  return (
    <ul className="selector-list" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="selector-item skeleton-row">
          <span className="skeleton skeleton-title" />
          <span className="skeleton skeleton-meta" />
        </li>
      ))}
    </ul>
  )
}

export default function SelectorList({
  title,
  subtitle,
  items,
  loading,
  error,
  onRetry,
  emptyMessage,
  renderItem,
}) {
  return (
    <section className="selector-section">
      <h2 className="section-title">{title}</h2>
      {subtitle && <p className="section-subtitle">{subtitle}</p>}
      {error && (
        <ErrorBannerInline message={error} onRetry={onRetry} />
      )}
      {loading ? (
        <SkeletonRows />
      ) : items.length === 0 && !error ? (
        <div className="empty-state">
          <p>{emptyMessage || 'Nothing here yet.'}</p>
          {onRetry && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
              Load
            </button>
          )}
        </div>
      ) : (
        <ul className="selector-list">
          {items.map((item) => renderItem(item))}
        </ul>
      )}
    </section>
  )
}
