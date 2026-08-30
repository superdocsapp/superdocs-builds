// @ts-check
/**
 * Paragraph alignment + word-level diff.
 *
 * Two real, standard algorithms from the `diff` package do the actual work:
 *   - diffArrays: LCS-based alignment of the paragraph sequence, so we know
 *     which paragraphs are unchanged, purely added, or purely removed.
 *   - diffWords: word-level diff within a paragraph pair we believe is a
 *     "modification" of the same paragraph, so we can classify what
 *     changed inside it.
 *
 * Known, documented limitation: diffArrays tells us block-level add/remove,
 * not "paragraph A became paragraph B". To detect *modifications* (as
 * opposed to unrelated delete+insert), this module pairs an immediately
 * adjacent removed-block with an immediately adjacent added-block,
 * position-by-position. That is a real, working heuristic — not a
 * fabricated one — but it is not the same as a similarity-scored alignment
 * (e.g. token-overlap + Hungarian matching), which is the honest next step
 * if paragraphs get reordered non-adjacently. See README "Known limitations".
 */
import { diffArrays, diffWords } from 'diff';

/**
 * @param {{paragraphs: Array<{text: string, styleId: string|null, runs: any[]}>}} basePayload
 * @param {{paragraphs: Array<{text: string, styleId: string|null, runs: any[]}>}} targetPayload
 */
export function alignParagraphs(basePayload, targetPayload) {
  const baseParas = basePayload.paragraphs;
  const targetParas = targetPayload.paragraphs;

  const blocks = diffArrays(baseParas, targetParas, {
    comparator: (a, b) => a.text === b.text,
  });

  // Walk the diffArrays output ourselves so we know exactly which base/target
  // indices were consumed by each block (needed to recover the *paired*
  // object on both sides for "common" — i.e. same text — paragraphs, since
  // identical text can still have different formatting).
  const ops = [];
  let bi = 0;
  let ti = 0;
  for (const part of blocks) {
    const count = part.value.length;
    if (!part.added && !part.removed) {
      for (let k = 0; k < count; k++) {
        ops.push({ type: 'common', base: baseParas[bi], target: targetParas[ti] });
        bi++;
        ti++;
      }
    } else if (part.removed) {
      ops.push({ type: 'removed-block', items: baseParas.slice(bi, bi + count) });
      bi += count;
    } else if (part.added) {
      ops.push({ type: 'added-block', items: targetParas.slice(ti, ti + count) });
      ti += count;
    }
  }

  // Merge an immediately-adjacent removed-block followed by an added-block
  // into position-paired "modified" entries, per the documented heuristic
  // above. Leftover unpaired items stay as pure removed/added.
  const merged = [];
  for (let i = 0; i < ops.length; i++) {
    const cur = ops[i];
    const next = ops[i + 1];
    if (cur.type === 'removed-block' && next && next.type === 'added-block') {
      const n = Math.min(cur.items.length, next.items.length);
      for (let k = 0; k < n; k++) {
        merged.push({ type: 'modified', base: cur.items[k], target: next.items[k] });
      }
      if (cur.items.length > n) {
        merged.push({ type: 'removed', items: cur.items.slice(n) });
      }
      if (next.items.length > n) {
        merged.push({ type: 'added', items: next.items.slice(n) });
      }
      i++; // consumed next
    } else if (cur.type === 'removed-block') {
      merged.push({ type: 'removed', items: cur.items });
    } else if (cur.type === 'added-block') {
      merged.push({ type: 'added', items: cur.items });
    } else {
      merged.push(cur);
    }
  }

  return merged;
}

/**
 * Real word-level Myers diff between two paragraph texts.
 * @param {string} baseText
 * @param {string} targetText
 */
export function wordDiff(baseText, targetText) {
  return diffWords(baseText, targetText);
}
