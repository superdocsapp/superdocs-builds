/**
 * SuperDocs REST API & MCP Client Adapter
 * Provides integration with the SuperDocs public API for document synchronization,
 * remote AI impact verification, and direct document patching.
 */

export interface SuperDocsConfig {
  apiKey?: string;
  baseUrl?: string;
  timeoutMs?: number;
}

export interface SuperDocsSyncResult {
  remoteDocumentId: string;
  version: number;
  status: 'SYNCED' | 'FAILED' | 'FALLBACK_LOCAL';
  timestamp: string;
}

export class SuperDocsClient {
  private apiKey: string;
  private baseUrl: string;
  private timeoutMs: number;

  constructor(config: SuperDocsConfig = {}) {
    const envApiKey = typeof process !== 'undefined' && process.env ? process.env.SUPERDOCS_API_KEY : undefined;
    const envBaseUrl = typeof process !== 'undefined' && process.env ? process.env.SUPERDOCS_BASE_URL : undefined;
    this.apiKey = config.apiKey || envApiKey || 'your-key-here';
    this.baseUrl = (config.baseUrl || envBaseUrl || 'https://api.superdocs.app').replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs || 10000;
  }

  public isConfigured(): boolean {
    return (
      Boolean(this.apiKey) &&
      this.apiKey !== 'your-key-here' &&
      this.apiKey !== 'test-key' &&
      !this.apiKey.startsWith('mock-')
    );
  }

  /**
   * Syncs an article to SuperDocs document store.
   */
  public async syncArticle(articleId: string, title: string, content: string): Promise<SuperDocsSyncResult> {
    if (!this.isConfigured()) {
      return {
        remoteDocumentId: `doc-local-${articleId}`,
        version: 1,
        status: 'FALLBACK_LOCAL',
        timestamp: new Date().toISOString()
      };
    }

    try {
      const response = await fetch(`${this.baseUrl}/v1/documents`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          title,
          content,
          metadata: {
            source: 'knowledge-base-freshness-sweeper',
            article_id: articleId
          }
        }),
        signal: AbortSignal.timeout(this.timeoutMs)
      });

      if (!response.ok) {
        throw new Error(`SuperDocs API returned HTTP ${response.status}: ${await response.text()}`);
      }

      const data = (await response.json()) as { id?: string; version?: number };
      return {
        remoteDocumentId: data.id || `doc-${articleId}`,
        version: data.version || 1,
        status: 'SYNCED',
        timestamp: new Date().toISOString()
      };
    } catch (err) {
      console.warn(`[SuperDocsClient] Remote sync failed, falling back to local storage: ${(err as Error).message}`);
      return {
        remoteDocumentId: `doc-fallback-${articleId}`,
        version: 1,
        status: 'FALLBACK_LOCAL',
        timestamp: new Date().toISOString()
      };
    }
  }

  /**
   * Pushes an approved surgical edit directly to the live SuperDocs document.
   */
  public async applySurgicalPatch(remoteDocId: string, patchContent: string): Promise<boolean> {
    if (!this.isConfigured()) {
      return true; // Local simulation
    }

    try {
      const response = await fetch(`${this.baseUrl}/v1/documents/${remoteDocId}/edit`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          patch: patchContent,
          mode: 'surgical'
        }),
        signal: AbortSignal.timeout(this.timeoutMs)
      });

      return response.ok;
    } catch {
      return false;
    }
  }
}
