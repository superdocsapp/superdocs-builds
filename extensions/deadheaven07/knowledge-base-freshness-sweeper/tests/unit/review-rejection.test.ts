import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Human Review Rejection Flow (Test 10)', () => {
  it('leaves original article content untouched and marks proposal REJECTED with notes', () => {
    const originalContent = '# Quota Guide\n\nOn the Pro tier, you receive 10,000 API calls per month.';
    const article: Article = {
      id: 'art-reject-test',
      title: 'Quota Guide',
      content: originalContent,
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
    const proposalId = proposals[0].id;

    const rejectionResult = sweeper.rejectProposal(proposalId, 'compliance-reviewer', 'Legacy contract exception applies');

    expect(rejectionResult.success).toBe(true);
    expect(rejectionResult.proposal?.status).toBe('REJECTED');
    expect(rejectionResult.proposal?.review_notes).toBe('Legacy contract exception applies');

    // Article content should be untouched
    const currentArticle = sweeper.getArticle(article.id);
    expect(currentArticle?.content).toBe(originalContent);
    expect(currentArticle?.version).toBe(1);
  });
});
