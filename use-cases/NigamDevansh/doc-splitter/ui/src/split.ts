/** Turning a click in the preview into a cut the service can make.
 *
 * The API gives `data-chunk-id` per block and nothing else, so the preview
 * renders the real HTML at real paper size and numbers the lines itself. A cut
 * is `(chunk_id, offset)`, where `offset` counts text-node characters — what the
 * browser caret reports and what the Python side cuts at, so nothing is
 * translated between them.
 *
 * See use-cases/doc-splitter/README.md § "Marking where the parts begin".
 */

/** The outline: what orders the cuts. The document itself renders from its HTML,
 * so a per-block text preview would ship the contract twice. */
export interface Block {
  chunk_id: string;
  index: number;
}

export type Snap = "word" | "exact";

export interface Cut {
  chunk_id: string;
  offset: number;
  /** Display only — what the reviewer saw when placing it; our pagination is not
   * Word's. */
  page: number;
  line: number;
  quote: string;
}

export interface PartPreview {
  part: number;
  title: string;
  blocks: number;
  headings: number;
  characters: number;
}

/** Only what the verdict draws. `/split` returns the whole breakdown — it IS the
 * proof, and a machine caller wants it — but the UI renders just these three. */
export interface Coverage {
  complete: boolean;
  summary: string;
  repeated_furniture: number;
}

export interface PageSetup {
  width_in?: number;
  height_in?: number;
  margin_in?: { top?: number; right?: number; bottom?: number; left?: number };
}

/** CSS pixels per inch, fixed by the spec. Only `pageBox` needs it. */
const PPI = 96;

/** The printable box in pixels, from the `.docx` page setup. Falls back to US
 * Letter with one-inch margins, since a .md/.txt master has no page setup. */
export function pageBox(setup: PageSetup | null | undefined) {
  const width = setup?.width_in ?? 8.5;
  const height = setup?.height_in ?? 11;
  const margin = setup?.margin_in ?? {};
  return {
    width: (width - (margin.left ?? 1) - (margin.right ?? 1)) * PPI,
    height: (height - (margin.top ?? 1) - (margin.bottom ?? 1)) * PPI,
  };
}

/** Which page a line at `top` pixels falls on. 1-based, like a printed page. */
export function pageOf(top: number, pageHeight: number): number {
  return Math.floor(top / Math.max(1, pageHeight)) + 1;
}

/** How many markers `parts` needs: **n − 1**. Three parts need two cuts — the
 * document already has a start and an end. */
export function markersNeeded(parts: number): number {
  return Math.max(0, parts - 1);
}

/** Cuts in document order, exact repeats dropped. Ordered by position, not by
 * when placed, so markers dropped back-to-front still produce parts in order. */
export function ordered(cuts: Cut[], order: Map<string, number>): Cut[] {
  const seen = new Map<string, Cut>();
  for (const cut of cuts) seen.set(`${cut.chunk_id}:${cut.offset}`, cut);
  return [...seen.values()].sort(
    (left, right) =>
      (order.get(left.chunk_id) ?? 0) - (order.get(right.chunk_id) ?? 0) ||
      left.offset - right.offset,
  );
}

/** Which part a cut opens: cut 0 opens part 2, and so on. */
export function partAfter(index: number): number {
  return index + 2;
}

/** What the reviewer is told before they spend anything. */
export function exportWarning(parts: number, maxParts: number): string | null {
  if (parts > maxParts) {
    return `${parts} parts exceeds the limit of ${maxParts}. Raise MAX_PARTS deliberately.`;
  }
  if (parts > 6) return `${parts} parts means ${parts} export operations.`;
  return null;
}

/** Whitespace, for "is there a word here". Includes the non-breaking space:
 * SuperDocs emits `&nbsp;`, which `\s` does not match. */
const SPACE = /[\s\u00a0]/;

/** Is there any word at this position? A click in the gap between paragraphs
 * resolves to some text node but is not a split point. */
export function hasWordAt(text: string, offset: number): boolean {
  const before = text.slice(0, offset);
  const after = text.slice(offset);
  return /\S/.test(before.slice(-1)) || /\S/.test(after.slice(0, 1));
}

/** Move a cut to the nearest word boundary: back to the word's start when
 * mid-word, forward to the next word when in whitespace — never into the run of
 * spaces, which would start a part with a blank. */
export function snapToWord(text: string, offset: number): number {
  const at = Math.max(0, Math.min(offset, text.length));
  if (at > 0 && SPACE.test(text[at - 1] ?? "")) {
    // Sitting after whitespace: already at a word start, or in a run of it.
    let forward = at;
    while (forward < text.length && SPACE.test(text[forward] ?? "")) forward += 1;
    return forward;
  }
  let back = at;
  while (back > 0 && !SPACE.test(text[back - 1] ?? "")) back -= 1;
  return back;
}

/** Apply the granularity. `exact` is character-precise, mid-word and all. */
export function applySnap(text: string, offset: number, snap: Snap): number {
  return snap === "word" ? snapToWord(text, offset) : offset;
}

/** A few words either side of the cut, so a marker is recognisable in the list.
 * `|` marks where the cut lands, including mid-word. */
export function quoteAround(text: string, offset: number, span = 26): string {
  const before = text.slice(Math.max(0, offset - span), offset);
  const after = text.slice(offset, offset + span);
  return `${offset > span ? "…" : ""}${before}|${after}${offset + span < text.length ? "…" : ""}`;
}
