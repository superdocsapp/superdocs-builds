// @ts-check
/**
 * Selecting "compare, review, apply, version" composes three independently
 * real capabilities through one explicit state machine. VERIFYING is not
 * decorative: it re-runs PRISM DELTA against the written output and only
 * transitions to VERIFIED if the remaining diff exactly matches what the
 * approval decisions predicted. A mismatch transitions to UNVERIFIED, which
 * per the workflow graph has no path to EXPORTED — an unverified result
 * cannot be published as verified, structurally, not by convention.
 */
import { compareFiles } from '@prism/delta';
import { createApprovalSet, decide, isFullyDecided, summarize, applyApprovedChanges } from '@prism/gate';
import { readDocx } from '@prism/core';
import { Vault } from '@prism/vault';
import { Workflow } from './workflow-engine.js';

/**
 * @param {DecisionValue} decisionValue
 * @returns {{decisionName: string, decisionOpts: {editedParagraphs?: object[]}}}
 */
function normalizeDecision(decisionValue) {
  if (typeof decisionValue === 'string') {
    return { decisionName: decisionValue, decisionOpts: {} };
  }
  return { decisionName: decisionValue.decision, decisionOpts: decisionValue.opts ?? {} };
}

/**
 * @typedef {string | {decision: string, opts?: {editedParagraphs?: object[]}}} DecisionValue
 * @param {{basePath: string, targetPath: string, decisions: Record<string, DecisionValue>, outputPath: string, vault?: Vault}} opts
 */
export async function runComposedWorkflow({ basePath, targetPath, decisions, outputPath, vault = new Vault() }) {
  const wf = new Workflow('compare-review-apply-version');
  const log = [];
  const record = (msg) => log.push({ at: new Date().toISOString(), msg });

  try {
    wf.transition('INGESTING');
    record(`Ingesting ${basePath} and ${targetPath}`);

    wf.transition('UNDERSTANDING');
    const report = await compareFiles(basePath, targetPath);
    record(`PRISM DELTA found ${report.summary.totalChanges} change(s)`);

    wf.transition('PLANNING');
    const approvalSet = createApprovalSet(report);

    wf.transition('PROPOSED');
    wf.transition('AWAITING_REVIEW');

    for (const [changeId, decisionValue] of Object.entries(decisions)) {
      const { decisionName, decisionOpts } = normalizeDecision(decisionValue);
      decide(approvalSet, changeId, decisionName, decisionOpts);
    }

    if (!isFullyDecided(approvalSet)) {
      wf.transition('NEEDS_REVIEW');
      throw new Error('Workflow: not every change was decided — see log for which are still pending.');
    }
    const decisionSummary = summarize(approvalSet);
    record(`Decisions: ${JSON.stringify(decisionSummary)}`);

    wf.transition('PARTIALLY_APPROVED');
    wf.transition('APPLYING');
    const applyResult = await applyApprovedChanges(report, approvalSet, outputPath);
    record(`PRISM GATE applied ${applyResult.appliedLog.length} decision(s) -> ${outputPath}`);

    wf.transition('VERIFYING');
    const verifyDiff = await compareFiles(outputPath, basePath);
    const expectedRemaining = decisionSummary.approved + decisionSummary.edited;
    if (verifyDiff.summary.totalChanges !== expectedRemaining) {
      wf.transition('UNVERIFIED');
      throw new Error(
        `Workflow: verification failed — expected ${expectedRemaining} change(s) to now differ from base, ` +
          `found ${verifyDiff.summary.totalChanges}. Refusing to mark VERIFIED.`,
      );
    }
    wf.transition('VERIFIED');
    record(`Verified: applied output differs from base by exactly ${expectedRemaining} change(s), as predicted by the decisions`);

    const outputDoc = await readDocx(outputPath);
    const version = vault.commit(outputDoc.paragraphs, { label: 'gate-applied-and-verified', kind: 'commit' });
    record(`PRISM VAULT committed version ${version.versionId}`);

    wf.transition('EXPORTED');

    return { workflow: wf, report, approvalSet, applyResult, vault, version, outputPath, log };
  } catch (err) {
    if (wf.state !== 'FAILED' && !wf.isTerminal()) {
      try {
        wf.transition('FAILED');
      } catch {
        /* already in a terminal failure state (e.g. UNVERIFIED, NEEDS_REVIEW) — leave it there, don't mask the real error */
      }
    }
    record(`ERROR: ${err.message}`);
    err.workflow = wf;
    err.log = log;
    throw err;
  }
}
