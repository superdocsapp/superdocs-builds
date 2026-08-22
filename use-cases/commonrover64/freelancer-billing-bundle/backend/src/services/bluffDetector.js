// Detects AI-generated placeholder text standing in for a real value.
const BLUFF_PATTERNS = [/please fill/i, /\bTBD\b/, /<mark>/i, /placeholder/i];

export function isBluffedChange(change) {
    return BLUFF_PATTERNS.some((pattern) => pattern.test(change.new_html));
}

// Checks a proposed change's new_html against a known correct value.
// Used for fields where we computed the truth ourselves (totals), so we
// don't have to trust the AI's number at all, we just verify it.
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
