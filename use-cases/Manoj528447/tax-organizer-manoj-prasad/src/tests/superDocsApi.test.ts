import {
  SuperDocsApiClient,
  parsePossiblyDoubleEncoded,
  normalizeProposedChanges,
  fetchWithTimeout
} from '../services/superDocsApiService';

/**
 * Tests for the SuperDocs API client's contract handling.
 *
 * These run entirely against a mocked global.fetch -- no live SUPERDOCS_API_KEY
 * required, per the task doc's rule #7 ("Real tests exist and run without a
 * live key"). What's being tested is exactly what a live key would exercise:
 * correct base URL / endpoint paths, correct auth header, and -- most
 * importantly -- the documented "proposed-change content arrives as a
 * JSON-encoded string and needs a second parse" gotcha. Missing that parse is
 * called out in the task doc as the single most common integration bug, so it
 * gets direct coverage here rather than being left to manual testing.
 */
export async function runSuperDocsApiTests() {
  console.log('\n--- SuperDocs API Client Contract Tests ---');
  let passed = 0;
  let failed = 0;

  function assert(condition: boolean, testName: string) {
    if (condition) {
      console.log(`  ✅ [PASS] ${testName}`);
      passed++;
    } else {
      console.error(`  ❌ [FAIL] ${testName}`);
      failed++;
    }
  }

  // --- Gotcha #1: double-JSON-encoded diff content ---

  // Case A: pending_changes arrives as an already-parsed array (best case).
  const alreadyParsed = [
    {
      chunk_id: 'chunk_1',
      section_label: 'Section 3',
      change_type: 'modification',
      diff: { before: 'old text', after: 'new text' },
      explanation: 'Tightened language',
      citation: 'Schedule C, Line 12'
    }
  ];
  const resultA = normalizeProposedChanges(alreadyParsed, 'batch-test-1');
  assert(resultA.length === 1, 'normalizeProposedChanges handles an already-parsed array');
  assert(resultA[0].originalText === 'old text' && resultA[0].proposedText === 'new text',
    'normalizeProposedChanges extracts before/after text from an already-parsed entry');

  // Case B: the whole pending_changes payload arrives as a JSON-encoded STRING
  // (the documented gotcha) -- this is what breaks integrations that only
  // parse once via response.json().
  const doubleEncodedOuter = JSON.stringify(alreadyParsed);
  const resultB = normalizeProposedChanges(doubleEncodedOuter, 'batch-test-2');
  assert(resultB.length === 1, 'normalizeProposedChanges recovers from a double-JSON-encoded outer array');
  assert(resultB[0].proposedText === 'new text', 'normalizeProposedChanges extracts correct text after second parse of outer payload');

  // Case C: the outer array is parsed, but individual entries are themselves
  // JSON-encoded strings (a shape some integrators report seeing).
  const doubleEncodedEntries = [JSON.stringify(alreadyParsed[0])];
  const resultC = normalizeProposedChanges(doubleEncodedEntries, 'batch-test-3');
  assert(resultC.length === 1, 'normalizeProposedChanges recovers from double-encoded individual entries');
  assert(resultC[0].citation === 'Schedule C, Line 12', 'normalizeProposedChanges extracts citation after per-entry second parse');

  // Case D: garbage/non-JSON string should not throw -- degrade gracefully.
  let threw = false;
  try {
    parsePossiblyDoubleEncoded('not valid json {{{');
  } catch {
    threw = true;
  }
  assert(!threw, 'parsePossiblyDoubleEncoded never throws on malformed input');

  // Case E: null/undefined pending_changes should yield an empty array, not crash.
  assert(normalizeProposedChanges(null, 'batch-test-4').length === 0, 'normalizeProposedChanges handles null input safely');
  assert(normalizeProposedChanges(undefined, 'batch-test-4').length === 0, 'normalizeProposedChanges handles undefined input safely');

  // Case F: live API may name the "after" field differently. Broadened mapping
  // must catch new_text / replacement / content / proposed_text so a real diff
  // doesn't render as a blank AFTER box (the empty-diff-card gotcha).
  const altFields = [{ chunk_id: 'c1', diff: { old_text: 'was', new_text: 'now' } }];
  const resF = normalizeProposedChanges(altFields, 'batch-test-f');
  assert(resF[0].proposedText === 'now' && resF[0].originalText === 'was',
    'normalizeProposedChanges maps new_text/old_text field variants');
  assert(resF[0].unmappable !== true, 'A mappable diff is not flagged unmappable');

  const altTop = [{ chunk_id: 'c2', proposed_text: 'top-level proposed' }];
  assert(normalizeProposedChanges(altTop, 'batch-test-f2')[0].proposedText === 'top-level proposed',
    'normalizeProposedChanges falls back to top-level proposed_text');

  // Case G: an entry with no recognizable proposed text must be FLAGGED
  // unmappable (so the UI shows an honest notice), not silently blank.
  const noContent = [{ chunk_id: 'c3', section_label: 'Section 1', mystery_field: 'x' }];
  const resG = normalizeProposedChanges(noContent, 'batch-test-g');
  assert(resG[0].unmappable === true, 'An entry with no mappable proposed text is flagged unmappable, not silently empty');

  // Case H: the CONFIRMED real live SuperDocs shape (captured from an actual
  // /v1/chat/async response): new_html / old_html / ai_explanation / operation.
  // HTML content must be converted to readable text (tags stripped) and mapped
  // to the right fields, so the diff card shows real content, not a blank box
  // and not literal <h2>/<p> markup.
  const liveShape = [{
    change_id: '663d81df-64b2-4004-889d-81419f8e1789',
    operation: 'create',
    chunk_id: 'new',
    document_id: 'doc_primary',
    old_html: null,
    new_html: '<h2 style="color: #1f3a5f;">Important Dates</h2><p><strong>Document Deadline:</strong> April 15, 2026</p>',
    ai_explanation: "I have added an 'Important Dates' section to the end of your document with the deadline reminder of April 15, 2026."
  }];
  const resH = normalizeProposedChanges(liveShape, 'batch-test-h');
  assert(resH[0].unmappable !== true, 'Confirmed live shape (new_html) is mapped, not flagged unmappable');
  assert(/Important Dates/.test(resH[0].proposedText) && /April 15, 2026/.test(resH[0].proposedText),
    'new_html content is extracted into proposedText');
  assert(!/<h2|<p>|<strong>/.test(resH[0].proposedText), 'HTML tags are stripped from proposed text (no literal markup shown)');
  assert(/deadline reminder/.test(resH[0].explanation), 'ai_explanation is mapped to the diff explanation');
  assert(resH[0].changeType === 'addition', "operation 'create' maps to changeType 'addition'");

  // --- Endpoint contract: correct base URL, paths, and auth header ---
  // We mock global.fetch and assert the client calls the REAL documented
  // routes (session-based /v1/chat/async + /v1/jobs/{id} + /v1/chat/{sid}/approve
  // + /v1/documents/export), not the fabricated /documents/:id/chat style
  // routes an earlier version of this client used.

  const originalFetch = global.fetch;
  const originalEnv = { ...process.env };
  process.env.SUPERDOCS_API_KEY = 'sk_test_fake_key_for_contract_check';
  process.env.SUPERDOCS_API_BASE_URL = 'https://api.superdocs.app';

  try {
    const calledUrls: string[] = [];
    const calledAuthHeaders: string[] = [];
    let approveBody: any = null;

    // @ts-ignore -- test-only fetch mock
    global.fetch = async (url: string, init?: any) => {
      calledUrls.push(url);
      calledAuthHeaders.push(init?.headers?.Authorization || '');
      if (url.includes('/approve') && init?.body) {
        try { approveBody = JSON.parse(init.body); } catch { /* ignore */ }
      }

      if (url.endsWith('/v1/chat/async')) {
        return {
          ok: true,
          json: async () => ({ job_id: 'job_abc123' })
        } as any;
      }
      if (url.includes('/v1/jobs/job_abc123')) {
        return {
          ok: true,
          json: async () => ({
            status: 'awaiting_approval',
            metadata: {
              // Deliberately double-encoded, to exercise the real code path end to end.
              pending_changes: JSON.stringify([
                {
                  chunk_id: 'chunk_9',
                  diff: { before: 'A', after: 'B' },
                  explanation: 'Example',
                  citation: 'Form 1040'
                }
              ])
            }
          })
        } as any;
      }
      if (url.includes('/v1/chat/') && url.endsWith('/approve')) {
        return { ok: true, json: async () => ({ status: 'applied' }) } as any;
      }
      if (url.endsWith('/v1/documents/export')) {
        return {
          ok: true,
          headers: { get: () => 'application/pdf' },
          arrayBuffer: async () => new TextEncoder().encode('%PDF-fake').buffer
        } as any;
      }
      return { ok: false, status: 404, text: async () => 'not found in mock' } as any;
    };

    const client = new SuperDocsApiClient();

    const started = await client.startEditInstruction('batch-test-5', 'Tighten the summary');
    assert(started?.jobId === 'job_abc123', 'startEditInstruction hits POST /v1/chat/async and returns job_id');
    assert(calledUrls[0] === 'https://api.superdocs.app/v1/chat/async', 'startEditInstruction uses the real base URL and /v1/chat/async path');
    assert(calledAuthHeaders[0] === 'Bearer sk_test_fake_key_for_contract_check', 'startEditInstruction sends Bearer auth header');

    const jobResult = await client.pollJob('job_abc123', 'batch-test-5');
    assert(jobResult?.status === 'awaiting_approval', 'pollJob follows GET /v1/jobs/{id} to awaiting_approval');
    assert(jobResult?.pendingChanges.length === 1 && jobResult.pendingChanges[0].proposedText === 'B',
      'pollJob correctly double-parses metadata.pending_changes end-to-end');

    const approveResult = await client.approveChange('batch-test-5', 'chunk_9', true, 'job_abc123');
    assert(!!approveResult, 'approveChange hits POST /v1/chat/{session_id}/approve successfully');
    assert(calledUrls.some((u) => u === 'https://api.superdocs.app/v1/chat/taxorg-batch-test-5/approve'),
      'approveChange targets the session-scoped approve endpoint, not a fabricated /documents/:id/approve route');
    assert(
      approveBody && approveBody.job_id === 'job_abc123' && approveBody.approved === true,
      `approve body sends job_id + approved at the top level (real API requires this; got: ${JSON.stringify(approveBody)})`
    );
    assert(
      approveBody && !('changes' in approveBody),
      'approve body does NOT use the old nested changes[] shape that returned a 422'
    );

    const exportResult = await client.exportDocument('batch-test-5', 'pdf');
    assert(!!exportResult && exportResult.buffer.length > 0, 'exportDocument returns a binary buffer from POST /v1/documents/export');
    assert(exportResult?.contentType === 'application/pdf', 'exportDocument surfaces the real content-type header');

    // No-job_id case: the app's pre-seeded diffs never went through
    // /v1/chat/async, so there is no remote job to approve. This must return a
    // discriminated { skipped: true } marker (NOT null, and NOT an HTTP call)
    // so the server can log it calmly once instead of emitting a scary "remote
    // approve failed" line on every approve click. Regression for the log spam
    // seen in the live run: "SuperDocs approve skipped: no job_id available...".
    const urlCountBeforeSkip = calledUrls.length;
    const skipResult: any = await client.approveChange('batch-no-job', 'chunk_x', true /* no jobId, none remembered */);
    assert(
      skipResult && skipResult.skipped === true && skipResult.reason === 'no-remote-job',
      `approveChange returns a { skipped, reason } marker when no job_id exists (got: ${JSON.stringify(skipResult)})`
    );
    assert(
      calledUrls.length === urlCountBeforeSkip,
      'approveChange makes NO network call when there is no job_id to approve (no wasted/failed request)'
    );
  } finally {
    global.fetch = originalFetch;
    process.env.SUPERDOCS_API_KEY = originalEnv.SUPERDOCS_API_KEY;
    process.env.SUPERDOCS_API_BASE_URL = originalEnv.SUPERDOCS_API_BASE_URL;
  }

  console.log(`\n  SuperDocs API tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}

/**
 * Regression test for a real issue hit while verifying the live integration:
 * network calls to SuperDocs previously had no timeout at all, so a stalled
 * or unreachable connection would leave an upload/edit/approve/export
 * request hanging indefinitely with no way to distinguish it from a
 * legitimately slow (documented: 30s-several min) operation. This proves
 * fetchWithTimeout() actually aborts within its configured budget instead of
 * waiting forever, using a mock fetch that only resolves if aborted --
 * exactly what a real network stall looks like.
 */
export async function runTimeoutHardeningTests() {
  console.log('\n--- Network Timeout Hardening Tests ---');
  let passed = 0;
  let failed = 0;

  function assert(condition: boolean, testName: string) {
    if (condition) {
      console.log(`  ✅ [PASS] ${testName}`);
      passed++;
    } else {
      console.error(`  ❌ [FAIL] ${testName}`);
      failed++;
    }
  }

  const originalFetch = global.fetch;
  try {
    // A mock fetch that simulates a real network stall: it never resolves on
    // its own, only rejects when the AbortSignal fires (which is exactly how
    // Node's real fetch behaves when a request is aborted mid-flight).
    // @ts-ignore -- test-only fetch mock
    global.fetch = (_url: string, init?: any) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const err: any = new Error('The operation was aborted');
          err.name = 'AbortError';
          reject(err);
        });
        // Deliberately never resolves otherwise -- simulates a hung connection.
      });
    };

    const startedAt = Date.now();
    let threwTimeoutError = false;
    let timeoutMessage = '';
    try {
      await fetchWithTimeout('https://api.superdocs.app/v1/documents/upload', { method: 'POST' }, 200);
    } catch (err: any) {
      threwTimeoutError = true;
      timeoutMessage = err.message;
    }
    const elapsedMs = Date.now() - startedAt;

    assert(threwTimeoutError, 'fetchWithTimeout throws instead of hanging forever on a stalled connection');
    assert(timeoutMessage.includes('timed out'), 'fetchWithTimeout gives a clear "timed out" error message, not a raw AbortError');
    assert(elapsedMs < 2000, `fetchWithTimeout aborts close to its configured budget (took ${elapsedMs}ms for a 200ms timeout), not indefinitely`);

    // Connect-level failure should be retried once, then succeed. Simulates the
    // intermittent IPv6 connect-timeout seen live: first attempt throws
    // UND_ERR_CONNECT_TIMEOUT (connection never established -> nothing sent ->
    // safe to retry), second attempt succeeds.
    let connectAttempts = 0;
    // @ts-ignore test-only mock
    global.fetch = async (_url: string, _init?: any) => {
      connectAttempts++;
      if (connectAttempts === 1) {
        const err: any = new Error('fetch failed');
        err.cause = { code: 'UND_ERR_CONNECT_TIMEOUT' };
        throw err;
      }
      return { ok: true, status: 200, json: async () => ({ ok: true }) } as any;
    };
    const retried = await fetchWithTimeout('https://api.superdocs.app/v1/chat/async', { method: 'POST' }, 5000);
    assert(connectAttempts === 2 && (retried as any).ok === true,
      'fetchWithTimeout retries once on a connect-level failure and then succeeds');

    // An AbortError (our own timeout fired mid-flight, request already sent)
    // must NOT be retried -- retrying could double-submit a POST.
    let abortAttempts = 0;
    // @ts-ignore test-only mock
    global.fetch = (_url: string, init?: any) => {
      abortAttempts++;
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const err: any = new Error('The operation was aborted');
          err.name = 'AbortError';
          reject(err);
        });
      });
    };
    try {
      await fetchWithTimeout('https://api.superdocs.app/v1/chat/async', { method: 'POST' }, 150);
    } catch { /* expected timeout */ }
    assert(abortAttempts === 1, 'fetchWithTimeout does NOT retry an AbortError (avoids double-submitting a POST)');

    // pollJob resilience: a transient 429 during polling must NOT end the poll
    // (which previously caused approve to fire against an in_progress job -> a
    // real 400 "Job is not awaiting approval"). The loop should keep waiting
    // and resolve once the job reaches awaiting_approval.
    process.env.SUPERDOCS_API_KEY = 'sk_test_fake_key_for_poll_check';
    process.env.SUPERDOCS_API_BASE_URL = 'https://api.superdocs.app';
    let pollCount = 0;
    // @ts-ignore test-only mock
    global.fetch = async (url: string) => {
      if (url.includes('/v1/jobs/')) {
        pollCount++;
        if (pollCount === 1) return { ok: false, status: 429, text: async () => 'rate limited' } as any;
        return { ok: true, json: async () => ({ status: 'awaiting_approval', metadata: { pending_changes: [] } }) } as any;
      }
      return { ok: true, json: async () => ({}) } as any;
    };
    const pollClient = new SuperDocsApiClient();
    const pollResult = await pollClient.pollJob('job_poll_test', 'batch-poll');
    assert(pollCount >= 2, 'pollJob keeps polling through a transient 429 instead of giving up');
    assert(pollResult?.status === 'awaiting_approval', 'pollJob resolves to awaiting_approval after a transient error clears');
  } finally {
    global.fetch = originalFetch;
  }

  console.log(`\n  Timeout hardening tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}
