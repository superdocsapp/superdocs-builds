// @ts-check
/**
 * An ApprovalSet gives every PRISM DELTA change a stable change_id and
 * tracks a human decision for each. Decisions can be made in any order and
 * changed any number of times before applying — both are explicit spec
 * requirements ("out-of-order decisions", "repeated decisions"), not just
 * accidental side effects of using a Map.
 */

/**
 * @typedef {{type: string, opIndex: number, findings: Array<{category: string, materiality: string, why: string}>, baseText?: string, targetText?: string, items?: object[]}} DeltaChange
 */

/**
 * @param {{changes: DeltaChange[]}} report - a PRISM DELTA report (buildDeltaReport output)
 */
export function createApprovalSet(report) {
  /** @type {Map<string, {changeId: string, change: DeltaChange, decision: 'pending'|'approved'|'rejected'|'edited', editedParagraphs: object[]|null}>} */
  const decisions = new Map();
  report.changes.forEach((change, i) => {
    const changeId = `delta-${String(i + 1).padStart(4, '0')}`;
    decisions.set(changeId, { changeId, change, decision: 'pending', editedParagraphs: null });
  });
  return { decisions };
}

const VALID_DECISIONS = new Set(['approved', 'rejected', 'edited', 'pending']);

/**
 * @param {ReturnType<typeof createApprovalSet>} approvalSet
 * @param {string} changeId
 * @param {string} decision - validated at runtime against VALID_DECISIONS below; typed as string (not a literal union) because callers (e.g. @prism/ui's JSON API) receive this as arbitrary external input that this function's job is to validate, not to already be statically narrowed
 * @param {{editedParagraphs?: object[]}} [opts]
 */
export function decide(approvalSet, changeId, decision, opts = {}) {
  if (!approvalSet.decisions.has(changeId)) {
    throw new Error(`Gate: unknown changeId "${changeId}". Known ids: ${[...approvalSet.decisions.keys()].join(', ')}`);
  }
  if (!VALID_DECISIONS.has(decision)) {
    throw new Error(`Gate: invalid decision "${decision}". Must be one of ${[...VALID_DECISIONS].join(', ')}.`);
  }
  if (decision === 'edited' && (!opts.editedParagraphs || opts.editedParagraphs.length === 0)) {
    throw new Error(`Gate: decision "edited" for ${changeId} requires opts.editedParagraphs (non-empty).`);
  }
  const entry = approvalSet.decisions.get(changeId);
  // The VALID_DECISIONS check above already proved `decision` is one of the
  // four valid values — this cast makes that runtime-established invariant
  // visible to the type checker instead of widening the stored field's type.
  entry.decision = /** @type {'pending'|'approved'|'rejected'|'edited'} */ (decision);
  entry.editedParagraphs = decision === 'edited' ? opts.editedParagraphs : null;
  return { ...entry };
}

export function isFullyDecided(approvalSet) {
  return [...approvalSet.decisions.values()].every((e) => e.decision !== 'pending');
}

export function summarize(approvalSet) {
  const all = [...approvalSet.decisions.values()];
  return {
    total: all.length,
    approved: all.filter((e) => e.decision === 'approved').length,
    rejected: all.filter((e) => e.decision === 'rejected').length,
    edited: all.filter((e) => e.decision === 'edited').length,
    pending: all.filter((e) => e.decision === 'pending').length,
  };
}
