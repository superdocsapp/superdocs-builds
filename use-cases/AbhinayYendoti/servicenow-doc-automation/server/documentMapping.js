/**
 * Canonical ChangeRequest -> the source document uploaded to SuperDocs.
 *
 * The mapping is deterministic and ServiceNow stays authoritative: values are
 * copied verbatim, never summarized or reworded locally. SuperDocs does the
 * writing; this module decides what it is allowed to see.
 */

import { createHash } from "node:crypto";

/** Fields a change must carry before it is worth sending anywhere. */
export const REQUIRED_FIELDS = [
  "short_description",
  "configuration_item",
  "work_notes",
  "resolution_code"
];

/**
 * Values SuperDocs must not alter. Checked per proposed change and again on the
 * finished document. Blocking fields are the ones the task requires verbatim;
 * advisory fields are ServiceNow-owned too, but a reviewer may accept a rewrite.
 */
export const PRESERVED_FIELDS = ["configuration_item", "work_notes"];
export const ADVISORY_FIELDS = ["number", "resolution_code", "status"];

/** Section labels a rewrite might restate a field under. */
const FIELD_LABELS = {
  configuration_item: ["Configuration Item"],
  work_notes: ["Work Notes"],
  number: ["Change ID", "Change Number"],
  resolution_code: ["Resolution", "Close Code"],
  status: ["Status", "State"]
};

const FIELD_TITLES = {
  configuration_item: "Configuration item",
  work_notes: "Work notes",
  number: "Change ID",
  resolution_code: "Resolution code",
  status: "Status"
};

export const FIELD_MAPPING = [
  { field: "number", section: "Change ID" },
  { field: "short_description", section: "Change Summary" },
  { field: "configuration_item", section: "Configuration Item" },
  { field: "work_notes", section: "Work Notes" },
  { field: "resolution_code", section: "Resolution" },
  { field: "status", section: "Status" },
  { field: "requester", section: "Requester" },
  { field: "assignment_group", section: "Assignment Group" },
  { field: "risk", section: "Risk" },
  { field: "planned_start", section: "Planned Start" },
  { field: "planned_end", section: "Planned End" }
];

export function validateChange(change) {
  const missingFields = REQUIRED_FIELDS.filter((field) => {
    const value = change?.[field];
    return typeof value !== "string" || value.trim().length === 0;
  });

  return { ok: missingFields.length === 0, missingFields };
}

export function mapChangeToSections(change) {
  return FIELD_MAPPING.filter(({ field }) => Boolean(change[field])).map(({ field, section }) => ({
    title: section,
    content: String(change[field]),
    sourceField: field
  }));
}

export function createFilename(change) {
  const id = change.number || "servicenow-change";
  return `${id.toLowerCase()}-production-change-record.docx`;
}

export function sourceFilename(change) {
  const id = change.number || "servicenow-change";
  return `${id.toLowerCase()}-source.md`;
}

/** The markdown actually uploaded to SuperDocs. */
export function renderSourceDocument(change) {
  const sections = mapChangeToSections(change)
    .map((section) => `## ${section.title}\n\n${section.content}`)
    .join("\n\n");

  return `# Production Change Record\n\n${sections}\n`;
}

/**
 * The edit instruction sent to SuperDocs. It names the values that must survive
 * verbatim, so the verification step below is checking a stated contract rather
 * than hoping.
 */
export function buildEditInstruction(change) {
  return [
    "Turn this ServiceNow change record into a production change record for an audit reader.",
    "Make targeted edits to the existing sections rather than rewriting the whole document,",
    "and keep every existing section and heading in place. Add a short Executive Summary at",
    "the top and a Risk and Rollback section at the end, drawn only from facts already in",
    "the document.",
    "",
    "Do not alter, paraphrase, reformat or abbreviate these values — they must appear character for character:",
    `- Configuration Item: ${change.configuration_item}`,
    `- Work Notes: ${change.work_notes}`,
    "",
    "Do not invent dates, owners, ticket numbers or outcomes that are not already present."
  ].join("\n");
}

