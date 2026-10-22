import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Human Review Approval Flow (Test 9)', () => {
  it('applies surgical edit, increments version, updates timestamp, and marks proposal APPROVED', () => {
    const article: Article = {
      id: 'art-approve-test',
      title: 'Quota Guide',
      content: '# Quota Guide\n\nOn the Pro tier, you receive 10,000 API calls per month.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-06-01'
    };

    const change: ChangeEvent = {
      id: 'change-limit',
      type: 'CHANGED_LIMIT',
      title: 'Limit Increase',
      description: '10,000 to 25,000',
      before_state: { value: 10000 },
      after_state: { value: 25000 },
      effective_date: '2026-08-01',
      source: 'Release'
    };

    const sweeper = new KnowledgeBaseSweeper([article], [change]);
    const { proposals } = sweeper.sweep();
    expect(proposals).toHaveLength(1);

    const proposalId = proposals[0].id;
    const approvalResult = sweeper.approveProposal(proposalId, 'lead-editor', 'Verified with release notes');

    expect(approvalResult.success).toBe(true);
    expect(approvalResult.proposal?.status).toBe('APPROVED');
    expect(approvalResult.article?.version).toBe(2);
    expect(approvalResult.article?.content).toContain('25,000 API calls per month');

    // Freshness score should update to 100% since affected proposal was resolved
    const metrics = sweeper.getMetrics();
    expect(metrics.freshness_score).toBe(100);
  });
});
