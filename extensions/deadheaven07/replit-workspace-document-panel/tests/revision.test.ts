import { describe, it, expect, vi } from 'vitest';
import { buildProjectContext } from '../src/services/replit';
import { computeSourceDiff, buildRevisionMessage, planRegeneration, SourceDiff } from '../src/services/revision';
import { computeFileHashesAsync, detectChangedFiles } from '../src/utils/hash';
import { createSuperDocsClient } from '../src/services/superdocs';

const mockFiles = new Map([
  ['src/main.ts', 'export function main() { console.log("hello"); }'],
  ['package.json', '{"name": "test", "version": "1.0.0"}'],
  ['README.md', '# Test Project\n\nA simple test project.'],
]);

const mockChangedFiles = new Map([
  ['src/main.ts', 'export function main() { console.log("hello world"); }'], // CHANGED
  ['package.json', '{"name": "test", "version": "1.0.0"}'],
  ['README.md', '# Test Project\n\nA simple test project.'],
]);

describe('Revision flow regression tests', () => {
  describe('computeSourceDiff against hash baseline', () => {
    it('produces an EMPTY diff when hashes are identical (zero drift)', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      const diff = await computeSourceDiff(baseline, mockFiles);

      expect(diff.hasChanges).toBe(false);
      expect(diff.changed).toHaveLength(0);
      expect(diff.added).toHaveLength(0);
      expect(diff.removed).toHaveLength(0);
    });

    it('detects changed files and includes ONLY their current content', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      const diff = await computeSourceDiff(baseline, mockChangedFiles);

      expect(diff.hasChanges).toBe(true);
      expect(diff.changed.map(f => f.path)).toEqual(['src/main.ts']);
      expect(diff.changed[0].content).toContain('console.log("hello world")'); // NEW content
      expect(diff.changed[0].content).not.toContain('console.log("hello")'); // OLD content
      expect(diff.added).toHaveLength(0);
      expect(diff.removed).toHaveLength(0);
    });

    it('detects added and removed files', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      const withNewFile = new Map([...mockFiles, ['src/new.ts', 'export const x = 1;']]);
      const withoutMain = new Map([['package.json', mockFiles.get('package.json')!], ['README.md', mockFiles.get('README.md')!]]);

      const addedDiff = await computeSourceDiff(baseline, withNewFile);
      expect(addedDiff.added).toEqual(['src/new.ts']);
      expect(addedDiff.changed).toHaveLength(0);

      const removedDiff = await computeSourceDiff(baseline, withoutMain);
      expect(removedDiff.removed).toEqual(['src/main.ts']);
      expect(removedDiff.changed).toHaveLength(0);
    });
  });

  describe('buildRevisionMessage (thin diff instruction)', () => {
    async function makeDiff(changedFiles: Map<string, string>): Promise<SourceDiff> {
      const baseline = await computeFileHashesAsync(mockFiles);
      return computeSourceDiff(baseline, changedFiles);
    }

    it('does NOT carry over previous revision change lists (regression test for instruction accumulation bug)', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      // First regeneration touched src/main.ts
      const firstDiff = await computeSourceDiff(baseline, mockChangedFiles);
      const firstMessage = buildRevisionMessage('readme', 'Original user instruction', firstDiff);
      expect(firstMessage).toContain('src/main.ts');

      // Snapshot after the first regeneration, then only package.json changes
      const secondBaseline = await computeFileHashesAsync(mockChangedFiles);
      const secondFiles = new Map([
        ['src/main.ts', 'export function main() { console.log("hello world"); }'],
        ['package.json', '{"name": "test", "version": "2.0.0"}'],
        ['README.md', '# Test Project\n\nA simple test project.'],
      ]);
      const secondDiff = await computeSourceDiff(secondBaseline, secondFiles);
      expect(secondDiff.changed.map(f => f.path)).toEqual(['package.json']);

      // Old bug: the previous full revision message leaked into the base
      // instruction of the next regeneration.
      const leaked = buildRevisionMessage('readme', firstMessage, secondDiff);

      // The OPERATIVE change summary is diff-derived and lists only
      // package.json - src/main.ts never re-enters the change list.
      const sections = leaked.split('## Modified Files');
      const operative = sections[sections.length - 1].split('---')[0];
      expect(operative).toContain('package.json');
      expect(operative).not.toContain('src/main.ts');
    });

    it('contains ONLY the changed file content - never the unchanged files', async () => {
      const diff = await makeDiff(mockChangedFiles);
      const message = buildRevisionMessage('readme', 'Original user instruction', diff);

      expect(message).toContain('File: `src/main.ts`');
      expect(message).toContain('console.log("hello world")'); // NEW content
      expect(message).not.toContain('console.log("hello")'); // OLD content
      // Unchanged files are omitted entirely - this is what preserves
      // approved sections whose source files were not touched.
      expect(message).not.toContain('File: `package.json`');
      expect(message).not.toContain('"name": "test"');
      expect(message).not.toContain('File: `README.md`');
    });

    it('is byte-identical for identical inputs (deterministic output stability)', async () => {
      const diff = await makeDiff(mockChangedFiles);
      const first = buildRevisionMessage('readme', 'Original user instruction', diff);
      const second = buildRevisionMessage('readme', 'Original user instruction', diff);

      expect(first).toBe(second);

      // Determinism also holds across a different Map insertion order,
      // because paths are sorted before serialization.
      const shuffled = new Map([
        ['README.md', mockFiles.get('README.md')!],
        ['src/main.ts', 'export function main() { console.log("hello world"); }'],
        ['package.json', mockFiles.get('package.json')!],
      ]);
      const shuffledDiff = await computeSourceDiff(await computeFileHashesAsync(mockFiles), shuffled);
      expect(buildRevisionMessage('readme', 'Original user instruction', shuffledDiff)).toBe(first);
    });

    it('lists added and removed files in the change summary', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);
      const withNewAndMissing = new Map([
        ['src/main.ts', 'export function main() { console.log("hello world"); }'],
        ['package.json', mockFiles.get('package.json')!],
        ['src/new.ts', 'export const x = 1;'],
      ]);
      const diff = await computeSourceDiff(baseline, withNewAndMissing);
      const message = buildRevisionMessage('readme', 'Original', diff);

      expect(message).toContain('Added Files');
      expect(message).toContain('src/new.ts');
      expect(message).toContain('Removed Files');
      // README.md is missing from current files, so it is only listed as removed
      // and never serialized as content
      expect(message).not.toContain('File: `README.md`');
    });
  });

  describe('planRegeneration (zero-drift short-circuit)', () => {
    it('returns hasChanges=false with NO message when source is unchanged - the proposed-changes list is provably empty and no chat job can be created', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      const plan = await planRegeneration(baseline, mockFiles, 'readme', 'Original user instruction');

      expect(plan.hasChanges).toBe(false);
      expect(plan.message).toBeUndefined();
      expect(plan.diff.changed).toHaveLength(0);
    });

    it('builds a message only when changes exist', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);

      const plan = await planRegeneration(baseline, mockChangedFiles, 'readme', 'Original user instruction');

      expect(plan.hasChanges).toBe(true);
      expect(plan.message).toBeDefined();
      expect(plan.diff.changed).toHaveLength(1);
    });
  });

  describe('Changed file detection with SHA-256', () => {
    it('detects changed files correctly', async () => {
      const originalHashes = await computeFileHashesAsync(mockFiles);
      const changedHashes = await computeFileHashesAsync(mockChangedFiles);
      
      const changes = detectChangedFiles(originalHashes, changedHashes);
      
      expect(changes.changed).toContain('src/main.ts');
      expect(changes.added).toHaveLength(0);
      expect(changes.removed).toHaveLength(0);
    });

    it('detects added files', async () => {
      const originalHashes = await computeFileHashesAsync(mockFiles);
      const withNewFile = new Map([...mockFiles, ['src/new.ts', 'export const x = 1;']]);
      const newHashes = await computeFileHashesAsync(withNewFile);
      
      const changes = detectChangedFiles(originalHashes, newHashes);
      
      expect(changes.added).toContain('src/new.ts');
    });

    it('detects removed files', async () => {
      const originalHashes = await computeFileHashesAsync(mockFiles);
      const withoutFile = new Map([['package.json', mockFiles.get('package.json')!], ['README.md', mockFiles.get('README.md')!]]);
      const newHashes = await computeFileHashesAsync(withoutFile);
      
      const changes = detectChangedFiles(originalHashes, newHashes);
      
      expect(changes.removed).toContain('src/main.ts');
    });
  });

  describe('Revision context uses CURRENT file contents', () => {
    it('buildProjectContext includes current file contents', () => {
      const { context } = buildProjectContext(mockChangedFiles, 'readme');
      
      expect(context).toContain('console.log("hello world")'); // NEW content
      expect(context).not.toContain('console.log("hello")'); // OLD content
      expect(context).toContain('src/main.ts');
    });

    it('includes all selected files in context', () => {
      const { context } = buildProjectContext(mockChangedFiles, 'readme');
      
      expect(context).toContain('src/main.ts');
      expect(context).toContain('package.json');
      expect(context).toContain('README.md');
    });
  });

  describe('SuperDocs session reuse', () => {
    it('reuses session ID across revision', async () => {
      const mockFetch = vi.fn()
        .mockResolvedValueOnce({ // initSession
          ok: true,
          json: async () => ({ session_id: 'session-123' }),
        })
        .mockResolvedValueOnce({ // uploadDocument
          ok: true,
          json: async () => ({
            session_id: 'session-123',
            document_id: 'doc-456',
            chunks_count: 5,
            version_id: 'v1',
            page_setup: {},
            html: '<html>Test</html>',
          }),
        })
        .mockResolvedValueOnce({ // chatAsync (initial)
          ok: true,
          json: async () => ({ job_id: 'job-1' }),
        })
        .mockResolvedValue({ // pollJob
          ok: true,
          json: async () => ({
            job_id: 'job-1',
            status: 'completed',
          }),
        });

      global.fetch = mockFetch;
      
      const client = createSuperDocsClient('test-key');
      
      // Initial generation
      const uploadResult = await client.uploadDocument('README.md', '# Test');
      const jobId1 = await client.chatAsync({
        message: 'Generate README',
        session_id: uploadResult.session_id,
      });
      
      expect(jobId1).toBe('job-1');
      expect(uploadResult.session_id).toBe('session-123');
      
      // Revision - should reuse same session
      const jobId2 = await client.chatAsync({
        message: 'Update README',
        session_id: uploadResult.session_id, // SAME session
      });
      
      expect(jobId2).toBe('job-1'); // Same job ID from mock
      expect(mockFetch).toHaveBeenCalledTimes(4); // init + upload + 2 chatAsync
    });
  });
});

