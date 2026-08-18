/**
 * Explicit managed-fact occurrence model.
 *
 * PolicySet renders every managed document itself, so it already knows the
 * shapes a managed return window takes in a document's natural legal prose
 * (PolicySet templates no longer emit a machine-style summary fact line — see
 * PROGRESS.md). This module locates those occurrences in authoritative
 * SuperDocs HTML by chunk, so a proposal batch can be checked for
 * completeness before approval. It is intentionally limited to
 * `returns.windowDays`.
 */
import type { PolicyDocumentType } from "./types";
import { htmlToPolicyText } from "./validator";

export type ManagedOccurrenceKind = "policy_prose";

export type ManagedOccurrencePattern = {
  id: string;
  kind: ManagedOccurrenceKind;
  label: string;
  build: (value: number) => RegExp;
};

/** Every managed shape the return window takes in a PolicySet document. */
export const RETURN_WINDOW_OCCURRENCE_PATTERNS: readonly ManagedOccurrencePattern[] =
  [
    {
      id: "prose-delivery-window",
      kind: "policy_prose",
      label: `the body prose "within N days of delivery"`,
      build: (value) =>
        new RegExp(`within\\s+${value}\\s+days?\\s+of\\s+delivery`, "i"),
    },
    {
      id: "prose-window-crossref",
      kind: "policy_prose",
      label: `the body prose "N-day window"`,
      build: (value) => new RegExp(`\\b${value}[ -]day\\s+window\\b`, "i"),
    },
  ];

/**
 * The occurrence kinds each affected document must contain. If a document does
 * not yield all of them, PolicySet's model no longer matches the document and
 * the gate fails closed instead of approving a partial batch.
 */
export const RETURN_WINDOW_COVERAGE_MODEL = {
  terms: ["policy_prose"],
  returns: ["policy_prose"],
} as const satisfies Partial<
  Record<PolicyDocumentType, readonly ManagedOccurrenceKind[]>
>;

export type ManagedOccurrence = {
  documentType: PolicyDocumentType;
  chunkId: string;
  kind: ManagedOccurrenceKind;
  patternId: string;
  label: string;
  excerpt: string;
};

export type PolicyDocumentChunk = {
  chunkId: string;
  tagName: string;
  attributes: string;
  html: string;
  text: string;
};

const CHUNK_TAG_RE = /<([a-z][\w:-]*)(\s[^>]*data-chunk-id="([^"]*)"[^>]*)>/gi;

/**
 * Splits authoritative SuperDocs HTML into its top-level `data-chunk-id`
 * blocks. Chunk-carrying elements are siblings, so each chunk runs until the
 * next chunk opening tag.
 */
export function splitPolicyDocumentChunks(
  html: string,
): PolicyDocumentChunk[] {
  const matches = [...html.matchAll(CHUNK_TAG_RE)];
  return matches
    .map((match, index) => {
      const start = match.index ?? 0;
      const end =
        index + 1 < matches.length
          ? (matches[index + 1].index ?? html.length)
          : html.length;
      const chunkHtml = html.slice(start, end);
      return {
        chunkId: match[3] ?? "",
        tagName: match[1].toLowerCase(),
        attributes: match[2] ?? "",
        html: chunkHtml,
        text: htmlToPolicyText(chunkHtml),
      };
    })
    .filter((chunk) => chunk.chunkId.trim() !== "");
}

export function isStructuralPartChunk(chunk: PolicyDocumentChunk): boolean {
  return (
    chunk.tagName === "header" ||
    chunk.tagName === "footer" ||
    /data-part-type="\s*(header|footer)\s*"/i.test(chunk.attributes)
  );
}

/**
 * Every body occurrence of the managed return window `value` in one document,
 * keyed by the chunk a SuperDocs proposal would have to target. Headers and
 * footers are excluded: PolicySet never asks SuperDocs to edit them.
 */
export function findReturnWindowOccurrences(
  documentType: PolicyDocumentType,
  html: string,
  value: number,
): ManagedOccurrence[] {
  const occurrences: ManagedOccurrence[] = [];
  for (const chunk of splitPolicyDocumentChunks(html)) {
    if (isStructuralPartChunk(chunk)) {
      continue;
    }
    for (const pattern of RETURN_WINDOW_OCCURRENCE_PATTERNS) {
      const match = pattern.build(value).exec(chunk.text);
      if (!match) {
        continue;
      }
      occurrences.push({
        documentType,
        chunkId: chunk.chunkId,
        kind: pattern.kind,
        patternId: pattern.id,
        label: pattern.label,
        excerpt: match[0].trim(),
      });
    }
  }
  return occurrences;
}

export function returnWindowCoverageModelFor(
  documentType: PolicyDocumentType,
): readonly ManagedOccurrenceKind[] | null {
  const model = RETURN_WINDOW_COVERAGE_MODEL as Partial<
    Record<PolicyDocumentType, readonly ManagedOccurrenceKind[]>
  >;
  return model[documentType] ?? null;
}

/**
 * True when `text` shows this exact occurrence moved from the previous managed
 * value to the next one, with no stale previous value left behind.
 */
export function isReturnWindowOccurrenceUpdated(
  patternId: string,
  text: string,
  previousValue: number,
  nextValue: number,
): boolean {
  const pattern = RETURN_WINDOW_OCCURRENCE_PATTERNS.find(
    (candidate) => candidate.id === patternId,
  );
  if (!pattern) {
    return false;
  }
  return (
    pattern.build(nextValue).test(text) &&
    !pattern.build(previousValue).test(text)
  );
}

export function describeManagedOccurrence(
  occurrence: ManagedOccurrence,
): string {
  return `${occurrence.documentType}: ${occurrence.label} ("${occurrence.excerpt}", chunk ${occurrence.chunkId})`;
}
