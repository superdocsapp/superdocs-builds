import { z } from "zod";

export const moneyRowSchema = z.object({
  source_row_id: z.string().min(1),
  label: z.string().min(1),
  amount: z.string().regex(/^\d+(\.\d{1,2})?$/),
});
export const authoritySchema = z.object({
  authority_id: z.string(),
  title: z.string().min(1),
  authority_type: z.string(),
  citation: z.string(),
  source_document_id: z.string(),
  exact_quote: z.string().min(1),
  source_locator: z.string(),
  verification_status: z
    .enum(["VERIFIED", "UNVERIFIED", "MISSING"])
    .default("UNVERIFIED"),
  proposition: z.string(),
  attachment_text: z.string(),
});
export const caseSchema = z.object({
  facts: z.array(z.string().min(1)).min(1),
  question: z.string().min(10),
  currency: z.string().min(1),
  rows: z.array(moneyRowSchema).min(1),
  authorities: z.array(authoritySchema).min(1),
});
export type TaxCase = z.infer<typeof caseSchema>;
export type Authority = z.infer<typeof authoritySchema>;
export type Proposal = {
  /** Canonical identity: upstream id/change_id, or a deterministic local fingerprint. */
  id: string;
  section: string;
  before: string;
  after: string;
  decision: "PENDING" | "APPROVED" | "REJECTED";
  mandatory?: boolean;
  reviewerNote?: string;
};
export type NumericEntry = {
  narrative_figure: string;
  memo_section: string;
  source_row_id: string | null;
  source_value: string | null;
  comparison_method: string;
  verified: boolean;
  warning: string | null;
};

const norm = (s: string) =>
  s.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase();
export function verifyAuthorities(items: Authority[]): Authority[] {
  return items.map((a) => ({
    ...a,
    verification_status: norm(a.attachment_text).includes(norm(a.exact_quote))
      ? "VERIFIED"
      : "UNVERIFIED",
  }));
}
export function authoritiesTable(items: Authority[]) {
  return items.map(
    ({
      title,
      citation,
      proposition,
      exact_quote,
      source_locator,
      verification_status,
    }) => ({
      authority: title,
      citation,
      proposition_supported: proposition,
      exact_quote,
      location: source_locator,
      verification_status,
    }),
  );
}
export function deterministicTotal(
  rows: TaxCase["rows"],
  ids: string[],
  id: string,
  label: string,
) {
  let cents = 0n;
  for (const key of ids) {
    const row = rows.find((r) => r.source_row_id === key);
    if (!row) throw new Error(`Missing calculation input: ${key}`);
    const [w, f = ""] = row.amount.split(".");
    cents += BigInt(w) * 100n + BigInt((f + "00").slice(0, 2));
  }
  return {
    source_row_id: id,
    label,
    amount: `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`,
    input_row_ids: ids,
  };
}
const numeric = /\b(?:INR|₹)?\s*\d[\d,]*(?:\.\d{1,2})?\b/g;
const canonical = (x: string) =>
  x.replace(/INR|₹|\s|,/g, "").replace(/\.00$/, "");
