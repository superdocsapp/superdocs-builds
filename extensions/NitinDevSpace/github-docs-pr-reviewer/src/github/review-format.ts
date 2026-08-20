import type { Finding } from "../review/findings.js";
import type { StaticReviewResult } from "../review/runner.js";

export const summaryMarkerPrefix = "<!-- superdocs-docs-pr-reviewer";

export type PullRequestTarget = {
  owner: string;
  repo: string;
  pullNumber: number;
  headSha: string;
};

export type PreviewArtifact = {
  url: string;
  label: string;
};

export function summaryMarker(headSha: string): string {
  return `${summaryMarkerPrefix}:${headSha} -->`;
}

export function formatSummaryComment({
  target,
  review,
  preview
}: {
  target: PullRequestTarget;
  review: StaticReviewResult;
  preview?: PreviewArtifact;
}): string {
  const severityCounts = countSeverities(review.findings);
  const status =
    review.findings.length === 0
      ? "No static docs issues found."
      : `${review.findings.length} finding${review.findings.length === 1 ? "" : "s"} found.`;

  const previewLine = preview
    ? `\nPreview: [${preview.label}](${preview.url})`
    : "\nPreview: not generated yet.";

  return [
    summaryMarker(target.headSha),
    "## SuperDocs docs review",
    "",
    status,
    "",
    `Files scanned: ${review.summary.filesScanned}`,
    `Docs reviewed: ${review.summary.docsReviewed}`,
    `Posted findings: ${review.summary.findingsPosted}`,
    `Suppressed low-priority findings: ${review.summary.findingsSuppressed}`,
    `Severity: ${severityCounts.blocker} blocker, ${severityCounts.warning} warning, ${severityCounts.suggestion} suggestion`,
    previewLine,
    "",
    "Commands:",
    "",
    "- `/superdocs review` - rerun the docs review",
    "- `/superdocs preview` - regenerate the export preview",
    "- `/superdocs apply <finding-id>` - apply one safe suggested fix",
    "",
    "This review is intentionally low-noise. Findings are capped so maintainers do not mute the app."
  ].join("\n");
}

export function formatReviewBody(review: StaticReviewResult): string {
  if (review.postedFindings.length === 0) {
    return "SuperDocs reviewed the documentation changes and found no static issues.";
  }

  return [
    `SuperDocs found ${review.postedFindings.length} high-signal documentation finding${review.postedFindings.length === 1 ? "" : "s"}.`,
    "Details are inline where GitHub line mapping is available."
  ].join("\n\n");
}

export function formatInlineFindingBody(finding: Finding): string {
  const lines = [
    `**${finding.title}**`,
    "",
    finding.explanation,
    "",
    `Finding ID: \`${finding.id}\``,
    `Severity: \`${finding.severity}\` · Confidence: \`${finding.confidence}\``
  ];

  if (finding.suggestedPatch) {
    lines.push("", "Suggested patch:", "", "```suggestion", finding.suggestedPatch, "```");
  }

  return lines.join("\n");
}

export function reviewEventFor(findings: Finding[]): "COMMENT" | "REQUEST_CHANGES" {
  return findings.some((finding) => finding.severity === "blocker")
    ? "REQUEST_CHANGES"
    : "COMMENT";
}

function countSeverities(findings: Finding[]) {
  return findings.reduce(
    (counts, finding) => {
      counts[finding.severity] += 1;
      return counts;
    },
    {
      blocker: 0,
      warning: 0,
      suggestion: 0
    }
  );
}

