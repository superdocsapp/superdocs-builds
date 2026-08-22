// Detects AI-generated placeholder text standing in for a real value.
const BLUFF_PATTERNS = [/please fill/i, /\bTBD\b/, /<mark>/i, /placeholder/i];

// Only flags a pattern as a bluff if it's newly introduced by this edit,
// not already present in old_html. This avoids false positives on partial
// table fills, where untouched rows still legitimately show TBD within
// the same html chunk as a row that was correctly filled in.
export function isBluffedChange(change) {
    return BLUFF_PATTERNS.some((pattern) => {
        const inNew = pattern.test(change.new_html);
        const inOld = pattern.test(change.old_html);
        return inNew && !inOld;
    });
}

export function valueMismatch(change, expectedValue) {
    const numbersInHtml = change.new_html.match(/[\d.]+/g) || [];
    const expectedStr = String(expectedValue);
    return !numbersInHtml.includes(expectedStr);
}

export function filterBluffedChanges(changes) {
    const safe = [];
    const bluffed = [];

    for (const change of changes) {
        if (isBluffedChange(change)) {
            bluffed.push(change);
        } else {
            safe.push(change);
        }
    }

    return { safe, bluffed };
}
