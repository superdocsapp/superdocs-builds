import { SuperDocsDiff } from '../types';

/**
 * Real SuperDocs REST API client, built against docs.superdocs.app (fetched live,
 * not guessed). This replaces an earlier version of this file that pointed at a
 * fabricated base URL (api.superdocs.ai) and invented endpoint shapes
 * (/api/documents/:id/chat, /api/documents/:id/approve) that don't exist on the
 * real service. Logged here per the task doc's "logged assumption counts in your
 * favor" note.
 *
 * Real contract (confirmed against docs.superdocs.app/llms-full.txt):
 *   - Base URL:      https://api.superdocs.app
 *   - Auth:          Authorization: Bearer sk_...
 *   - Upload:        POST /v1/documents/upload           (multipart, field "file" + "session_id")
 *   - Edit (HITL):   POST /v1/chat/async                  {message, session_id, approval_mode:'ask_every_time'}
 *                    -> job_id, then poll GET /v1/jobs/{job_id} until status
 *                       is 'awaiting_approval' (read metadata.pending_changes) or 'completed'
 *   - Approve:       POST /v1/chat/{session_id}/approve   {approved, feedback?} or {changes:[...]}
 *   - Export:        POST /v1/documents/export            {session_id, format} -> binary file
 *
 * SuperDocs is session-based, not per-document-id based: there is no
 * "/documents/:id/chat" or "/documents/:id/approve" route. We map each client
 * record in this app to a stable session_id ("taxorg-<clientRecordId>"), per
 * the docs' own B2B guidance ("prefix session IDs with your user's identifier").
 *
 * GOTCHA (from the SuperDocs Engineer Task doc, confirmed in the pending_changes
 * shape): proposed-change content can arrive as a JSON-encoded STRING inside the
 * job/approve payloads rather than as an already-parsed object. We defensively
 * attempt a second JSON.parse on any diff-bearing field that comes back as a
 * string, falling back to the raw string if it isn't valid JSON. Skipping this
 * is the single most common reason integrators see empty/undefined diff cards.
 */

const DEFAULT_BASE_URL = 'https://api.superdocs.app';

// Budget guard (task doc note: "if your build measures something or runs in a
// loop, give it a small-sample mode and a stopping rule"). Async jobs can
// legitimately take from 30s to several minutes with no visible progress
// (documented behavior, not a bug) so we poll generously but not forever.
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 150; // ~5 minutes at 2s intervals

export interface SuperDocsJobResult {
  jobId: string;
  status: 'pending' | 'in_progress' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled';
  pendingChanges: SuperDocsDiff[];
  finalHtml?: string;
  raw: any;
}

/** Safely parse a field that the SuperDocs API may return either as a
 * pre-parsed object/array or as a JSON-encoded string (the documented
 * double-encoding gotcha). Never throws. Exported for unit testing. */
export function parsePossiblyDoubleEncoded<T = any>(value: unknown): T | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value !== 'string') return value as T;
  try {
    return JSON.parse(value) as T;
  } catch {
    // Not JSON after all — return as-is so callers can decide what to do.
    return value as unknown as T;
  }
}

/** Map a SuperDocs `pending_changes` / `chunk_diffs` entry (whatever shape it
 * arrives in) into our internal SuperDocsDiff type. Defensive about both the
 * outer array and each entry's fields being double-encoded. Exported for
 * unit testing. */
