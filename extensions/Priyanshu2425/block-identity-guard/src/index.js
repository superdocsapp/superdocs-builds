/**
 * superdocs-block-identity-guard
 *
 * Validates a SuperDocs document round trip and reports precisely which blocks
 * lost their identifier, where they are, and what the likely cause was.
 *
 *   import { checkRoundTrip, formatReport } from 'superdocs-block-identity-guard';
 *
 *   const report = checkRoundTrip(incomingHtml, editor.getHTML());
 *   if (!report.ok) console.log(formatReport(report));
 */

import { analyse, resolveOptions, SCHEMA_VERSION } from './analyse.js';
import { formatHuman } from './format/human.js';
import { formatJson } from './format/json.js';
import { formatGithub } from './format/github.js';
import { RULES, SEVERITIES, atLeastAsSevere, severityRank } from './rules.js';
import { createBaseline, applyBaseline } from './baseline.js';
import { extractDocumentHtml } from './capture.js';

/**
 * @param {string} beforeHtml HTML as SuperDocs sent it
 * @param {string} afterHtml HTML as your integration serialised it back
 * @param {object} [options]
 */
export function checkRoundTrip(beforeHtml, afterHtml, options) {
  return analyse(beforeHtml, afterHtml, options);
}

export class RoundTripError extends Error {
  constructor(report, message) {
    super(message);
    this.name = 'RoundTripError';
    this.report = report;
  }
}

/**
 * The assertion form, for an editor integration's own test suite. This is the
 * replacement for the three-line `console.assert` in the integration guide: same
 * position in your test, an answer instead of a boolean.
 *
 * @throws {RoundTripError} when the round trip loses identity
 */
export function assertRoundTrip(beforeHtml, afterHtml, options = {}) {
  const report = checkRoundTrip(beforeHtml, afterHtml, options);
  const threshold = options.failOn || 'error';
  if (!hasFindingsAtLeast(report, threshold)) return report;
  throw new RoundTripError(report, formatHuman(report, { colour: false }));
}

/** True when the report carries a finding at or above `threshold`. */
export function hasFindingsAtLeast(report, threshold = 'error') {
  if (threshold === 'never') return false;
  return report.findings.some((finding) => atLeastAsSevere(finding.severity, threshold));
}

/**
 * @param {object} report
 * @param {{ format?: 'human'|'json'|'github', colour?: boolean, file?: string, compact?: boolean }} [options]
 */
export function formatReport(report, options = {}) {
  switch (options.format || 'human') {
    case 'json':
      return formatJson(report, options);
    case 'github':
      return formatGithub(report, options);
    case 'human':
      return formatHuman(report, options);
    default:
      throw new Error(`unknown format: ${options.format}`);
  }
}

export {
  analyse,
  resolveOptions,
  formatHuman,
  formatJson,
  formatGithub,
  createBaseline,
  applyBaseline,
  extractDocumentHtml,
  RULES,
  SEVERITIES,
  severityRank,
  atLeastAsSevere,
  SCHEMA_VERSION,
};
