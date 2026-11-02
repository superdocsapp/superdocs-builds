const LIVE_KEY = /\b(?:sk|lce)_[a-f0-9]{16,}\b/gi;

export function redactSecrets<T>(value: T, secrets: string[] = []): T {
  const exact = secrets.filter((secret) => secret.length >= 8);
  const walk = (input: unknown): unknown => {
    if (typeof input === "string") {
      let text = input.replace(LIVE_KEY, "[redacted]");
      for (const secret of exact) {
        if (text.includes(secret)) text = text.split(secret).join("[redacted]");
      }
      return text;
    }
    if (Array.isArray(input)) return input.map(walk);
    if (input && typeof input === "object") {
      const copy: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(input)) copy[key] = walk(child);
      return copy;
    }
    return input;
  };
  return walk(value) as T;
}
