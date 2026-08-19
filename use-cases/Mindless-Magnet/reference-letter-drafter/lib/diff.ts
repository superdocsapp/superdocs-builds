/**
 * Word-level diff for the review cards.
 *
 * Note what this replaces. The first version of this app rendered the before
 * and after HTML with `dangerouslySetInnerHTML` behind a sanitizer. That HTML
 * originates from a model that has just read attacker-influenced intake text,
 * so a sanitizer there is a mitigation for an XSS class we do not have to be in
 * at all. Reference letters are prose; the reviewer needs to see which words
 * changed, not which tags did.
 *
 * So the diff runs on extracted text and renders as React text nodes. There is
 * no `dangerouslySetInnerHTML` anywhere in this repository. That closes the
 * class rather than filtering the instance, and it makes the review card more
 * readable at the same time.
 *
 * The algorithm is a standard LCS over word tokens. Letters are hundreds of
 * words, so the O(n*m) table is a few hundred kilobytes at worst and runs in
 * single-digit milliseconds. A diff library would be a dependency for a
 * forty-line function.
 */

export type DiffOp = "same" | "added" | "removed";

export interface DiffSegment {
  op: DiffOp;
  text: string;
}

/** Split into words while keeping whitespace attached, so joins round-trip. */
function tokenize(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

const MAX_TOKENS = 4000;

export function wordDiff(before: string, after: string): DiffSegment[] {
  const a = tokenize(before);
  const b = tokenize(after);

  if (a.length === 0 && b.length === 0) return [];
  if (a.length === 0) return [{ op: "added", text: b.join("") }];
  if (b.length === 0) return [{ op: "removed", text: a.join("") }];

  // Degrade rather than freeze the browser on a pathological input.
  if (a.length > MAX_TOKENS || b.length > MAX_TOKENS) {
    return [
      { op: "removed", text: a.join("") },
      { op: "added", text: b.join("") },
    ];
  }

  // LCS length table.
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );

  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] =
        a[i].trim() === b[j].trim()
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const raw: DiffSegment[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i].trim() === b[j].trim()) {
      raw.push({ op: "same", text: a[i] });
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      raw.push({ op: "removed", text: a[i] });
      i++;
    } else {
      raw.push({ op: "added", text: b[j] });
      j++;
    }
  }
  while (i < a.length) raw.push({ op: "removed", text: a[i++] });
  while (j < b.length) raw.push({ op: "added", text: b[j++] });

  // Coalesce runs so the UI renders a handful of spans, not one per word.
  const merged: DiffSegment[] = [];
  for (const segment of raw) {
    const last = merged[merged.length - 1];
    if (last && last.op === segment.op) last.text += segment.text;
    else merged.push({ ...segment });
  }
  return merged;
}

/** True when the two sides are identical once whitespace is normalised. */
export function isNoOpChange(before: string, after: string): boolean {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  return norm(before) === norm(after);
}
