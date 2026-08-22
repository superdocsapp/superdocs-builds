import type { GameString } from "./kit";

export type Violation = { id: string; kind: "missing_token" | "extra_token" | "missing_protected_term" | "limit"; message: string };
const tokenPattern = /\{[^{}]+\}|\[[^\]]+\]|<[^>]+>|%\d*\$?[sd]|\\n/g;

export function protectedTokens(value: string): string[] {
  return value.match(tokenPattern) ?? [];
}

export function displayWidth(value: string, language: string): number {
  const multiplier = /japanese|chinese|korean/i.test(language) ? 2 : /arabic|hebrew/i.test(language) ? 1.35 : 1;
  return [...value].reduce((total, char) => {
    if (/\p{Mark}/u.test(char)) return total;
    const wide = /[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7AF\uF900-\uFAFF\uFE10-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/u.test(char);
    return total + (wide ? 2 : multiplier);
  }, 0);
}

function counts(values: string[]): Map<string, number> {
  return values.reduce((all, value) => all.set(value, (all.get(value) ?? 0) + 1), new Map<string, number>());
}

function occurrenceCount(value: string, term: string): number {
  return term ? value.split(term).length - 1 : 0;
}

export function validateTranslations(strings: GameString[], translations: Record<string, string>, language: string, doNotTranslate: string[] = []): Violation[] {
  return strings.flatMap(item => {
    const target = translations[item.id] ?? "";
    const expected = counts(protectedTokens(item.source));
    const actual = counts(protectedTokens(target));
    const violations: Violation[] = [];
    for (const [token, expectedCount] of expected) {
      const actualCount = actual.get(token) ?? 0;
      if (actualCount < expectedCount) violations.push({ id: item.id, kind: "missing_token", message: `Missing protected token(s): ${token}${expectedCount - actualCount > 1 ? ` x${expectedCount - actualCount}` : ""}` });
    }
    for (const [token, actualCount] of actual) {
      const expectedCount = expected.get(token) ?? 0;
      if (actualCount > expectedCount) violations.push({ id: item.id, kind: "extra_token", message: `Unexpected protected token(s): ${token}${actualCount - expectedCount > 1 ? ` x${actualCount - expectedCount}` : ""}` });
    }
    for (const term of doNotTranslate.filter(value => item.source.includes(value))) {
      const expectedCount = occurrenceCount(item.source, term);
      const actualCount = occurrenceCount(target, term);
      if (actualCount < expectedCount) violations.push({ id: item.id, kind: "missing_protected_term", message: `Protected term must remain unchanged: ${term}${expectedCount - actualCount > 1 ? ` x${expectedCount - actualCount}` : ""}` });
    }
    const width = displayWidth(target, language);
    if (width > item.characterLimit) violations.push({ id: item.id, kind: "limit", message: `Display width ${width.toFixed(1)} exceeds ${item.characterLimit}.` });
    return violations;
  });
}
