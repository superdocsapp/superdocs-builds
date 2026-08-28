/**
 * Field names that must never appear in a log line or an EditProof's
 * `execution_metadata`, regardless of where the value came from (config,
 * adapter response headers, thrown errors, etc).
 */
const SECRET_KEY_PATTERN =
  /(api[_-]?key|token|secret|password|passwd|credential|authorization|auth[_-]?header|cookie|private[_-]?key)/i;

const SECRET_VALUE_PATTERNS: RegExp[] = [
  /\bsk-[a-zA-Z0-9_-]{10,}\b/g, // Anthropic/OpenAI-style API keys
  /\bBearer\s+[a-zA-Z0-9._-]{10,}\b/gi,
];

const REDACTED = '[REDACTED]';

/**
 * Deep-clones `value`, replacing any object property whose key looks secret
 * with `[REDACTED]`, and scrubbing known secret-shaped substrings out of
 * remaining string values. Safe to call on arbitrary config/error objects
 * before they are logged or embedded in an EditProof.
 */
export function redact<T>(value: T): T {
  return redactInner(value, new WeakSet()) as T;
}

function redactInner(value: unknown, seen: WeakSet<object>): unknown {
  if (typeof value === 'string') {
    let out = value;
    for (const pattern of SECRET_VALUE_PATTERNS) out = out.replace(pattern, REDACTED);
    return out;
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactInner(item, seen));
  }
  if (value !== null && typeof value === 'object') {
    if (seen.has(value)) return '[circular]';
    seen.add(value);
    const out: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SECRET_KEY_PATTERN.test(key) ? REDACTED : redactInner(val, seen);
    }
    return out;
  }
  return value;
}

/** True if the given string contains something that looks like a live secret. */
export function containsSecretShapedValue(value: string): boolean {
  return SECRET_VALUE_PATTERNS.some((pattern) => new RegExp(pattern.source, pattern.flags).test(value));
}