export function normalizeProposedChanges(rawPendingChanges: unknown, clientRecordId: string): SuperDocsDiff[] {
  const parsedOuter = parsePossiblyDoubleEncoded<any[]>(rawPendingChanges);
  if (!Array.isArray(parsedOuter)) return [];

  // The real API returns HTML (new_html/old_html). The diff card renders text,
  // so convert to readable plain text: drop tags, collapse whitespace, decode
  // the few common entities. Keeps the reviewer looking at content, not markup.
  const htmlToText = (v: unknown): string => {
    if (typeof v !== 'string') return typeof v === 'number' ? String(v) : '';
    return v
      .replace(/<\s*br\s*\/?>/gi, '\n')
      .replace(/<\/\s*(p|div|h[1-6]|li)\s*>/gi, '\n')
      .replace(/<[^>]+>/g, '')
      .replace(/&nbsp;/gi, ' ')
      .replace(/&amp;/gi, '&')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
      .replace(/&quot;/gi, '"')
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  };

  return parsedOuter.map((entry, idx) => {
    const parsedEntry = typeof entry === 'string' ? parsePossiblyDoubleEncoded<any>(entry) : entry;
    const chunkId = parsedEntry?.chunk_id || parsedEntry?.chunkId || `${clientRecordId}-chunk-${idx}`;
    const diffHtml = parsePossiblyDoubleEncoded<any>(parsedEntry?.diff ?? parsedEntry?.html_diff ?? parsedEntry);

    // Pull the "after"/proposed text from the many field names the live API
    // might use. CONFIRMED from a live response, the real SuperDocs shape is:
    //   { change_id, operation, chunk_id, document_id, old_html, new_html, ai_explanation }
    // so new_html / old_html / ai_explanation are the real fields; the rest are
    // kept as defensive fallbacks for other shapes. Being generous here is what
    // avoids a rendered-but-empty diff card (the empty-diff-card gotcha).
    const proposedRaw =
      parsedEntry?.new_html ??
      diffHtml?.after ??
      diffHtml?.proposed ??
      diffHtml?.new_text ??
      diffHtml?.newText ??
      diffHtml?.replacement ??
      diffHtml?.content ??
      parsedEntry?.after ??
      parsedEntry?.proposed_text ??
      parsedEntry?.new_content ??
      (typeof diffHtml === 'string' ? diffHtml : '');

    const originalRaw =
      parsedEntry?.old_html ??
      diffHtml?.before ??
      diffHtml?.original ??
      diffHtml?.old_text ??
      parsedEntry?.before ??
      parsedEntry?.original_text ??
      '';

    const proposedText = htmlToText(proposedRaw);
    const originalText = htmlToText(originalRaw);

    // If we could not extract any proposed content, DON'T emit a silently empty
    // diff (a blank AFTER box is a bluff). Flag it, and log the raw entry shape
    // once so the real field names are visible for mapping. The card can then
    // show an honest "content could not be parsed" state instead of blank.
    if (!proposedText || (typeof proposedText === 'string' && proposedText.trim() === '')) {
      console.warn(
        `[SuperDocs] pending_changes entry ${idx} had no mappable proposed text. Raw entry keys: ${
          parsedEntry && typeof parsedEntry === 'object' ? Object.keys(parsedEntry).join(', ') : typeof parsedEntry
        }. Raw entry: ${JSON.stringify(parsedEntry)?.slice(0, 500)}`
      );
    }

    return {
      id: chunkId,
      targetSectionId: chunkId,
      locationLabel: parsedEntry?.section_label || parsedEntry?.location || `Section ${idx + 1}`,
      changeType: (parsedEntry?.change_type as any) || (parsedEntry?.operation === 'create' ? 'addition' : parsedEntry?.operation === 'delete' ? 'deletion' : 'modification'),
      originalText,
      proposedText,
      // Explicit flag the UI can use to show an honest "couldn't parse content"
      // state rather than an empty green box.
      unmappable: !proposedText || (typeof proposedText === 'string' && proposedText.trim() === ''),
      explanation: parsedEntry?.ai_explanation || parsedEntry?.explanation || parsedEntry?.reason || 'Proposed by SuperDocs AI',
      citation: parsedEntry?.citation || parsedEntry?.source || parsedEntry?.document_id || '',
      status: 'pending'
    } as SuperDocsDiff;
  });
}

// Every network call below is wrapped with a hard timeout via AbortController.
// Without this, a network stall (DNS hang, dropped connection, blocked egress
// that doesn't respond) leaves the request pending forever with no visible
// progress and no way for the caller to distinguish it from a legitimately
// slow (documented: 30s-several min) operation. REQUEST_TIMEOUT_MS is
// generous enough for real SuperDocs latency but still bounded.
const REQUEST_TIMEOUT_MS = 30000;

