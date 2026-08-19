/**
 * The one place that talks to the network.
 *
 * Deliberately not `server-only`: the eval harness (`evals/run.ts`) runs as a
 * plain Node script, not inside Next.js, and imports this module transitively
 * through the calibration verifier. It is still never imported from a "use
 * client" component.
 *
 * Three things every call needs and `fetch` does not give you:
 *
 * - A timeout. SuperDocs jobs legitimately run for minutes, but a *request*
 *   hanging forever is different from a job taking a while, and without a
 *   deadline a stuck socket becomes a stuck page with no error.
 * - Bounded retry on the failures that are actually transient (429, 5xx,
 *   network reset) and NEVER on the ones that are not (400, 401, 404, 422).
 *   Retrying a 400 just spends the budget again on the same wrong request.
 * - Errors that name the cause and the fix. "SuperDocs returned 401" is
 *   useless at 2am; "401 from SuperDocs: the API key was rejected. Check
 *   SUPERDOCS_API_KEY in .env.local" is not.
 */

export class UpstreamError extends Error {
  readonly status: number;
  readonly operation: string;
  readonly fix: string;
  readonly retryable: boolean;
  readonly body: string;

  constructor(params: {
    operation: string;
    status: number;
    body: string;
    fix: string;
    retryable: boolean;
  }) {
    super(`${params.operation} failed (${params.status}): ${params.fix}`);
    this.name = "UpstreamError";
    this.status = params.status;
    this.operation = params.operation;
    this.fix = params.fix;
    this.retryable = params.retryable;
    this.body = params.body;
  }

  /** Safe to send to the browser: never contains the key or the raw body. */
  toClient(): { error: string; cause: string; fix: string; status: number } {
    return {
      error: `${this.operation} failed`,
      cause: `Upstream responded ${this.status}`,
      fix: this.fix,
      status: this.status,
    };
  }
}

const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);

function fixFor(status: number, operation: string, body: string): string {
  switch (status) {
    case 400:
      return `SuperDocs rejected the request shape for ${operation}. This is a bug in this app, not a config problem. Upstream said: ${body.slice(0, 300)}`;
    case 401:
    case 403:
      return "The API key was rejected. Check SUPERDOCS_API_KEY in .env.local, and that the key has not been revoked at use.superdocs.app.";
    case 404:
      return `The session, job or document no longer exists. Start a new letter; a session that has been archived cannot be resumed.`;
    case 413:
      return "The document is too large for this path. Use the pre-signed upload path for large files.";
    case 422:
      return `SuperDocs could not process the content: ${body.slice(0, 300)}`;
    case 429:
      return "Operation limit or rate limit reached. Check remaining operations before retrying; the eval harness has a --max-ops stopping rule for exactly this.";
    default:
      return status >= 500
        ? "SuperDocs is having a problem on its side. This was retried and still failed; the letter is not lost, the session id is still valid, and retrying later resumes it."
        : `Unexpected status ${status} from SuperDocs.`;
  }
}

export interface RequestOptions extends RequestInit {
  /** Milliseconds before the request is aborted. */
  timeoutMs?: number;
  /** How many extra attempts after the first. */
  retries?: number;
  /** Label used in error messages and logs. */
  operation: string;
  /** Injected in tests to make backoff instant. */
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Full jitter backoff. Deterministic sequences make every client in a fleet
 * retry in lockstep, which is how a recovering service gets knocked over again.
 */
function backoffMs(attempt: number): number {
  const ceiling = Math.min(8000, 400 * 2 ** attempt);
  return Math.random() * ceiling;
}

export async function request(url: string, options: RequestOptions): Promise<Response> {
  const {
    timeoutMs = 30_000,
    retries = 2,
    operation,
    sleep = defaultSleep,
    ...init
  } = options;

  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await fetch(url, { ...init, signal: controller.signal });
      clearTimeout(timer);

      if (res.ok) return res;

      const body = await res.text().catch(() => "");
      const retryable = RETRYABLE_STATUS.has(res.status);

      const error = new UpstreamError({
        operation,
        status: res.status,
        body,
        fix: fixFor(res.status, operation, body),
        retryable,
      });

      if (!retryable || attempt === retries) throw error;
      lastError = error;
      await sleep(backoffMs(attempt));
      continue;
    } catch (err) {
      clearTimeout(timer);

      if (err instanceof UpstreamError) {
        if (!err.retryable || attempt === retries) throw err;
        lastError = err;
        await sleep(backoffMs(attempt));
        continue;
      }

      const aborted = err instanceof Error && err.name === "AbortError";
      const wrapped = new UpstreamError({
        operation,
        status: aborted ? 408 : 0,
        body: err instanceof Error ? err.message : String(err),
        fix: aborted
          ? `${operation} did not respond within ${timeoutMs}ms. Long drafts are normal — the job is still running upstream, and polling the job id will pick it up.`
          : `Could not reach SuperDocs (${err instanceof Error ? err.message : "network error"}). Check connectivity.`,
        retryable: true,
      });

      if (attempt === retries) throw wrapped;
      lastError = wrapped;
      await sleep(backoffMs(attempt));
    }
  }

  throw lastError instanceof Error ? lastError : new Error(`${operation} failed`);
}

export async function requestJson<T>(url: string, options: RequestOptions): Promise<T> {
  const res = await request(url, options);
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new UpstreamError({
      operation: options.operation,
      status: res.status,
      body: text.slice(0, 500),
      fix: `${options.operation} returned a non-JSON body. This usually means an HTML error page from a proxy rather than SuperDocs itself.`,
      retryable: false,
    });
  }
}
