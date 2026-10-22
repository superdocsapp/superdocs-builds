import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Honest Could-Not-Assess Behavior (Test 5)', () => {
  const ambiguousArticle: Article = {
    id: 'art-custom-contract',
    title: 'Enterprise Custom Terms',
    content: '# Enterprise Terms\n\nFor enterprise customers, pricing is subject to change based on custom MSA negotiation. Contact sales for tier details.',
    version: 1,
    metadata: { category: 'Enterprise' },
    screenshots: [],
    last_updated: '2026-06-05'
  };

  const planChange: ChangeEvent = {
    id: 'change-legacy-pro',
    type: 'RETIRED_PLAN',
    title: 'Retirement of Legacy Pro Tier',
    description: 'Legacy Pro tier discontinued',
    before_state: { entity_name: 'Legacy Pro' },
    after_state: { entity_name: 'Growth Plan' },
    effective_date: '2026-08-15',
    source: 'Pricing'
  };

  it('classifies ambiguous context into COULD_NOT_ASSESS with explicit reasons and missing evidence', () => {
    const sweeper = new KnowledgeBaseSweeper([ambiguousArticle], [planChange]);
    const { assessments } = sweeper.sweep();

    expect(assessments).toHaveLength(1);
    expect(assessments[0].status).toBe('COULD_NOT_ASSESS');
    expect(assessments[0].confidence).toBe('LOW');
    expect(assessments[0].could_not_assess_details).toBeDefined();
    expect(assessments[0].could_not_assess_details?.what_checked).toContain('Pricing overview terms');
    expect(assessments[0].could_not_assess_details?.missing_evidence).toContain('Exact plan limits or feature tiers are deferred');
  });
});