/**
 * Post-edit gate: confirm the values ServiceNow owns came back untouched.
 * Runs against the HTML SuperDocs returned, before approval is offered.
 */
export function verifyPreservedValues(change, documentHtml) {
  const text = htmlToText(documentHtml ?? "");

  const checks = PRESERVED_FIELDS.map((field) => {
    const expected = String(change[field] ?? "");
    return {
      field,
      label: field === "configuration_item" ? "Configuration item preserved" : "Work notes preserved",
      expected,
      found: expected.length > 0 && normalize(text).includes(normalize(expected))
    };
  });

  return { ok: checks.every((check) => check.found), checks };
}

/**
 * Per-change gate. SuperDocs proposes chunk-level changes and asks for a
 * decision on each, so each one is checked on its own before a reviewer sees it.
 *
 * Two things count as tampering with a ServiceNow-owned value:
 *   1. the change drops a value that was in the chunk it replaces, and
 *   2. the change restates a field under its label with different text.
 *
 * The second rule is what catches a rewritten summary block that invents its own
 * spelling of a configuration item.
 */
export function verifyProposedChange(change, proposed) {
  const before = htmlToText(proposed?.old_html ?? "");
  const after = htmlToText(proposed?.new_html ?? "");
  const findings = [];

  for (const field of [...PRESERVED_FIELDS, ...ADVISORY_FIELDS]) {
    const expected = String(change[field] ?? "").trim();
    if (!expected) continue;

    const blocking = PRESERVED_FIELDS.includes(field);
    const title = FIELD_TITLES[field] ?? field;

    if (contains(before, expected) && !contains(after, expected)) {
      findings.push({
        field,
        blocking,
        reason: `${title} was changed. ServiceNow value: "${truncate(expected)}".`
      });
      continue;
    }

    const restated = restatedValue(after, FIELD_LABELS[field] ?? []);
    if (restated !== null && !contains(restated, expected)) {
      findings.push({
        field,
        blocking,
        reason: `${title} is restated with different text. ${describeDivergence(expected, restated)}`
      });
      continue;
    }

    // Only the verbatim fields earn this warning. An advisory field being
    // discussed in prose — "resolution was reached without customer impact" —
    // is ordinary writing, not drift.
    if (blocking && paraphrasesValue(after, expected, FIELD_LABELS[field] ?? [])) {
      findings.push({
        field,
        blocking: false,
        reason: `New text discusses the ${title.toLowerCase()} without quoting the ServiceNow value "${truncate(
          expected
        )}".`
      });
    }
  }

  const blocked = findings.some((finding) => finding.blocking);

  return {
    verdict: blocked ? "blocked" : findings.length ? "advisory" : "safe",
    recommendation: blocked ? "reject" : "approve",
    findings
  };
}

/**
 * If `text` labels a field, return what it says the value is, so the label's
 * value can be compared against ServiceNow. Returns null when the field is not
 * mentioned at all — silence is not a violation.
 *
 * The label has to read as a label: followed by a separator, or ending its own
 * line or table cell. Without that, prose like "Status was preserved by draining
 * traffic" reads as a restatement of the Status field and every rewrite trips.
 */
function restatedValue(text, labels) {
  for (const label of labels) {
    const match = new RegExp(`${escapeRegExp(label)}[ \\t]*(?:[:\\-–|]|\\n)[ \\t]*([\\s\\S]{0,200})`, "iu").exec(
      text
    );

    // A label with nothing after it is a heading, not a claim about the value.
    // Reading that as a restatement rates a proposed "<h2>Work Notes</h2>" as
    // blocked, which the server then refuses to approve — a chunk the reviewer
    // can only ever reject. Deletion is still caught: if the value was in the
    // chunk being replaced, the removal rule above has already fired.
    if (match) return match[1].trim() || null;
  }

  return null;
}

/**
 * Prose long enough to be making a claim, rather than a bare heading. A created
 * chunk containing only "<h2>Work Notes</h2>" mentions the field but asserts
 * nothing about it, and flagging that would be noise.
 */
