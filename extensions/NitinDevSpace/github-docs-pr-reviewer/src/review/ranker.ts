import type { Finding, FindingSeverity } from "./findings.js";

const severityWeight: Record<FindingSeverity, number> = {
  blocker: 3,
  warning: 2,
  suggestion: 1
};

export type RankedFindings = {
  posted: Finding[];
  suppressed: Finding[];
};

export function rankFindings(
  findings: Finding[],
  options: { maxPosted?: number } = {}
): RankedFindings {
  const maxPosted = options.maxPosted ?? 5;
  const deduped = dedupeFindings(findings);
  const sorted = [...deduped].sort((a, b) => {
    const severityDelta = severityWeight[b.severity] - severityWeight[a.severity];
    if (severityDelta !== 0) return severityDelta;

    const pathDelta = a.path.localeCompare(b.path);
    if (pathDelta !== 0) return pathDelta;

    return a.startLine - b.startLine;
  });

  return {
    posted: sorted.slice(0, maxPosted),
    suppressed: sorted.slice(maxPosted)
  };
}

function dedupeFindings(findings: Finding[]): Finding[] {
  const seen = new Set<string>();
  const deduped: Finding[] = [];

  for (const finding of findings) {
    const key = [
      finding.path,
      finding.startLine,
      finding.category,
      finding.title
    ].join(":");

    if (seen.has(key)) continue;

    seen.add(key);
    deduped.push(finding);
  }

  return deduped;
}

