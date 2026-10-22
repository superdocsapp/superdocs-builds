import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createSuperDocsClient, SuperDocsClient } from '../src/services/superdocs';
import { computeFileHashesAsync } from '../src/utils/hash';
import { planRegeneration, buildRevisionMessage } from '../src/services/revision';

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('Zero-drift fidelity (regeneration from source)', () => {
  // ---------------------------------------------------------------------
  // Verification method
  // ---------------------------------------------------------------------
  // "Zero drift" means: when the workspace file hashes stored in
  // `.superdocs-state.json` are identical to the hashes of the current file
  // contents, the regeneration pipeline MUST produce an empty change set
  // and MUST NOT create a chat job. A regeneration job is only created from
  // `planRegeneration(...).message`, so `message === undefined` proves the
  // proposed-changes list is empty without touching the network.
  //
  // Tail behavior: on zero drift the hook short-circuits BEFORE `chatAsync`
  // and returns `{ hasChanges: false, changes: [] }`; the UI shows
  // "No source changes detected" and previously approved document sections
  // are preserved because unchanged source files are never re-sent.
  // ---------------------------------------------------------------------
  const files = new Map([
    ['src/main.ts', 'export function main() { console.log("hello"); }'],
    ['package.json', '{"name": "test", "version": "1.0.0"}'],
  ]);

  it('identical hashes => zero proposed changes and no chat job created', async () => {
    const baseline = await computeFileHashesAsync(files);

    const plan = await planRegeneration(baseline, files, 'readme', 'Original instruction');

    expect(plan.hasChanges).toBe(false);
    expect(plan.diff.changed).toHaveLength(0);
    expect(plan.diff.added).toHaveLength(0);
    expect(plan.diff.removed).toHaveLength(0);
    expect(plan.message).toBeUndefined();

    // The chat job is created only from `plan.message`, so with no message
    // there can be no pending_changes and the proposed-changes array is
    // provably length 0.
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('proposed changes are non-empty ONLY when drift exists', async () => {
    const baseline = await computeFileHashesAsync(files);

    const changedFiles = new Map(files);
    changedFiles.set('src/main.ts', 'export function main() { console.log("hello world"); }');

    const plan = await planRegeneration(baseline, changedFiles, 'readme', 'Original instruction');

    expect(plan.hasChanges).toBe(true);
    expect(plan.diff.changed.map(f => f.path)).toEqual(['src/main.ts']);
    expect(plan.message).toBeDefined();
    expect(plan.message).toContain('console.log("hello world")');
    expect(plan.message).not.toContain('console.log("hello")');
  });

  it('byte-identical output stability: repeated builds of the same diff produce identical instructions', async () => {
    const baseline = await computeFileHashesAsync(files);

    const changedFiles = new Map(files);
    changedFiles.set('src/main.ts', 'export function main() { console.log("hello world"); }');

    const plan = await planRegeneration(baseline, changedFiles, 'readme', 'Original instruction');
    const rebuilt = buildRevisionMessage('readme', 'Original instruction', plan.diff);

    expect(plan.message).toBe(rebuilt);

    // Repeated invocations are also deterministic (no timestamps, no
    // randomness, sorted paths) - a regression here would break the
    // regeneration review loop's stability guarantees.
    const again = await planRegeneration(baseline, changedFiles, 'readme', 'Original instruction');
    expect(again.message).toBe(plan.message);
  });
});

describe('SuperDocsClient', () => {
  let client: SuperDocsClient;
  const apiKey = 'test-api-key';
  const baseUrl = 'https://api.superdocs.app';

  beforeEach(() => {
    vi.clearAllMocks();
    client = createSuperDocsClient(apiKey, baseUrl);
  });

  describe('initSession', () => {
    it('calls correct endpoint and returns session_id', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: 'session-123' }),
      });

      const sessionId = await client.initSession();
      
      expect(sessionId).toBe('session-123');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/sessions/init',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
          }),
        })
      );
    });

    it('throws on API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => 'Unauthorized',
      });

      await expect(client.initSession()).rejects.toThrow('SuperDocs API error (401)');
    });
  });

  describe('uploadDocument', () => {
    it('uploads document and returns result', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ session_id: 'session-123' }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            session_id: 'session-123',
            document_id: 'doc-456',
            chunks_count: 5,
            version_id: 'v1',
            page_setup: {},
            html: '<html>Test</html>',
          }),
        });

      const result = await client.uploadDocument('test.md', '# Test Content');
      
      expect(result.session_id).toBe('session-123');
      expect(result.document_id).toBe('doc-456');
      expect(result.chunks_count).toBe(5);
      expect(result.html).toBe('<html>Test</html>');
    });
  });

  describe('chatAsync', () => {
    it('starts chat job and returns job_id', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job-789' }),
      });

      const jobId = await client.chatAsync({
        message: 'Test instruction',
        session_id: 'session-123',
      });

      expect(jobId).toBe('job-789');
    });
  });

  describe('pollJob', () => {
    it('returns job status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-789',
          status: 'processing',
        }),
      });

      const status = await client.pollJob('job-789');
      
      expect(status.job_id).toBe('job-789');
      expect(status.status).toBe('processing');
    });
  });

  describe('approveChanges', () => {
    it('approves changes and returns job status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-789',
          status: 'completed',
        }),
      });

      const status = await client.approveChanges({
        session_id: 'session-123',
        job_id: 'job-789',
        approved: true,
        changes: [{ change_id: 'ch-1', operation: 'replace', ai_explanation: 'Test explanation' }],
      });

      expect(status.job_id).toBe('job-789');
      expect(status.status).toBe('completed');
    });
  });

  describe('continueJob', () => {
    it('continues job and returns status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-789',
          status: 'completed',
        }),
      });

      const status = await client.continueJob(
        { job_id: 'job-789', continue: true },
        'session-123'
      );

      expect(status.job_id).toBe('job-789');
      expect(status.status).toBe('completed');
    });
  });

  describe('exportDocument', () => {
    it('exports document and returns result', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          download_url: 'https://example.com/download.pdf',
          filename: 'export.pdf',
          format: 'pdf',
        }),
      });

      const result = await client.exportDocument({
        session_id: 'session-123',
        format: 'pdf',
      });

      expect(result.download_url).toBe('https://example.com/download.pdf');
      expect(result.format).toBe('pdf');
    });
  });

  describe('downloadExport', () => {
    it('downloads export blob', async () => {
      const mockBlob = new Blob(['test content'], { type: 'application/pdf' });
      mockFetch.mockResolvedValueOnce({
        ok: true,
        blob: async () => mockBlob,
      });

      const blob = await client.downloadExport('https://example.com/download.pdf');
      
      expect(blob).toBeInstanceOf(Blob);
      expect(blob.size).toBeGreaterThan(0);
    });
  });

  describe('error handling', () => {
    it('includes status code in error message', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        text: async () => 'Internal Server Error',
      });

      await expect(client.initSession()).rejects.toThrow('SuperDocs API error (500)');
    });
  });

  describe('syncHtml', () => {
    it('posts html to sync endpoint and returns response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          document_id: 'doc-456',
          version_id: 'v2',
        }),
      });

      const result = await client.syncHtml({
        session_id: 'session-123',
        document_id: 'doc-456',
        html: '<html>Updated</html>',
      });

      expect(result.success).toBe(true);
      expect(result.version_id).toBe('v2');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/documents/sync-html',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            session_id: 'session-123',
            document_id: 'doc-456',
            html: '<html>Updated</html>',
          }),
        })
      );
    });

    it('throws on API error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        text: async () => 'Bad Request',
      });

      await expect(
        client.syncHtml({ session_id: 'session-123', document_id: 'doc-456', html: '<html></html>' })
      ).rejects.toThrow('SuperDocs API error (400)');
    });
  });

  describe('getVersions', () => {
    it('fetches version history for a document', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          versions: [
            {
              version_id: 'v1',
              document_id: 'doc-456',
              created_at: '2026-08-16T10:00:00Z',
              created_by: 'user-1',
              html: '<html>v1</html>',
              change_summary: 'Initial version',
              is_current: false,
            },
          ],
        }),
      });

      const result = await client.getVersions('doc-456');

      expect(result.versions).toHaveLength(1);
      expect(result.versions[0].change_summary).toBe('Initial version');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/documents/doc-456/versions',
        expect.any(Object)
      );
    });
  });

  describe('getDocumentVersion', () => {
    it('fetches a single document version', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          version_id: 'v2',
          document_id: 'doc-456',
          created_at: '2026-08-16T11:00:00Z',
          created_by: 'user-1',
          html: '<html>v2</html>',
          change_summary: 'Updated',
          is_current: true,
        }),
      });

      const version = await client.getDocumentVersion('doc-456', 'v2');

      expect(version.version_id).toBe('v2');
      expect(version.is_current).toBe(true);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/documents/doc-456/versions/v2',
        expect.any(Object)
      );
    });
  });

  describe('revertToVersion', () => {
    it('posts revert and returns job status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ job_id: 'job-revert-1', status: 'completed' }),
      });

      const status = await client.revertToVersion('doc-456', 'v1');

      expect(status.status).toBe('completed');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/documents/doc-456/versions/v1/revert',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  describe('getTemplates', () => {
    it('fetches the template gallery', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          templates: [
            {
              id: 'tpl-1',
              name: 'README',
              description: 'Project readme',
              document_type: 'readme',
              variables: [{ name: 'repo_name', description: 'Repo name', required: true }],
              default_content: '# {{repo_name}}',
            },
          ],
        }),
      });

      const result = await client.getTemplates();

      expect(result.templates).toHaveLength(1);
      expect(result.templates[0].document_type).toBe('readme');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/templates',
        expect.any(Object)
      );
    });
  });

  describe('getPrompts', () => {
    it('fetches the prompt library', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          prompts: [
            {
              id: 'pr-1',
              name: 'Explain architecture',
              description: 'Explain project architecture',
              template: 'Explain the architecture of {{repo_name}}',
              variables: [{ name: 'repo_name', description: 'Repo name', required: true }],
            },
          ],
        }),
      });

      const result = await client.getPrompts();

      expect(result.prompts).toHaveLength(1);
      expect(result.prompts[0].template).toContain('{{repo_name}}');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/prompts',
        expect.any(Object)
      );
    });
  });

  describe('getPrompt', () => {
    it('fetches a single prompt by id', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'pr-1',
          name: 'Explain architecture',
          description: 'Explain project architecture',
          template: 'Explain the architecture of {{repo_name}}',
          variables: [],
        }),
      });

      const prompt = await client.getPrompt('pr-1');

      expect(prompt.id).toBe('pr-1');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.superdocs.app/v1/prompts/pr-1',
        expect.any(Object)
      );
    });
  });
});