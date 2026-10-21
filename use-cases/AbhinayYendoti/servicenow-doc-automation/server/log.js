/**
 * Structured logging.
 *
 * One JSON line per event in production, a readable line in development. Every
 * request carries an id that also goes back to the browser in the error
 * envelope, so a user-reported failure can be found in the log without guessing.
 */

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

/** Anything matching these is redacted wherever it appears in a logged value. */
const SECRET_KEYS = /^(authorization|api[_-]?key|password|secret|token|file_base64)$/iu;
const SECRET_PATTERN = /\b(sk_|lce_)[A-Za-z0-9]{8,}/gu;

let threshold = LEVELS.info;
let pretty = true;

export function configureLogging({ level = "info", env = "development" } = {}) {
  threshold = LEVELS[level] ?? LEVELS.info;
  pretty = env !== "production";
}

export function redact(value, depth = 0) {
  if (depth > 6) return "[deep]";
  if (typeof value === "string") return value.replace(SECRET_PATTERN, "$1***");
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => redact(item, depth + 1));

  if (value && typeof value === "object") {
    const output = {};
    for (const [key, nested] of Object.entries(value)) {
      output[key] = SECRET_KEYS.test(key) ? "[redacted]" : redact(nested, depth + 1);
    }
    return output;
  }

  return value;
}

function emit(level, message, fields) {
  if (LEVELS[level] < threshold) return;

  const safe = fields ? redact(fields) : undefined;

  if (pretty) {
    const tail = safe && Object.keys(safe).length ? ` ${JSON.stringify(safe)}` : "";
    const line = `${new Date().toISOString()} ${level.toUpperCase().padEnd(5)} ${message}${tail}`;
    (level === "error" || level === "warn" ? console.error : console.log)(line);
    return;
  }

  const line = JSON.stringify({ ts: new Date().toISOString(), level, message, ...safe });
  (level === "error" || level === "warn" ? console.error : console.log)(line);
}

export const log = {
  debug: (message, fields) => emit("debug", message, fields),
  info: (message, fields) => emit("info", message, fields),
  warn: (message, fields) => emit("warn", message, fields),
  error: (message, fields) => emit("error", message, fields),
  /** A logger bound to one request, so the id does not have to be threaded by hand. */
  child(base) {
    return {
      debug: (message, fields) => emit("debug", message, { ...base, ...fields }),
      info: (message, fields) => emit("info", message, { ...base, ...fields }),
      warn: (message, fields) => emit("warn", message, { ...base, ...fields }),
      error: (message, fields) => emit("error", message, { ...base, ...fields })
    };
  }
};
