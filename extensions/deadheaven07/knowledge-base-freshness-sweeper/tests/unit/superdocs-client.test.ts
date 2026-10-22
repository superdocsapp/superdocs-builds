import { describe, it, expect, vi, afterEach } from 'vitest';
import { SuperDocsClient } from '../../src/core/superdocs-client.js';

describe('SuperDocs API Client Adapter (Integration, Mock Wire & Fallback)', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('identifies unconfigured state when SUPERDOCS_API_KEY is unset/placeholder and falls back gracefully', async () => {
    const client = new SuperDocsClient({ apiKey: 'your-key-here' });
    expect(client.isConfigured()).toBe(false);

    const result = await client.syncArticle('art-100', 'Title', '# Content');
    expect(result.status).toBe('FALLBACK_LOCAL');
    expect(result.remoteDocumentId).toBe('doc-local-art-100');
  });

  it('recognizes configured state when a valid API key is passed', () => {
    const client = new SuperDocsClient({ apiKey: 'live_sk_test_12345' });
    expect(client.isConfigured()).toBe(true);
  });

  it('performs wire-level HTTP POST with auth headers and handles success response', async () => {
    const mockResponse = { id: 'doc-remote-999', version: 2 };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
      text: async () => JSON.stringify(mockResponse)
    } as any);

    const client = new SuperDocsClient({
      apiKey: 'live_sk_test_valid',
      baseUrl: 'https://api.superdocs.app'
    });

    const result = await client.syncArticle('art-001', 'API Rate Limits', '# Content');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'https://api.superdocs.app/v1/documents',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Authorization': 'Bearer live_sk_test_valid',
          'Content-Type': 'application/json'
        })
      })
    );
    expect(result.status).toBe('SYNCED');
    expect(result.remoteDocumentId).toBe('doc-remote-999');
    expect(result.version).toBe(2);
  });

  it('gracefully degrades to FALLBACK_LOCAL on HTTP 500 or network timeout without crashing', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'Internal Server Error'
    } as any);

    const client = new SuperDocsClient({
      apiKey: 'live_sk_test_valid',
      baseUrl: 'https://api.superdocs.app'
    });

    const result = await client.syncArticle('art-002', 'Storage Limits', '# Content');
    expect(result.status).toBe('FALLBACK_LOCAL');
    expect(result.remoteDocumentId).toBe('doc-fallback-art-002');
  });
});