export function traceNarrative(
  sections: Record<string, string>,
  rows: TaxCase["rows"],
): NumericEntry[] {
  return Object.entries(sections).flatMap(([section, text]) =>
    (text.match(numeric) || []).map((value) => {
      const row = rows.find((r) => canonical(r.amount) === canonical(value));
      return {
        narrative_figure: value,
        memo_section: section,
        source_row_id: row?.source_row_id ?? null,
        source_value: row?.amount ?? null,
        comparison_method: row
          ? "normalized exact decimal match"
          : "no source/calculation match",
        verified: !!row,
        warning: row ? null : "Unmatched narrative figure",
      };
    }),
  );
}
const stableFingerprint = (value: string) => {
  let hash = 0xcbf29ce484222325n;
  for (const byte of new TextEncoder().encode(value)) {
    hash ^= BigInt(byte);
    hash = BigInt.asUintN(64, hash * 0x100000001b3n);
  }
  return hash.toString(16).padStart(16, "0");
};
const normalizedIdentityContent = (value: unknown) =>
  String(value ?? "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();

export function parseProposedChanges(
  value: unknown,
  context: { sessionId?: string } = {},
): Proposal[] {
  let parsed = value;
  if (typeof parsed === "string") {
    try {
      parsed = JSON.parse(parsed);
    } catch {
      throw new Error("SuperDocs proposed changes were not valid JSON");
    }
  }
  const source = Array.isArray(parsed)
    ? parsed
    : (parsed as { proposed_changes?: unknown })?.proposed_changes;
  if (!Array.isArray(source))
    throw new Error("SuperDocs response did not contain proposed_changes");
  const proposals: Proposal[] = source.map((x, i) => {
    const v = x as Record<string, unknown>;
    const after = v.after ?? v.new_html;
    if (typeof after !== "string")
      throw new Error(`Proposed change ${i + 1} has invalid content`);
    const upstreamId = v.id ?? v.change_id;
    const localIdentity = [
      context.sessionId ?? "unknown-session",
      i,
      v.operation_type ?? v.operation ?? v.type ?? "replace",
      v.source_range_id ?? v.range_id ?? v.target ?? v.chunk_id ?? v.before,
      normalizedIdentityContent(after),
    ].join("\u001f");
    return {
      id:
        upstreamId === undefined || String(upstreamId).trim() === ""
          ? `local-${stableFingerprint(localIdentity)}`
          : String(upstreamId),
      section: String(v.section ?? "Analysis"),
      before: String(v.before ?? v.old_html ?? ""),
      after,
      decision: "PENDING",
    };
  });
  if (
    new Set(proposals.map((proposal) => proposal.id)).size !== proposals.length
  )
    throw new Error(
      "SuperDocs proposed changes contained duplicate identities",
    );
  return proposals;
}
export function blockers(
  authorities: Authority[],
  register: NumericEntry[],
  proposals: Proposal[],
  missing: string[] = [],
) {
  return [
    ...register
      .filter((x) => !x.verified)
      .map((x) => `Unmatched figure: ${x.narrative_figure}`),
    ...authorities
      .filter((x) => x.verification_status !== "VERIFIED")
      .map((x) => `Unverified quotation: ${x.title}`),
    ...missing.map((x) => `Missing authority: ${x}`),
    ...(proposals.some((x) => (x.mandatory ?? true) && x.decision === "PENDING")
      ? ["Mandatory proposals remain undecided"]
      : []),
  ];
}
export function decideProposal(
  proposals: Proposal[],
  id: string,
  decision: Exclude<Proposal["decision"], "PENDING">,
  reviewerNote: string,
) {
  return proposals.map((proposal) =>
    proposal.id === id ? { ...proposal, decision, reviewerNote } : proposal,
  );
}
export function outputs(
  data: TaxCase,
  sections: Record<string, string>,
  authorities: Authority[],
  register: NumericEntry[],
  proposals: Proposal[],
) {
  const sourceState = JSON.stringify({
    data,
    sections,
    authorities,
    register,
    proposals,
  });
  const client = {
    facts: data.facts,
    question: data.question,
    authorities: authorities
      .filter((x) => x.verification_status === "VERIFIED")
      .map((x) => x.citation),
    analysis: [
      sections.Analysis,
      ...proposals
        .filter((x) => x.decision === "APPROVED" && x.section === "Analysis")
        .map((x) => x.after),
    ].join("\n"),
    conclusion: [
      sections.Conclusion,
      ...proposals
        .filter((x) => x.decision === "APPROVED" && x.section === "Conclusion")
        .map((x) => x.after),
    ].join("\n"),
    confidence_level: "Moderate",
    source_state: sourceState,
  };
  const internal = {
    ...client,
    authorities_table: authoritiesTable(authorities),
    numeric_register: register,
    unsupported_authority_warnings: authorities
      .filter((x) => x.verification_status !== "VERIFIED")
      .map((x) => x.title),
    review_log: proposals.map((x) => ({
      id: x.id,
      decision: x.decision,
      reviewer_note: x.reviewerNote ?? "",
    })),
    limitations: ["Synthetic demonstration; not tax advice."],
  };
  return { client, internal };
}
