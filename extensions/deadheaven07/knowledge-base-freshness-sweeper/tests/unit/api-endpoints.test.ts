import { describe, it, expect, beforeAll } from 'vitest';
import { createServer } from '../../src/api/server.js';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';
import express from 'express';
import http from 'http';

describe('REST API Endpoints (Test 16)', () => {
  let app: express.Express;
  let server: http.Server;
  let baseUrl: string;
  let sweeper: KnowledgeBaseSweeper;

  const sampleArticle: Article = {
    id: 'api-art-1',
    title: 'API Test Document',
    content: '# Test\nOn the Pro plan, 10,000 API calls per month are permitted.',
    version: 1,
    metadata: {},
    screenshots: [],
    last_updated: '2026-06-01'
  };

  const sampleChange: ChangeEvent = {
    id: 'api-change-1',
    type: 'CHANGED_LIMIT',
    title: 'Pro limit upgrade',
    description: '10,000 to 25,000',
    before_state: { value: 10000 },
    after_state: { value: 25000 },
    effective_date: '2026-08-01',
    source: 'API Test'
  };

  beforeAll(async () => {
    sweeper = new KnowledgeBaseSweeper([sampleArticle], [sampleChange]);
    app = createServer(sweeper);
    await new Promise<void>(resolve => {
      server = app.listen(0, () => {
        const addr = server.address() as { port: number };
        baseUrl = `http://localhost:${addr.port}`;
        resolve();
      });
    });
  });

  it('GET /health returns ok status', async () => {
    const res = await fetch(`${baseUrl}/health`);
    const data = await res.json();
    expect(data.status).toBe('ok');
  });

  it('GET /api/articles returns article list', async () => {
    const res = await fetch(`${baseUrl}/api/articles`);
    const data = await res.json();
    expect(data).toHaveLength(1);
    expect(data[0].id).toBe('api-art-1');
  });

  it('POST /api/sweep executes sweep and returns proposals', async () => {
    const res = await fetch(`${baseUrl}/api/sweep`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    expect(data.assessments).toHaveLength(1);
    expect(data.assessments[0].status).toBe('AFFECTED');
    expect(data.proposals).toHaveLength(1);
  });

  it('POST /api/proposals/:id/approve applies patch and updates freshness', async () => {
    const proposalsRes = await fetch(`${baseUrl}/api/proposals`);
    const proposals = await proposalsRes.json();
    const proposalId = proposals[0].id;

    const approveRes = await fetch(`${baseUrl}/api/proposals/${proposalId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer: 'test-admin', notes: 'Approved via API' })
    });
    const result = await approveRes.json();
    expect(result.success).toBe(true);
    expect(result.proposal.status).toBe('APPROVED');

    // Verify article updated
    const artRes = await fetch(`${baseUrl}/api/articles/api-art-1`);
    const updatedArt = await artRes.json();
    expect(updatedArt.content).toContain('25,000 API calls per month');
    expect(updatedArt.version).toBe(2);
  });
});
