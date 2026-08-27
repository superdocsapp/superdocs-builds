/**
 * Finding the after-side node that used to be a block.
 *
 * The diagnosis layer can only name a cause if it can point at what the block
 * became. Matching is by content, because content is the one thing a sanitiser,
 * a schema and a serialiser all leave alone: the identifier is gone, the tag may
 * have changed, the position has almost certainly shifted, but the sentence is
 * still the sentence.
 */

import { shortText } from './blocks.js';

const MINIMUM_TEXT_LENGTH = 3;
/** Same tag: the node is recognisably the same block, so be generous. */
const SIMILARITY_THRESHOLD = 0.6;
/** Different tag: only accept a match the text makes undeniable. */
const CROSS_TAG_THRESHOLD = 0.75;
const CROSS_TAG_MINIMUM_TOKENS = 3;

/** Index every element of the after document by its text, and by tag + text. */
export function buildAfterIndex(afterDocument) {
  const byTagAndText = new Map();
  const byText = new Map();

  for (const node of afterDocument.elements) {
    const text = node.text();
    if (text.length >= MINIMUM_TEXT_LENGTH) {
      push(byText, text, node);
      push(byTagAndText, node.tag + ' ' + text, node);
    }
  }
  return { byTagAndText, byText, used: new Set(), document: afterDocument };
}

function push(map, key, value) {
  const existing = map.get(key);
  if (existing) existing.push(value);
  else map.set(key, [value]);
}

/**
 * Token sets are cached per node: the similarity fallback compares one lost
 * block against every candidate in the after document, so recomputing the
 * candidate's tokens each time turns a linear scan into a quadratic one on
 * documents with thousands of blocks.
 */
const TOKEN_CACHE = new WeakMap();

function tokensOf(node) {
  const cached = TOKEN_CACHE.get(node);
  if (cached) return cached;
  const tokens = tokenise(node.text());
  TOKEN_CACHE.set(node, tokens);
  return tokens;
}

function tokenise(text) {
  return new Set(text.toLowerCase().split(/\W+/).filter(Boolean));
}

function setSimilarity(left, right) {
  if (left.size === 0 || right.size === 0) return 0;
  const [small, large] = left.size <= right.size ? [left, right] : [right, left];
  let shared = 0;
  for (const token of small) if (large.has(token)) shared += 1;
  return shared / (left.size + right.size - shared);
}

function tokenSimilarity(a, b) {
  if (!a || !b) return 0;
  return setSimilarity(tokenise(a), tokenise(b));
}

/**
 * @returns {{ node: object|null, how: string, unique: boolean, similarity: number }}
 * `how` is one of: exact-tag-and-text, text-only, similar-text, none.
 */
export function findCounterpart(block, index) {
  const text = block.text;

  if (text.length >= MINIMUM_TEXT_LENGTH) {
    const exact = pickUnused(index.byTagAndText.get(block.tag + ' ' + text), index.used);
    if (exact.node) {
      index.used.add(exact.node);
      return { node: exact.node, how: 'exact-tag-and-text', unique: exact.unique, similarity: 1 };
    }
    const sameText = pickUnused(index.byText.get(text), index.used);
    if (sameText.node) {
      index.used.add(sameText.node);
      return { node: sameText.node, how: 'text-only', unique: sameText.unique, similarity: 1 };
    }
  }

  // Nothing carries this text exactly. Fall back to similarity: a node whose
  // text is a near-neighbour is this block after somebody edited it, or after a
  // conversion rewrote its structure -- not a different block.
  const sameTag = bestSimilar(block, index, (node) => node.tag === block.tag, SIMILARITY_THRESHOLD);
  if (sameTag) {
    index.used.add(sameTag.node);
    return { node: sameTag.node, how: 'similar-text', unique: true, similarity: sameTag.score };
  }

  // A table that came back as a list, a heading that came back as a paragraph:
  // the tag is gone, so the text has to carry the whole match on its own.
  if (countTokens(text) >= CROSS_TAG_MINIMUM_TOKENS) {
    const anyTag = bestSimilar(block, index, () => true, CROSS_TAG_THRESHOLD);
    if (anyTag) {
      index.used.add(anyTag.node);
      return { node: anyTag.node, how: 'similar-text', unique: true, similarity: anyTag.score };
    }
  }

  return { node: null, how: 'none', unique: false, similarity: 0 };
}

/**
 * The best-scoring candidate above `threshold`, preferring the most specific
 * node: when a paragraph and the div wrapping it both carry the text, the
 * paragraph is the block, and the div is just where it lives.
 */
function bestSimilar(block, index, accept, threshold) {
  let best = null;
  let bestScore = 0;
  let bestSize = Infinity;
  const wanted = tokenise(block.text);
  for (const node of index.document.elements) {
    if (index.used.has(node)) continue;
    if (!accept(node)) continue;
    const score = setSimilarity(wanted, tokensOf(node));
    if (score < threshold) continue;
    const size = subtreeSize(node);
    if (score > bestScore || (score === bestScore && size < bestSize)) {
      best = node;
      bestScore = score;
      bestSize = size;
    }
  }
  return best ? { node: best, score: bestScore } : null;
}

function subtreeSize(node) {
  let count = 1;
  for (const child of node.children) count += subtreeSize(child);
  return count;
}

function countTokens(text) {
  return text.split(/\W+/).filter(Boolean).length;
}

function pickUnused(candidates, used) {
  if (!candidates || candidates.length === 0) return { node: null, unique: false };
  const free = candidates.filter((node) => !used.has(node));
  if (free.length === 0) return { node: null, unique: false };
  return { node: free[0], unique: candidates.length === 1 };
}

/** A locator for an after-side node, in the same shape blocks use. */
export function describeNode(node, afterDocument, idAttribute) {
  const position = afterDocument.positionOf(node.start);
  return {
    tag: node.tag,
    line: position.line,
    column: position.column,
    preview: shortText(node.text()),
    attributes: [...node.attributes.keys()],
    hasIdAttribute: node.attributes.has(idAttribute),
  };
}

export { tokenSimilarity, SIMILARITY_THRESHOLD, CROSS_TAG_THRESHOLD };
