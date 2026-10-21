/**
 * The word-level diff shown on each review card.
 *
 * It lives in core rather than in the modal because the review gate is the most
 * important thing in this plugin to get right, and logic that can only be tested
 * by opening Obsidian is logic that does not get tested.
 */

export type DiffPart = { kind: "same" | "add" | "del"; text: string };

/** Strip markup for display. The diff is about prose, not tags. */
export function toText(html: string): string {
  return html
    .replace(/<\/(p|div|li|h[1-6]|tr|figcaption|blockquote)>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Word-level LCS diff.
 *
 * Small on purpose: a proposed change is a paragraph or two, not a file, so an
 * O(n·m) table over a couple of hundred tokens costs nothing, and pulling in a
 * diff library for this would be a dependency per kilobyte of value.
 */
export function wordDiff(before: string, after: string): DiffPart[] {
  const A = before.split(/(\s+)/).filter((s) => s !== "");
  const B = after.split(/(\s+)/).filter((s) => s !== "");
  const n = A.length;
  const m = B.length;

  // Guard against a pathological pair; fall back to a whole-block replacement.
  if (n * m > 4_000_000) {
    return [
      { kind: "del", text: before },
      { kind: "add", text: after },
    ];
  }

  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lcs[i]![j] =
        A[i] === B[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }

  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      push("same", A[i]!);
      i += 1;
      j += 1;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      push("del", A[i]!);
      i += 1;
    } else {
      push("add", B[j]!);
      j += 1;
    }
  }
  while (i < n) push("del", A[i++]!);
  while (j < m) push("add", B[j++]!);
  return out;
}
