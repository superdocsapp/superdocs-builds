import type { Proposal } from "./domain";

type AuditAuthority = { title: string; citation: string };
type AuditRow = { amount: string; source_row_id: string };

const escapeHtml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character]!,
  );

const headingOnly = /^\s*<h([1-6])(?:\s[^>]*)?>[\s\S]*?<\/h\1>\s*$/i;

/** Removes headings with no rendered content before the next heading. */
export function removeOrphanHeadings(html: string) {
  let result = html;
  const consecutiveHeading =
    /<h([1-6])([^>]*)>([\s\S]*?)<\/h\1>\s*(?=<h[1-6](?:\s|>))/gi;
  while (consecutiveHeading.test(result))
    result = result.replace(consecutiveHeading, "");
  return result;
}

export function renderReviewedExports(input: {
  draftHtml: string;
  proposals: Proposal[];
  authorities: AuditAuthority[];
  rows: AuditRow[];
  rejectedAuthorityTitle: string;
}) {
  const approvedFragments = input.proposals
    .filter((proposal) => proposal.decision === "APPROVED")
    .map((proposal) => proposal.after)
    .filter((fragment) => !headingOnly.test(fragment));
  const reviewedBase = removeOrphanHeadings(
    input.draftHtml.replace(
      "<h2>Conclusion</h2>",
      `${approvedFragments.join("\n")}<h2>Conclusion</h2>`,
    ),
  );
  const auditSections = `<h2>Authorities table</h2>${input.authorities.map((item) => `<p>${escapeHtml(item.title)} | ${escapeHtml(item.citation)} | VERIFIED</p>`).join("")}<h2>Numeric traceability register</h2>${input.rows.map((row) => `<p>INR ${escapeHtml(row.amount)} | ${escapeHtml(row.source_row_id)} | VERIFIED</p>`).join("")}<h2>Unsupported-authority warnings</h2><p>${escapeHtml(input.rejectedAuthorityTitle)} rejected.</p><h2>Reviewer decision log</h2><p>${input.proposals.map((item) => `${escapeHtml(item.id)}: ${item.decision}`).join(" | ")}</p>`;
  return {
    reviewedBase,
    client: reviewedBase,
    file: `${reviewedBase}${auditSections}`,
  };
}
