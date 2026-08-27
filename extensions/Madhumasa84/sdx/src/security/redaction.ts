const SENSITIVE_KEY = /authorization|api[-_]?key|token|password|secret/i;
const SECRET_TEXT = /\b(?:Bearer\s+\S+|sk_[A-Za-z0-9_-]+)\b/gi;

export function redactUrl(value: string): string {
  try {
    const url = new URL(value);
    if (url.search || url.hash) {
      url.search = '?[REDACTED]';
      url.hash = '';
    }
    return url.toString();
  } catch {
    return value;
  }
}

export function redactText(value: string, secrets: readonly string[] = []): string {
  let redacted = value.replace(SECRET_TEXT, '[REDACTED]');
  for (const secret of secrets) {
    if (secret.length > 0) {
      redacted = redacted.split(secret).join('[REDACTED]');
    }
  }
  return redacted.replace(/https?:\/\/[^\s"'<>]+/g, redactUrl);
}

export function redactUnknown(value: unknown): unknown {
  if (typeof value === 'string') {
    return redactText(value);
  }
  if (Array.isArray(value)) {
    return value.map(redactUnknown);
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [
        key,
        SENSITIVE_KEY.test(key) ? '[REDACTED]' : redactUnknown(nested),
      ]),
    );
  }
  return value;
}

export function redactRecord(
  values: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [
      key,
      SENSITIVE_KEY.test(key) ? '[REDACTED]' : redactUnknown(value),
    ]),
  );
}