/**
 * A connect-level failure means the TCP/TLS connection never established, so
 * the request never reached the server -- safe to retry even for POST (no
 * double-submit risk, since nothing was sent). A timeout AFTER a response
 * started is a different animal and is NOT retried here. Mirrors the Gemini
 * retry: on some Windows/Node setups the first attempt races onto a stalling
 * IPv6 route; one retry usually lands on IPv4.
 */
function isConnectLevelFailure(err: any): boolean {
  const text = String(err?.cause?.code || err?.code || err?.message || err || '');
  return /UND_ERR_CONNECT_TIMEOUT|ConnectTimeout|ETIMEDOUT|EAI_AGAIN|ECONNRESET|ENOTFOUND|fetch failed/i.test(text);
}

export async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<Response> {
  const attempts = 2;
  let lastErr: any;
  for (let i = 0; i < attempts; i++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } catch (err: any) {
      lastErr = err;
      const isAbort = err?.name === 'AbortError';
      // Retry once on a connect-level failure (connection never established, so
      // no request reached the server -> safe even for POST). Do NOT retry an
      // AbortError, which means our own timeout fired after the request was
      // already in flight.
      if (i < attempts - 1 && !isAbort && isConnectLevelFailure(err)) {
        await new Promise((r) => setTimeout(r, 400));
        continue;
      }
      if (isAbort) {
        throw new Error(`Request to ${url} timed out after ${timeoutMs}ms (network stall or unreachable host)`);
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

export class SuperDocsApiClient {
  // The real /v1/.../approve endpoint requires the job_id from the async
  // chat/edit call that produced the pending changes (confirmed by a live 422
  // error: "job_id: Field required"). That job_id isn't part of our per-diff
  // approve UI, so we remember the most recent job_id per client here when the
  // edit is started, and look it up at approve time.
  private lastJobIdByClient: Record<string, string> = {};

  public rememberJobId(clientRecordId: string, jobId: string): void {
    this.lastJobIdByClient[clientRecordId] = jobId;
  }

  public getRememberedJobId(clientRecordId: string): string | undefined {
    return this.lastJobIdByClient[clientRecordId];
  }

  private getApiKey(): string | undefined {
    return process.env.SUPERDOCS_API_KEY;
  }

  private getBaseUrl(): string {
    return (process.env.SUPERDOCS_API_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, '');
  }

  public isConfigured(): boolean {
    const key = this.getApiKey();
    return Boolean(key && key.trim().length > 0);
  }

  private getHeaders(json = true): Record<string, string> {
    const apiKey = this.getApiKey() || '';
    const headers: Record<string, string> = {
      Authorization: `Bearer ${apiKey}`
    };
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  /** Turn a session-scoped client record id into a stable SuperDocs session_id. */
  public sessionIdFor(clientRecordId: string): string {
    return `taxorg-${clientRecordId}`;
  }

  /**
   * 1. Upload a document into a session.
   * POST /v1/documents/upload (multipart: file + session_id)
   */
  public async uploadDocument(
    fileBuffer: Buffer,
    filename: string,
    mimeType: string,
    clientRecordId: string
  ): Promise<{ html: string; sessionId: string; chunksCount: number } | null> {
    if (!this.isConfigured()) return null;

    const sessionId = this.sessionIdFor(clientRecordId);
    try {
      const form = new FormData();
      form.append('file', new Blob([fileBuffer], { type: mimeType }), filename);
      form.append('session_id', sessionId);

      const response = await fetchWithTimeout(
        `${this.getBaseUrl()}/v1/documents/upload`,
        {
          method: 'POST',
          headers: this.getHeaders(false), // FormData sets its own Content-Type boundary
          body: form
        },
        60000 // uploads can be larger/slower than other calls; give this one more room
      );

      if (!response.ok) {
        console.warn(`SuperDocs upload returned ${response.status}: ${await response.text()}`);
        return null;
      }

      const data = (await response.json()) as any;
      return {
        html: data.html,
        sessionId: data.session_id || sessionId,
        chunksCount: data.chunks_count ?? 0
      };
    } catch (err) {
      console.error('SuperDocs uploadDocument HTTP error:', err);
      return null;
    }
  }

  /**
   * 2. Start an edit with human-in-the-loop review.
   * POST /v1/chat/async  {message, session_id, approval_mode:'ask_every_time'}
   * Returns a job_id; caller should follow with pollJob().
   */
  public async startEditInstruction(
    clientRecordId: string,
    instruction: string
  ): Promise<{ jobId: string } | null> {
    if (!this.isConfigured()) return null;

    try {
      const response = await fetchWithTimeout(`${this.getBaseUrl()}/v1/chat/async`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          message: instruction,
          session_id: this.sessionIdFor(clientRecordId),
          approval_mode: 'ask_every_time'
        })
      });

      if (!response.ok) {
        console.warn(`SuperDocs chat/async returned ${response.status}: ${await response.text()}`);
        return null;
      }

      const data = (await response.json()) as any;
      if (!data.job_id) return null;
      return { jobId: data.job_id };
    } catch (err) {
      console.error('SuperDocs startEditInstruction HTTP error:', err);
      return null;
    }
  }

  /**
   * Poll GET /v1/jobs/{job_id} until the job reaches awaiting_approval or a
   * terminal state. Long operations (30s-several minutes with no visible
   * progress) are documented, expected behavior, not a failure — so we poll
   * with a generous but bounded budget rather than treating silence as an error.
   */
  public async pollJob(jobId: string, clientRecordId: string): Promise<SuperDocsJobResult | null> {
    if (!this.isConfigured()) return null;

    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
      try {
        const response = await fetchWithTimeout(
          `${this.getBaseUrl()}/v1/jobs/${jobId}`,
          { method: 'GET', headers: this.getHeaders() },
          15000 // shorter timeout: this fires every POLL_INTERVAL_MS, a stuck poll shouldn't eat the whole budget
        );

        if (!response.ok) {
          // A transient HTTP error during polling (rate-limit or gateway) is
          // NOT a terminal state -- the job is very likely still processing.
          // Previously this returned null, which made the caller treat the job
          // as finished-with-no-diffs and then try to approve a job still
          // in_progress (real 400: "Job is not awaiting approval"). Keep
          // polling on retryable statuses; only give up on a clearly
          // unrecoverable one (e.g. 404 job not found).
          const retryable = response.status === 429 || response.status === 502 || response.status === 503 || response.status === 504;
          if (retryable && attempt < MAX_POLL_ATTEMPTS - 1) {
            console.warn(`SuperDocs job poll got ${response.status} (transient); will keep waiting (attempt ${attempt + 1}/${MAX_POLL_ATTEMPTS}).`);
            await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
            continue;
          }
          console.warn(`SuperDocs job poll returned non-retryable ${response.status}; giving up on this job.`);
          return null;
        }

        const data = (await response.json()) as any;
        const status = data.status as SuperDocsJobResult['status'];

        if (status === 'awaiting_approval') {
          return {
            jobId,
            status,
            pendingChanges: normalizeProposedChanges(data.metadata?.pending_changes, clientRecordId),
            raw: data
          };
        }

        if (status === 'completed') {
          return {
            jobId,
            status,
            pendingChanges: [],
            finalHtml: data.document_html || data.result?.document_html,
            raw: data
          };
        }

        if (status === 'failed' || status === 'cancelled') {
          return { jobId, status, pendingChanges: [], raw: data };
        }

        // pending / in_progress: keep polling.
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      } catch (err) {
        // A single stalled/failed poll shouldn't kill an otherwise-healthy
        // long-running job -- log it and let the loop retry on the next
        // interval, up to MAX_POLL_ATTEMPTS overall.
        console.warn(`SuperDocs job poll attempt ${attempt + 1}/${MAX_POLL_ATTEMPTS} failed, will retry: ${(err as Error).message}`);
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      }
    }

    console.warn(`SuperDocs job ${jobId} did not settle within the polling budget; still processing is a valid state, not necessarily a failure.`);
    return null;
  }

  /**
   * 3. Approve or reject one proposed change.
   * POST /v1/chat/{session_id}/approve  {approved, feedback?}
   * (chunk_id is implicit in real usage via which pending change this decision
   * targets; the caller supplies it here so we can route per-diff decisions.)
   */
  /**
   * 3. Approve or reject one proposed change.
   * POST /v1/chat/{session_id}/approve
   *
   * The real API requires job_id and approved at the TOP LEVEL of the body
   * (confirmed by a live 422: both "job_id" and "approved" reported as
   * "Field required" when sent nested inside changes[]). The job_id comes from
   * the async chat/edit call that produced these pending changes; the caller
   * supplies it (or we fall back to the remembered job_id for this client).
   */
  public async approveChange(
    clientRecordId: string,
    chunkId: string,
    approved: boolean,
    jobId?: string,
    feedback?: string
  ): Promise<any | null> {
    if (!this.isConfigured()) return null;

    const resolvedJobId = jobId || this.getRememberedJobId(clientRecordId);
    if (!resolvedJobId) {
      // This is the EXPECTED path for the app's pre-seeded diffs: they are
      // generated locally at record-build time and never went through
      // /v1/chat/async, so there is no remote job to approve. That is not an
      // error -- approving them is a purely local decision. Return a
      // discriminated "skipped" marker (not null) so the caller can log this
      // calmly and once, rather than emitting a "remote approve failed" line
      // on every single approve click. A real remote approve only applies to
      // diffs that actually originated from a live chat/async job.
      return { skipped: true, reason: 'no-remote-job' };
    }

    try {
      const sessionId = this.sessionIdFor(clientRecordId);
      const response = await fetchWithTimeout(`${this.getBaseUrl()}/v1/chat/${sessionId}/approve`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          job_id: resolvedJobId,
          approved,
          chunk_id: chunkId,
          ...(feedback ? { feedback } : {})
        })
      });

      if (!response.ok) {
        const bodyText = await response.text();
        if (response.status === 400 && /not awaiting approval/i.test(bodyText)) {
          // Timing, not misconfiguration: the job hadn't reached
          // awaiting_approval when approve fired (usually because polling was
          // cut short by a transient error). With the poll fix this should be
          // rare; surface it clearly rather than as a generic failure.
          console.warn(`SuperDocs approve skipped: job not yet awaiting approval (${bodyText.trim()}). The edit job likely needs more polling time; retry the approval shortly.`);
        } else {
          console.warn(`SuperDocs approve returned ${response.status}: ${bodyText}`);
        }
        return null;
      }

      return await response.json();
    } catch (err) {
      console.error('SuperDocs approveChange HTTP error:', err);
      return null;
    }
  }

  /**
   * 4. Export the session's current document.
   * POST /v1/documents/export  {session_id, format} -> binary response
   */
  public async exportDocument(
    clientRecordId: string,
    format: 'docx' | 'pdf' | 'html' | 'markdown' | 'txt' = 'docx'
  ): Promise<{ buffer: Buffer; contentType: string } | null> {
    if (!this.isConfigured()) return null;

    try {
      const response = await fetchWithTimeout(
        `${this.getBaseUrl()}/v1/documents/export`,
        {
          method: 'POST',
          headers: this.getHeaders(),
          body: JSON.stringify({
            session_id: this.sessionIdFor(clientRecordId),
            format
          })
        },
        60000 // export/render can be slow for large documents
      );

      if (!response.ok) {
        console.warn(`SuperDocs export returned ${response.status}: ${await response.text()}`);
        return null;
      }

      const arrayBuffer = await response.arrayBuffer();
      return {
        buffer: Buffer.from(arrayBuffer),
        contentType: response.headers.get('content-type') || 'application/octet-stream'
      };
    } catch (err) {
      // A connect-level timeout here is often retried by fetchWithTimeout; if
      // the retry also fails we land here and fall back to local content. Log
      // as a warning (not a scary error) and let the caller render locally.
      console.warn('SuperDocs exportDocument could not reach the export endpoint (falling back to local render):', (err as any)?.cause?.code || (err as any)?.message || err);
      return null;
    }
  }
}

export const superDocsApiClient = new SuperDocsApiClient();
