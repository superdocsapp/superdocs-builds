/**
 * Baselines.
 *
 * The first run of this check on an integration that has been shipping for a
 * year will find real problems that cannot all be fixed today. Without a way to
 * accept the known ones, the check gets switched off, and a check that is
 * switched off finds nothing. A baseline records what is already known so the
 * pipeline can fail on what is new.
 */

export const BASELINE_VERSION = 1;

export function createBaseline(report, options = {}) {
  return {
    baselineVersion: BASELINE_VERSION,
    idAttribute: report.idAttribute,
    note: options.note
      || 'Findings accepted as known. Delete an entry to make the check fail on it again.',
    accepted: report.findings
      .filter((finding) => finding.severity === 'error' || finding.severity === 'warning')
      .map((finding) => ({
        key: finding.key,
        rule: finding.rule,
        id: finding.id,
        where: finding.locator ? finding.locator.path : null,
        text: finding.locator ? finding.locator.preview : null,
      })),
  };
}

/**
 * Returns a new report with baselined findings moved aside. The findings are
 * kept, not deleted -- a baseline hides a failure from the exit code, never from
 * the report.
 */
export function applyBaseline(report, baseline) {
  if (!baseline || !Array.isArray(baseline.accepted)) return report;
  const accepted = new Set(baseline.accepted.map((entry) => entry.key));
  if (accepted.size === 0) return report;

  const findings = [];
  const baselined = [];
  for (const finding of report.findings) {
    if (accepted.has(finding.key)) baselined.push({ ...finding, baselined: true });
    else findings.push(finding);
  }

  const summary = { error: 0, warning: 0, info: 0, notice: 0 };
  for (const finding of findings) summary[finding.severity] += 1;

  return {
    ...report,
    findings,
    baselined,
    summary,
    ok: summary.error === 0,
    baselineApplied: {
      accepted: accepted.size,
      matched: baselined.length,
      stale: [...accepted].filter((key) => !baselined.some((finding) => finding.key === key)).length,
    },
  };
}
