// @ts-check
/**
 * Turns a decided ApprovalSet into an actual .docx: walks every aligned op
 * from the PRISM DELTA report (not just the "interesting" ones — untouched
 * common paragraphs must still appear in the output) and picks base,
 * target, or an edited replacement per the recorded decision, then writes
 * the result via @prism/core's real OOXML writer.
 *
 * Refuses to run against an undecided ApprovalSet rather than guessing a
 * default for 'pending' items — "never guess silently" applies to applying
 * changes just as much as to classifying them.
 */
import { writeDocx } from '@prism/core';
import { isFullyDecided } from './approval.js';

/**
 * @typedef {{ sourcePath: string, paragraphs: object[], tables: object[], hasTables: boolean, trailingOrderedNodes: object[], rawDocument: object }} BaseDoc
 * @typedef {{ ops: Array<{type: string, base?: object, target?: object, items?: object[]}>, changes: Array<{opIndex: number}>, baseDoc: BaseDoc }} DeltaReport
 */

/**
 * @param {DeltaReport} report
 * @param {ReturnType<typeof import('./approval.js').createApprovalSet>} approvalSet
 * @param {string} outputPath
 */
export async function applyApprovedChanges(report, approvalSet, outputPath) {
  if (!isFullyDecided(approvalSet)) {
    const pending = [...approvalSet.decisions.values()].filter((e) => e.decision === 'pending').map((e) => e.changeId);
    throw new Error(`Gate: cannot apply — ${pending.length} change(s) still pending: ${pending.join(', ')}. Decide every change first.`);
  }

  const decisionByOpIndex = new Map();
  for (const entry of approvalSet.decisions.values()) {
    decisionByOpIndex.set(entry.change.opIndex, entry);
  }

  const finalParagraphs = [];
  const appliedLog = [];

  report.ops.forEach((op, opIndex) => {
    const entry = decisionByOpIndex.get(opIndex);

    if (!entry) {
      // No change entry for this op: a true no-op (identical text AND
      // formatting). Structural/modified/formatting ops always produce a
      // change entry in build-report.js, so this path is only reached for
      // genuinely unchanged 'common' pairs.
      if (op.type === 'common') finalParagraphs.push(op.base);
      return;
    }

    const { decision, editedParagraphs, changeId } = entry;

    if (op.type === 'modified' || op.type === 'common') {
      // 'common' here means a formatting-only change (see build-report.js);
      // both are a single base/target paragraph pair either way.
      if (decision === 'approved') finalParagraphs.push(op.target);
      else if (decision === 'rejected') finalParagraphs.push(op.base);
      else if (decision === 'edited') finalParagraphs.push(...editedParagraphs);
    } else if (op.type === 'added') {
      if (decision === 'approved') finalParagraphs.push(...op.items);
      else if (decision === 'edited') finalParagraphs.push(...editedParagraphs);
      // rejected: omit — the proposed new paragraph(s) never make it in.
    } else if (op.type === 'removed') {
      if (decision === 'rejected') finalParagraphs.push(...op.items); // rejected the deletion: keep it
      else if (decision === 'edited') finalParagraphs.push(...editedParagraphs);
      // approved: omit — the deletion is confirmed.
    }

    appliedLog.push({ changeId, opType: op.type, decision });
  });

  const reindexed = finalParagraphs.map((p, i) => ({ ...p, index: i }));
  const writeResult = await writeDocx(report.baseDoc, reindexed, outputPath);

  return { ...writeResult, appliedLog, finalParagraphCount: reindexed.length };
}
