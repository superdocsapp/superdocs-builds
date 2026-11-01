import type { OpenDocumentInput, ProposedEdit, SuperDocClient, SuperDocReceipt, SuperDocSession } from './superDocClient.js';
import { SuperDocError } from './errors.js';

export interface MockEditInput {
  instructionText: string;
  currentContent: string;
  /** 1-based attempt number within this session (recovery retries increment this). */
  attempt: number;
}

export interface MockEditOutcome {
  resultDocument: string;
}

export type MockEditResolver = (input: MockEditInput) => MockEditOutcome;

export interface MockSuperDocClientOptions {
  resolver: MockEditResolver;
  /** If set, the Nth call to open() throws a simulated SuperDocError instead of succeeding (1-based). */
  failOpenOnAttempt?: number;
  /** Simulated latency in ms. Fixed, not random, so runs stay reproducible. */
  latencyMs?: number;
}

/**
 * Clearly-labeled mock mode (brief section 25). This is NOT a stand-in for
 * real SuperDoc behavior in the sense of parsing real DOCX/XML — it exists
 * so Aegis's verification pipeline, recovery loop, and decision engine can
 * be exercised deterministically without a document editor, a browser, or
 * network access. Every test, the CLI demo, and the benchmark run against
 * this client; none of them are evidence of behavior against the real
 * SuperDoc Document API. See docs/ARCHITECTURE.md "Known limitations".
 */
export class MockSuperDocClient implements SuperDocClient {
  readonly mode = 'mock' as const;
  private openCount = 0;

  constructor(private readonly options: MockSuperDocClientOptions) {}

  async open(input: OpenDocumentInput): Promise<SuperDocSession> {
    this.openCount++;
    if (this.options.failOpenOnAttempt === this.openCount) {
      throw new SuperDocError(
        `Simulated failure opening document "${input.documentId}" (mock scenario: failOpenOnAttempt=${this.openCount})`,
        'MOCK_OPEN_FAILURE',
        `mock-open-${this.openCount}`,
      );
    }
    await delay(this.options.latencyMs ?? 1);
    return new MockSuperDocSession(input.documentId, input.content, this.options.resolver, this.options.latencyMs ?? 1);
  }
}

class MockSuperDocSession implements SuperDocSession {
  readonly sessionId: string;
  private attempt = 0;
  private pendingResult: string | null = null;
  private status: 'idle' | 'pending' | 'accepted' | 'rejected' | 'closed' = 'idle';

  constructor(
    documentId: string,
    private readonly originalContent: string,
    private readonly resolver: MockEditResolver,
    private readonly latencyMs: number,
  ) {
    this.sessionId = documentId;
  }

  async proposeEdit(instructionText: string): Promise<ProposedEdit> {
    if (this.status === 'closed') {
      throw new SuperDocError('Cannot propose an edit on a closed session', 'SESSION_CLOSED', this.sessionId);
    }
    this.attempt++;
    await delay(this.latencyMs);
    // Always resolves against the ORIGINAL content, never a previously
    // rejected attempt's output — a rejected tracked change must not
    // compound into the next retry (see src/recovery/recoveryController.ts).
    const outcome = this.resolver({ instructionText, currentContent: this.originalContent, attempt: this.attempt });
    this.pendingResult = outcome.resultDocument;
    this.status = 'pending';
    return {
      operationId: `${this.sessionId}:op${this.attempt}`,
      changeMode: 'tracked',
      receipt: { status: 'applied', operation: 'replace', detail: `Tracked change proposed on attempt ${this.attempt}.` },
      resultDocument: outcome.resultDocument,
    };
  }

  async decideTrackedChanges(decision: 'accept' | 'reject'): Promise<SuperDocReceipt> {
    if (this.status !== 'pending') {
      throw new SuperDocError('No pending tracked change to decide on', 'NO_PENDING_CHANGE', this.sessionId);
    }
    await delay(this.latencyMs);
    this.status = decision === 'accept' ? 'accepted' : 'rejected';
    return {
      status: decision === 'accept' ? 'applied' : 'rejected',
      operation: 'trackChanges.decide',
      detail: `Attempt ${this.attempt} was ${decision}ed.${decision === 'reject' ? ' Document reverted to its original state.' : ''}`,
    };
  }

  async close(): Promise<void> {
    // Safety net: a session must never be abandoned mid-review. If nothing
    // ever called decideTrackedChanges, treat that as an implicit reject so
    // an unreviewed tracked change can never silently "stick".
    if (this.status === 'pending') {
      this.status = 'rejected';
    }
    this.status = 'closed';
    this.pendingResult = null;
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
