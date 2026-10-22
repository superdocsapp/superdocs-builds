import { describe, it, expect, vi, beforeEach } from 'vitest';
import { runHeadlessGeneration, runHeadlessRevision } from '../src/services/headless';
import { computeFileHashesAsync } from '../src/utils/hash';

describe('Headless Machine Runner (Behavior #4: Machine-drivable pipeline)', () => {
  const mockFiles = new Map([
    ['src/index.ts', 'export function add(a: number, b: number) { return a + b; }'],
    ['package.json', '{"name": "math-lib", "version": "1.0.0"}'],
  ]);

  // Double-JSON payload format as returned by SuperDocs
  const mockPendingChangesEnvelope = JSON.stringify({
    content: JSON.stringify({
      batch_id: 'batch_h1',
      batch_total: 2,
      awaiting_kind: 'approval',
      changes: [
        {
          change_id: 'c1',
          operation: 'insert',
          new_html: '<h1>Math Lib</h1>',
          ai_explanation: 'Added title',
        },
        {
          change_id: 'c2',
          operation: 'insert',
          new_html: '<p>API: add(a, b)</p>',
          ai_explanation: 'Added function signature',
        },
      ],
    }),
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('runs complete initial generation pipeline end-to-end headlessly', async () => {
    const mockFetch = vi.fn()
      // 1. sessions/init
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: 'sess_123' }),
      })
      // 2. upload-base64
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'sess_123',
          document_id: 'doc_123',
          chunks_count: 1,
        }),
      })
      // 3. chat/async
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job_123' }),
      })
      // 4. jobs/job_123 (waitForJob)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job_123',
          status: 'awaiting_approval',
          metadata: {
            pending_changes: mockPendingChangesEnvelope,
          },
        }),
      })
      // 5. chat/sess_123/approve
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job_123',
          status: 'completed',
        }),
      })
      // 6. documents/export
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          download_url: 'https://api.superdocs.app/exports/doc.pdf',
          filename: 'README.pdf',
          format: 'pdf',
        }),
      })
      // 7. downloadExport
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => new Blob(['%PDF-1.4 mock content'], { type: 'application/pdf' }),
      });

    global.fetch = mockFetch;

    const result = await runHeadlessGeneration({
      apiKey: 'test-key',
      files: mockFiles,
      documentType: 'readme',
      instruction: 'Generate README for math-lib',
      // Programmatic gate: approve only c1
      approvalGate: (changes) => ({
        approved: true,
        selectedChanges: changes.filter(c => c.change_id === 'c1'),
      }),
      exportFormat: 'pdf',
    });

    expect(result.sessionId).toBe('sess_123');
    expect(result.documentId).toBe('doc_123');
    expect(result.approvedChanges).toHaveLength(1);
    expect(result.approvedChanges[0].change_id).toBe('c1');
    expect(result.rejectedChanges).toHaveLength(1);
    expect(result.rejectedChanges[0].change_id).toBe('c2');
    expect(result.exportResult?.format).toBe('pdf');
    expect(result.exportedBlob).toBeDefined();

    // Verify approve call was dispatched with only c1
    const approveCall = mockFetch.mock.calls.find(c => String(c[0]).includes('/approve'));
    expect(approveCall).toBeDefined();
    const approveBody = JSON.parse(approveCall[1].body);
    expect(approveBody.approved).toBe(true);
    expect(approveBody.changes.map((c: any) => c.change_id)).toEqual(['c1']);
  });

  it('runs zero-drift revision headlessly and short-circuits when no source changes exist', async () => {
    const baselineHashes = await computeFileHashesAsync(mockFiles);
    const mockFetch = vi.fn();
    global.fetch = mockFetch;

    const result = await runHeadlessRevision({
      apiKey: 'test-key',
      sessionId: 'sess_123',
      documentType: 'readme',
      originalInstruction: 'Generate README',
      baselineHashes,
      currentFiles: mockFiles, // Identical files
    });

    expect(result.hasChanges).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled(); // Zero API calls / zero tokens burnt
  });

  it('runs targeted revision when source files change', async () => {
    const baselineHashes = await computeFileHashesAsync(mockFiles);
    const modifiedFiles = new Map([
      ['src/index.ts', 'export function add(a: number, b: number) { return a + b; }\nexport function subtract(a: number, b: number) { return a - b; }'],
      ['package.json', '{"name": "math-lib", "version": "1.1.0"}'],
    ]);

    const mockFetch = vi.fn()
      // 1. chat/async for revision
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job_rev1' }),
      })
      // 2. jobs/job_rev1
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job_rev1',
          status: 'awaiting_approval',
          metadata: {
            pending_changes: mockPendingChangesEnvelope,
          },
        }),
      })
      // 3. chat/sess_123/approve
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job_rev1', status: 'completed' }),
      })
      // 4. documents/export
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          download_url: 'https://api.superdocs.app/exports/doc.pdf',
          filename: 'README.pdf',
          format: 'pdf',
        }),
      })
      // 5. downloadExport
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => new Blob(['%PDF-1.4 mock'], { type: 'application/pdf' }),
      });

    global.fetch = mockFetch;

    const result = await runHeadlessRevision({
      apiKey: 'test-key',
      sessionId: 'sess_123',
      documentType: 'readme',
      originalInstruction: 'Generate README',
      baselineHashes,
      currentFiles: modifiedFiles,
      exportFormat: 'pdf',
    });

    expect(result.hasChanges).toBe(true);
    expect(result.jobId).toBe('job_rev1');
    expect(result.approvedChanges).toHaveLength(2);
    expect(result.telemetry).toBeDefined();
  });
});