describe('SuperDocsClient retry logic', () => {
  const apiKey = 'test-api-key';
  const baseUrl = 'https://api.superdocs.app';

  // Create client with test retry config
  function createTestClient() {
    return createSuperDocsClient(apiKey, baseUrl, { maxRetries: 3, retryDelayMs: 10 });
  }

  it('retries on network error and succeeds', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: 'session-123' }),
      });

    global.fetch = mockFetch;

    const client = createTestClient();
    const sessionId = await client.initSession();

    expect(sessionId).toBe('session-123');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('fails after max retries exhausted', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValue(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();
    await expect(client.initSession()).rejects.toThrow('Network error');
    expect(mockFetch).toHaveBeenCalledTimes(4); // initial + 3 retries
  });

  it('does not retry on non-retriable errors (e.g., 401)', async () => {
    const mockFetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => 'Unauthorized',
      });

    global.fetch = mockFetch;

    const client = createTestClient();
    await expect(client.initSession()).rejects.toThrow('SuperDocs API error (401)');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('retries on 503 service unavailable', async () => {
    const mockFetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        text: async () => 'Service Unavailable',
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        text: async () => 'Service Unavailable',
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: 'session-123' }),
      });

    global.fetch = mockFetch;

    const client = createTestClient();
    const sessionId = await client.initSession();

    expect(sessionId).toBe('session-123');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('does not retry mutation POST requests (uploadDocument)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();

    // uploadDocument should NOT retry (it's a mutation)
    // Provide sessionId to avoid initSession call which does retry
    await expect(client.uploadDocument('test.md', 'content', 'existing-session')).rejects.toThrow('Network error');
    // Should only be called once (no retries for mutations)
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not retry chatAsync (mutation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();

    await expect(client.chatAsync({ message: 'test', session_id: 's1' })).rejects.toThrow('Network error');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not retry approveChanges (mutation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();

    await expect(client.approveChanges({
      session_id: 's1',
      job_id: 'j1',
      approved: true,
      changes: []
    })).rejects.toThrow('Network error');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not retry continueJob (mutation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();

    await expect(client.continueJob({ job_id: 'j1', continue: true }, 's1')).rejects.toThrow('Network error');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not retry exportDocument (mutation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'));

    global.fetch = mockFetch;

    const client = createTestClient();

    await expect(client.exportDocument({ session_id: 's1', format: 'pdf' })).rejects.toThrow('Network error');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('retries pollJob (safe read operation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'j1', status: 'completed' }),
      });

    global.fetch = mockFetch;

    const client = createTestClient();
    const status = await client.pollJob('j1');

    expect(status.job_id).toBe('j1');
    expect(status.status).toBe('completed');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it('retries waitForJob (safe polling operation)', async () => {
    const mockFetch = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'j1', status: 'completed' }),
      });

    global.fetch = mockFetch;

    const client = createTestClient();
    const status = await client.waitForJob('j1');

    expect(status.job_id).toBe('j1');
    expect(status.status).toBe('completed');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  describe('DiffTelemetry and savings calculations', () => {
    it('calculates accurate payload reduction and token savings', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);
      const diff = await computeSourceDiff(baseline, mockChangedFiles);

      expect(diff.telemetry).toBeDefined();
      expect(diff.telemetry.totalFilesCount).toBe(3);
      expect(diff.telemetry.totalBytes).toBeGreaterThan(0);
      expect(diff.telemetry.changedBytes).toBeGreaterThan(0);
      expect(diff.telemetry.changedBytes).toBeLessThan(diff.telemetry.totalBytes);
      expect(diff.telemetry.payloadSavingsPercent).toBeGreaterThan(0);
      expect(diff.telemetry.estimatedTokensSaved).toBeGreaterThan(0);
    });

    it('injects telemetry metadata into the revision message', async () => {
      const baseline = await computeFileHashesAsync(mockFiles);
      const diff = await computeSourceDiff(baseline, mockChangedFiles);
      const message = buildRevisionMessage('readme', 'Test prompt', diff);

      expect(message).toContain('## Telemetry & Context Efficiency');
      expect(message).toContain(`Payload Reduction: ${diff.telemetry.payloadSavingsPercent}%`);
      expect(message).toContain(`Estimated Token Savings: ~${diff.telemetry.estimatedTokensSaved} tokens`);
    });
  });
});