const MIN_PROSE_LENGTH = 80;

/**
 * Newly written prose that talks about a protected value without quoting it.
 *
 * The first two rules only catch a value being removed from a chunk, or being
 * restated under its own label. Neither fires on *added* text, and against the
 * live API that is exactly where the drift showed up: asked for an Executive
 * Summary, the model wrote "the configuration item identified as the production
 * API gateway" instead of `PROD-API-GATEWAY-01`.
 *
 * The canonical section still carries the verbatim value, so the document as a
 * whole survives the final gate — this is advisory, not blocking. But a
 * reviewer should be told the summary paraphrases a value ServiceNow owns
 * rather than quoting it.
 */
function paraphrasesValue(after, expected, labels) {
  if (after.length < MIN_PROSE_LENGTH) return false;
  if (contains(after, expected)) return false;

  return labels.some((label) => new RegExp(escapeRegExp(label), "iu").test(after));
}

/**
 * Two long strings truncated to the same length look identical even when they
 * differ later on, which makes for a useless finding. Quote both sides from
 * where they actually diverge.
 */
function describeDivergence(expected, actual) {
  const left = normalize(expected);
  const right = normalize(actual);

  let index = 0;
  while (index < left.length && index < right.length && left[index] === right[index]) index += 1;

  // Back up to a word boundary so neither side is quoted mid-word.
  const boundary = left.lastIndexOf(" ", index);
  if (boundary > 0) index = boundary + 1;

  if (index < 24) {
    return `ServiceNow has "${truncate(left, 70)}"; the change has "${truncate(right, 70)}".`;
  }

  const from = left.lastIndexOf(" ", Math.max(0, index - 14)) + 1;
  return `They match up to "...${left.slice(from, index).trim()}", then ServiceNow has "${truncate(
    left.slice(index),
    50
  )}" and the change has "${truncate(right.slice(index), 50)}".`;
}

function contains(haystack, needle) {
  return normalize(haystack).includes(normalize(needle));
}

function truncate(value, limit = 60) {
  const collapsed = normalize(value);
  return collapsed.length > limit ? `${collapsed.slice(0, limit)}…` : collapsed;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

/**
 * A stable fingerprint of the finished document.
 *
 * Recorded in the audit trail and written back to ServiceNow, so the exported
 * file can later be tied to the record it was approved against. Whitespace is
 * normalized first: a reflowed paragraph is the same document.
 */
export function documentChecksum(html) {
  return createHash("sha256").update(normalize(htmlToText(html ?? ""))).digest("hex").slice(0, 16);
}

/**
 * The work note written back to ServiceNow after export.
 *
 * ServiceNow stays the system of record, so the loop closes there: the change
 * gets a journal entry naming the document, the session that produced it, the
 * checksum, and who signed it off.
 */
export function buildWriteBackNote({ change, filename, checksum, sessionId, approvedAt, reviewer }) {
  return [
    "Production change record generated and exported.",
    `Document: ${filename}`,
    `Checksum (sha256/16): ${checksum}`,
    `SuperDocs session: ${sessionId}`,
    `Approved: ${approvedAt} by ${reviewer ?? "change reviewer"}`,
    `Verified verbatim: ${PRESERVED_FIELDS.map((field) => FIELD_TITLES[field] ?? field).join(", ")}`,
    `Source record: ${change.number}`
  ].join("\n");
}

export function htmlToText(html) {
  return html
    .replace(/<(script|style)[\s\S]*?<\/\1>/giu, " ")
    .replace(/<br\s*\/?>/giu, "\n")
    .replace(/<\/(p|div|h[1-6]|li|tr|td|th)>/giu, "\n")
    .replace(/<[^>]+>/gu, " ")
    .replace(/&nbsp;/gu, " ")
    .replace(/&amp;/gu, "&")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&#39;/gu, "'");
}

/** Whitespace-insensitive comparison: rewrapping a paragraph is not a value change. */
function normalize(value) {
  return value.replace(/\s+/gu, " ").trim();
}
