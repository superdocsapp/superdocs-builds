/**
 * Word-level diff. No dependency, per PLAN.md.pdf section 1's scope cut
 * ("no fancy diff rendering library ... polish loses to finishing").
 *
 * Standard LCS over tokens. Tokens keep their trailing whitespace so joining
 * the output reproduces the input exactly -- a diff that silently renormalises
 * spacing would show reviewers a change that was never proposed.
 */

/** Split into words while preserving whitespace and punctuation boundaries. */
export function tokenize(text) {
  if (!text) return [];
  return text.match(/\s+|[^\s]+/g) || [];
}

/** Strip HTML tags to visible text. The corpus stores styled HTML chunks. */
export function stripTags(html) {
  if (!html) return '';
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&ldquo;|&rdquo;/g, '"')
    .replace(/&rsquo;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Longest common subsequence table over two token arrays.
 * Returns a list of ops: {type: 'equal'|'insert'|'delete', tokens: string[]}
 */
export function diffTokens(oldTokens, newTokens) {
  const n = oldTokens.length;
  const m = newTokens.length;

  // lengths[i][j] = LCS length of oldTokens[i:] and newTokens[j:]
  const lengths = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lengths[i][j] =
        oldTokens[i] === newTokens[j]
          ? lengths[i + 1][j + 1] + 1
          : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }

  const ops = [];
  const push = (type, token) => {
    const last = ops[ops.length - 1];
    if (last && last.type === type) last.tokens.push(token);
    else ops.push({ type, tokens: [token] });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (oldTokens[i] === newTokens[j]) {
      push('equal', oldTokens[i]);
      i += 1;
      j += 1;
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      push('delete', oldTokens[i]);
      i += 1;
    } else {
      push('insert', newTokens[j]);
      j += 1;
    }
  }
  while (i < n) {
    push('delete', oldTokens[i]);
    i += 1;
  }
  while (j < m) {
    push('insert', newTokens[j]);
    j += 1;
  }
  return ops;
}

/** Convenience: diff two HTML chunks as visible text. */
export function diffHtml(oldHtml, newHtml) {
  return diffTokens(tokenize(stripTags(oldHtml)), tokenize(stripTags(newHtml)));
}

/** True when the two sides are textually identical. */
export function isNoop(oldHtml, newHtml) {
  return stripTags(oldHtml) === stripTags(newHtml);
}
