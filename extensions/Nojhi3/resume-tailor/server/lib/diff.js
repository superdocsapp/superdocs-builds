// Word-level diff between an original block and its revised text.
//
// The CLI's tracked `replace` diffs the replaced range itself at the
// character level, so replacing a whole block fragments one revision into
// many mid-word edits ("using" -> "us" deleted + "utiliz" inserted) that a
// human reviewer can't meaningfully approve or reject. Instead, split the
// revision into the minimal set of disjoint regions at *word* boundaries
// (longest common subsequence of whitespace-delimited tokens), and replace
// each region separately. Each region then becomes exactly one tracked
// change, and the changes read as real edits ("Built" -> "Architected",
// "using" -> "utilizing").

const TOKEN_RE = /(\S+\s*)/g;

function tokenize(text) {
  const tokens = [];
  let m;
  while ((m = TOKEN_RE.exec(text))) {
    tokens.push({ text: m[0], start: m.index, end: m.index + m[0].length });
  }
  return tokens;
}

/**
 * Returns the minimal set of disjoint regions (character offsets into
 * `oldText`) that, when each is replaced by its `newText`, produce the
 * revised text. Pure insertions have start === end (zero-width selection).
 * Order is left to right.
 */
export function computeRegions(oldText, newText) {
  const a = tokenize(oldText);
  const b = tokenize(newText);
  const n = a.length;
  const m = b.length;

  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        a[i].text === b[j].text
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const regions = [];
  let i = 0;
  let j = 0;
  let oldAcc = [];
  let newAcc = [];

  const flush = () => {
    if (!oldAcc.length && !newAcc.length) return;
    let start;
    let end;
    if (oldAcc.length) {
      start = oldAcc[0].start;
      end = oldAcc[oldAcc.length - 1].end;
    } else {
      start = i < n ? a[i].start : oldText.length;
      end = start;
    }
    regions.push({ start, end, newText: newAcc.map((t) => t.text).join("") });
    oldAcc = [];
    newAcc = [];
  };

  while (i < n && j < m) {
    if (a[i].text === b[j].text) {
      flush();
      i++;
      j++;
    } else if (dp[i + 1][j] > dp[i][j + 1]) {
      oldAcc.push(a[i]);
      i++;
    } else {
      // On equal remaining match length prefer consuming the new token:
      // it keeps the diff local instead of swallowing long matched runs
      // into one region.
      newAcc.push(b[j]);
      j++;
    }
  }
  while (i < n) {
    oldAcc.push(a[i]);
    i++;
  }
  while (j < m) {
    newAcc.push(b[j]);
    j++;
  }
  flush();

  return regions;
}