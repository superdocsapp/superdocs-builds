import { describe, it, expect } from 'vitest';
import { KnowledgeBaseDatabase } from '../../src/core/db.js';
import { FreshnessSweeperAgentGraph } from '../../src/core/agent-graph.js';
import { SuperDocsMCPServer } from '../../src/mcp/server.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Durable SQLite Storage, StateGraph Agent-Loop & MCP Server', () => {
  const sampleArticle: Article = {
    id: 'art-test-01',
    title: 'API Limits Guide',
    content: '# API Limits\nThe Pro plan includes 10,000 API calls per month.\n\n## Summary\nEnjoy high performance.',
    version: 1,
    metadata: { category: 'Billing' },
    screenshots: [],
    last_updated: '2026-08-27T00:00:00Z'
  };

  const sampleChange: ChangeEvent = {
    id: 'change-test-01',
    type: 'CHANGED_LIMIT',
    title: 'Pro Plan Quota Increase to 25,000',
    description: 'Updated rate limit for Pro tier from 10,000 to 25,000 API calls per month.',
    before_state: { value: 10000 },
    after_state: { value: 25000 },
    effective_date: '2026-08-27',
    source: 'Release Notes v2.4'
  };

  it('persists articles, proposals, and audit logs into durable SQLite', () => {
    const db = new KnowledgeBaseDatabase(':memory:');
    db.saveArticle(sampleArticle);

    const loadedArticles = db.getArticles();
    expect(loadedArticles).toHaveLength(1);
    expect(loadedArticles[0].id).toBe('art-test-01');

    db.saveProposal({
      id: 'prop-test-01',
      article_id: 'art-test-01',
      change_id: 'change-test-01',
      original_content: sampleArticle.content,
      proposed_content: sampleArticle.content.replace('10,000', '25,000'),
      changed_spans: [{
        start_char: 35,
        end_char: 41,
        original_text: '10,000',
        replacement_text: '25,000',
        sentence_index: 0
      }],
      rationale: 'Updated limit',
      evidence: [],
      confidence: 'HIGH',
      status: 'PENDING',
      created_at: new Date().toISOString(),
      structural_preservation_ratio: 0.99
    });

    const pending = db.getProposals('PENDING');
    expect(pending).toHaveLength(1);

    db.recordReviewDecision({
      proposal_id: 'prop-test-01',
      decision: 'APPROVED',
      reviewer: 'lead_maintainer',
      notes: 'Verified against release notes v2.4',
      timestamp: new Date().toISOString()
    });

    const updated = db.getProposals('APPROVED');
    expect(updated).toHaveLength(1);
    expect(updated[0].reviewer).toBe('lead_maintainer');
    db.close();
  });

  it('runs StateGraph workflow, interrupts at Human Gate, and resumes upon approval', async () => {
    const db = new KnowledgeBaseDatabase(':memory:');
    const graph = new FreshnessSweeperAgentGraph(db);
    const threadId = 'thread-live-001';

    // 1. Start execution
    const state1 = await graph.start(threadId, [sampleArticle], [sampleChange]);

    expect(state1.status).toBe('INTERRUPTED_AT_HUMAN_GATE');
    expect(state1.current_node).toBe('HUMAN_GATE_INTERRUPT');
    expect(state1.proposals).toHaveLength(1);

    // Verify checkpoint is stored in SQLite
    const checkpoint = db.getCheckpoint(threadId);
    expect(checkpoint).not.toBeNull();
    expect(checkpoint?.is_interrupted).toBe(true);

    // 2. Resume graph with human decision
    const state2 = await graph.resume(threadId, [{
      proposal_id: state1.proposals[0].id,
      decision: 'APPROVED',
      reviewer: 'knowledge_architect',
      timestamp: new Date().toISOString(),
      notes: 'Approved surgical edit'
    }]);

    expect(state2.status).toBe('COMPLETED');
    expect(state2.current_node).toBe('COMPLETED');
    expect(state2.applied_articles[0].content).toContain('25,000 API calls per month');
    expect(state2.applied_articles[0].version).toBe(2);

    db.close();
  });

  it('exposes MCP server tools for external AI agent orchestration', async () => {
    const db = new KnowledgeBaseDatabase(':memory:');
    const mcpServer = new SuperDocsMCPServer(db);

    const tools = mcpServer.getTools();
    expect(tools.map(t => t.name)).toContain('sweep_knowledge_base');
    expect(tools.map(t => t.name)).toContain('list_pending_proposals');
    expect(tools.map(t => t.name)).toContain('submit_review_decision');
    expect(tools.map(t => t.name)).toContain('get_portfolio_freshness');

    // Agent executes sweep via MCP
    const sweepRes = await mcpServer.callTool({
      name: 'sweep_knowledge_base',
      arguments: {
        thread_id: 'mcp-thread-99',
        articles: [sampleArticle],
        changes: [sampleChange]
      }
    });

    expect(sweepRes.isError).toBeFalsy();
    const sweepOutput = JSON.parse(sweepRes.content[0].text);
    expect(sweepOutput.status).toBe('INTERRUPTED_AT_HUMAN_GATE');

    // Agent lists pending proposals
    const listRes = await mcpServer.callTool({
      name: 'list_pending_proposals',
      arguments: {}
    });
    const pendingList = JSON.parse(listRes.content[0].text);
    expect(pendingList).toHaveLength(1);

    // Agent submits review decision via MCP
    const reviewRes = await mcpServer.callTool({
      name: 'submit_review_decision',
      arguments: {
        thread_id: 'mcp-thread-99',
        proposal_id: pendingList[0].id,
        decision: 'APPROVED',
        reviewer: 'autonomous_evaluator_agent',
        notes: 'Autonomous signoff based on ground-truth telemetry'
      }
    });

    const resumeOutput = JSON.parse(reviewRes.content[0].text);
    expect(resumeOutput.status).toBe('COMPLETED');

    db.close();
  });
});
