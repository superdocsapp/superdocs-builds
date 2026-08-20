import type { Finding } from "../review/findings.js";

export const appliedMarkerPrefix = "<!-- superdocs-applied";
export const refusedMarkerPrefix = "<!-- superdocs-apply-refused";

export type AppliedCommit = {
  path: string;
  commitSha: string;
  commitUrl?: string;
  findingIds: string[];
  changedLines: number[];
};

/**
 * Identifies one successful apply against one commit. Re-running the same command
 * on the same head SHA finds this marker and reports the original result instead
 * of committing twice.
 */
export function appliedMarker(key: string, headSha: string): string {
  return `${appliedMarkerPrefix}:${key}:${headSha} -->`;
}

/**
 * Identifies one refusal, kept distinct from the applied marker so that a retry
 * after a refusal is never mistaken for work already done. The reason is part of
 * the key so a different refusal still gets its own explanation.
 */
export function refusedMarker(
  key: string,
  headSha: string,
  reason: string
): string {
  return `${refusedMarkerPrefix}:${key}:${headSha}:${reason} -->`;
}

export function formatCommitMessage({
  findings,
  requestedBy,
  path
}: {
  findings: Finding[];
  requestedBy: string;
  path: string;
}): string {
  const subject =
    findings.length === 1
      ? `docs: apply SuperDocs fix for ${findings[0].id}`
      : `docs: apply ${findings.length} SuperDocs fixes in ${path}`;

  const details = findings.map(
    (finding) => `- ${finding.title} (${finding.path}:${finding.startLine}) [${finding.id}]`
  );

  return [
    subject,
    "",
    ...details,
    "",
    `Requested by @${requestedBy} via a /superdocs apply comment.`,
    "Applied by the SuperDocs docs PR reviewer app."
  ].join("\n");
}

export function formatAppliedReply({
  key,
  headSha,
  commits
}: {
  key: string;
  headSha: string;
  commits: AppliedCommit[];
}): string {
  const lines = [
    appliedMarker(key, headSha),
    `**Applied.** ${describeFixCount(commits)} committed to this pull request.`,
    ""
  ];

  for (const commit of commits) {
    const sha = commit.commitUrl
      ? `[\`${shortSha(commit.commitSha)}\`](${commit.commitUrl})`
      : `\`${shortSha(commit.commitSha)}\``;

    lines.push(
      `- \`${commit.path}\` — ${sha}, line${commit.changedLines.length === 1 ? "" : "s"} ${commit.changedLines.join(", ")} changed`
    );
  }

  lines.push(
    "",
    "Only the lines listed above were rewritten; every other line in those files is byte-for-byte unchanged.",
    "Re-run `/superdocs review` to review the updated commit."
  );

  return lines.join("\n");
}

export function formatRefusalReply({
  key,
  headSha,
  reason,
  detail,
  nextStep
}: {
  key: string;
  headSha: string;
  reason: string;
  detail: string;
  nextStep?: string;
}): string {
  const lines = [
    refusedMarker(key, headSha, reason),
    `**Not applied.** ${detail}`
  ];

  if (nextStep) {
    lines.push("", nextStep);
  }

  return lines.join("\n");
}

function describeFixCount(commits: AppliedCommit[]): string {
  const findings = commits.reduce(
    (total, commit) => total + commit.findingIds.length,
    0
  );

  return findings === 1 ? "1 suggested fix" : `${findings} suggested fixes`;
}

function shortSha(sha: string): string {
  return sha.slice(0, 7);
}
