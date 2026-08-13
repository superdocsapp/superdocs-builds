import type { GameString } from "./kit";

export type Violation = { id: string; kind: "missing_token" | "extra_token" | "limit"; message: string };
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

export function validateTranslations(strings: GameString[], translations: Record<string, string>, language: string): Violation[] {
  return strings.flatMap(item => {
    const target = translations[item.id] ?? "";
    const expected = protectedTokens(item.source);
    const actual = protectedTokens(target);
    const missing = expected.filter(token => !actual.includes(token));
    const extra = actual.filter(token => !expected.includes(token));
    const violations: Violation[] = [];
    if (missing.length) violations.push({ id: item.id, kind: "missing_token", message: `Missing protected token(s): ${missing.join(", ")}` });
    if (extra.length) violations.push({ id: item.id, kind: "extra_token", message: `Unexpected protected token(s): ${extra.join(", ")}` });
    const width = displayWidth(target, language);
    if (width > item.characterLimit) violations.push({ id: item.id, kind: "limit", message: `Display width ${width.toFixed(1)} exceeds ${item.characterLimit}.` });
    return violations;
  });
}
