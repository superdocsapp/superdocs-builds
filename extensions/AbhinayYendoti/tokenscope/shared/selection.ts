import type { DocumentSnapshot, Paragraph, ProposedChange, Selection } from "./types.js";

/**
 * Resolving a host selection onto the document, and checking afterwards that the
 * model stayed inside it.
 *
 * The host (Word, or the demo surface) hands us raw selected text. Turning that
 * into "which paragraphs did the user mean" is done here rather than in either
 * host, so both hosts behave identically and the rule is testable without a
 * document editor in the loop.
 */

export class InvalidSelectionError extends Error {
  override readonly name = "InvalidSelectionError";
}

/** Collapse whitespace so a selection that spans a line break still matches. */
export function normalize(text: string): string {
  return text.replace(/\s+/gu, " ").trim();
}

/**
 * Which paragraphs does this selected text cover?
 *
 * A selection counts as covering a paragraph when the paragraph contains the
 * selection, or the selection contains the paragraph. That handles both "the
 * user dragged across half a sentence" and "the user selected four paragraphs".
 */
export function resolveSelection(document: DocumentSnapshot, selectedText: string): Selection {
  const text = normalize(selectedText);

  if (text.length === 0) {
    throw new InvalidSelectionError("Nothing is selected. Select the text you want rewritten.");
  }

  const covered = document.paragraphs.filter((p) => {
    const paragraph = normalize(p.text);
    if (paragraph.length === 0) return false;
    return paragraph.includes(text) || text.includes(paragraph);
  });

  if (covered.length === 0) {
    throw new InvalidSelectionError(
      "The selected text was not found in the document TokenScope is holding. " +
        "Reload the document and select again."
    );
  }

  return { paragraphIds: covered.map((p) => p.id), text: selectedText.trim() };
}

export function assertInstruction(instruction: string): string {
  const trimmed = instruction.trim();

  if (trimmed.length === 0) {
    throw new InvalidSelectionError(
      "Enter a rewrite instruction, for example “Make this more concise”."
    );
  }

  return trimmed;
}

function escapeHtml(text: string): string {
  return text.replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;");
}

/** The document as SuperDocs receives it. One paragraph in, one chunk out. */
export function toDocumentHtml(document: DocumentSnapshot): string {
  return document.paragraphs.map((p) => `<p>${escapeHtml(p.text)}</p>`).join("");
}

/**
 * The surgical instruction.
 *
 * The selection is delimited rather than described, so the model is matching an
 * exact string instead of interpreting a reference to "the second paragraph".
 * Everything else in the document is explicitly fenced off.
 */
export function buildSurgicalMessage(selection: Selection, instruction: string): string {
  return [
    "Rewrite ONLY the text delimited by the SELECTION markers below.",
    "Leave every other part of the document exactly as it is: do not re-word,",
    "re-order, re-format or re-flow anything outside the markers.",
    "",
    `Instruction: ${instruction}`,
    "",
    "<<<SELECTION",
    selection.text,
    "SELECTION>>>"
  ].join("\n");
}

/**
 * The whole-document counterfactual instruction.
 *
 * This is the thing TokenScope exists to argue against, so it has to be a fair
 * fight: the same edit, expressed the way you would have to express it if you
 * had no way to target a range.
 */
export function buildWholeDocumentMessage(instruction: string): string {
  return [
    "Regenerate this document in full. Reproduce every section from top to bottom",
    "in the output, applying the following change where it is relevant and leaving",
    "the meaning of everything else intact.",
    "",
    `Instruction: ${instruction}`
  ].join("\n");
}

/** Strip tags so a returned chunk can be compared with the plain text we sent. */
export function htmlToText(html: string): string {
  return normalize(
    html
      .replace(/<[^>]*>/gu, " ")
      .replace(/&nbsp;/gu, " ")
      .replace(/&lt;/gu, "<")
      .replace(/&gt;/gu, ">")
      .replace(/&amp;/gu, "&")
  );
}

export interface ScopeReport {
  /** Changes whose original text is one of the selected paragraphs. */
  inScope: ProposedChange[];
  /** Changes that landed somewhere else. Never offered for apply. */
  outOfScope: ProposedChange[];
}

/**
 * Did the model stay inside the selection?
 *
 * SuperDocs mints its own chunk ids, so the changes come back keyed to ids we
 * never sent. The mapping back to our paragraphs is done on the original text,
 * which is the one thing both sides agree on. A change we cannot map is treated
 * as out of scope: unproven is not the same as safe.
 */
export function checkScope(
  changes: ProposedChange[],
  document: DocumentSnapshot,
  selection: Selection
): ScopeReport {
  const byId = new Map<string, Paragraph>(document.paragraphs.map((p) => [p.id, p]));
  const selected = selection.paragraphIds
    .map((id) => byId.get(id))
    .filter((p): p is Paragraph => p !== undefined)
    .map((p) => normalize(p.text));

  const inScope: ProposedChange[] = [];
  const outOfScope: ProposedChange[] = [];

  for (const change of changes) {
    const original = normalize(change.oldText);
    // An empty original is inside every string. It proves nothing, so it maps to
    // nothing: a change with no original text is a change we cannot place.
    const matches =
      original.length > 0 &&
      selected.some((paragraph) => paragraph === original || paragraph.includes(original));

    (matches ? inScope : outOfScope).push(change);
  }

  return { inScope, outOfScope };
}
