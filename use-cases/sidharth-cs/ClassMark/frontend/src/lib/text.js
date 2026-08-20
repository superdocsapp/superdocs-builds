// Text helpers shared by the UI and its node:test suite (no DOM required).

// DOM-based HTML -> visible text, for display. Browser only.
export function stripHtml(html) {
  if (!html) return ''
  if (typeof document === 'undefined') return normalizeText(html)
  const div = document.createElement('div')
  div.innerHTML = html
  return div.textContent || ''
}

// Minimal, conservative normalization for no-op classification:
// strip tags, normalize line endings, collapse whitespace, trim.
// Deliberately NOT aggressive — case-sensitive and punctuation-sensitive,
// so case-only or punctuation-only edits remain actionable.
export function normalizeText(s) {
  if (!s) return ''
  return String(s)
    .replace(/<[^>]*>/g, ' ')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split(/\s+/)
    .join(' ')
    .trim()
}

// A "no-op" proposal: the before/after text is identical once normalized.
// SuperDocs genuinely returns such proposals (live-observed: unchanged
// heading and paragraph chunks). They are flagged, never discarded, and
// require no teacher decision.
export function isNoOpChange(change) {
  const before = normalizeText(change?.old_html)
  const after = normalizeText(change?.new_html)
  if (!before || !after) return false
  return before === after
}

// What the UI should offer for a change: no-op proposals get an
// informational treatment; genuine changes get Approve/Reject.
export function reviewActionsFor(change) {
  return isNoOpChange(change) ? 'noop' : 'decide'
}

// Decision counts over the ACTIONABLE subset only — no-op changes are
// excluded from approved/rejected/pending (they need no decision) but
// reported separately.
export function countDecisions(changes) {
  const counts = { approved: 0, rejected: 0, pending: 0, noop: 0 }
  for (const c of changes || []) {
    if (isNoOpChange(c)) counts.noop += 1
    else if (c.decision === 'approved') counts.approved += 1
    else if (c.decision === 'rejected') counts.rejected += 1
    else counts.pending += 1
  }
  return counts
}

// The explanation shown to the teacher. SuperDocs' generic "Parallel
// edit: …" boilerplate is engine metadata, not useful review feedback —
// hidden from the teacher UI. Only the explanation FIELD is filtered;
// the suggested text itself always passes through verbatim.
export function explanationForDisplay(change) {
  const exp = change?.ai_explanation
  if (!exp) return null
  if (/^parallel edit/i.test(exp.trim())) return null
  return exp
}
