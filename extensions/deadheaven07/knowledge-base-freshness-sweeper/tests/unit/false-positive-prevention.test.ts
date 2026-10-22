import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('False-Positive Prevention (Test 4)', () => {
  it('does not flag articles mentioning business "growth" when Growth Plan is retired/introduced', () => {
    const article: Article = {
      id: 'art-growth-strategy',
      title: 'Accelerating Team Revenue Growth',
      content: '# Growth Strategy\n\nDriving sustained growth requires cross-functional alignment. Focus on user onboarding metrics.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-07-22'
    };

    const change: ChangeEvent = {
      id: 'change-retired-tier',
      type: 'RETIRED_PLAN',
      title: 'Growth Plan Migration',
      description: 'Legacy Pro tier migrated to Growth Plan',
      before_state: { entity_name: 'Legacy Pro' },
      after_state: { entity_name: 'Growth Plan' },
      effective_date: '2026-08-15',
      source: 'Pricing'
    };

    const sweeper = new KnowledgeBaseSweeper([article], [change]);
    const { assessments } = sweeper.sweep();

    expect(assessments[0].status).toBe('NOT_AFFECTED');
  });

  it('does not flag articles mentioning client "browser memory limits" when API rate limit changes', () => {
    const article: Article = {
      id: 'art-browser-limits',
      title: 'Browser Memory Considerations',
      content: '# Browser Limits\n\nWhen editing huge documents, client memory limit constraints in Chrome may impact responsiveness.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-07-25'
    };

    const change: ChangeEvent = {
      id: 'change-api-limits',
      type: 'CHANGED_LIMIT',
      title: 'API Rate Limits Changed',
      description: 'API rate limits increased from 10,000 to 25,000',
      before_state: { value: 10000 },
      after_state: { value: 25000 },
      effective_date: '2026-08-01',
      source: 'API'
    };

    const sweeper = new KnowledgeBaseSweeper([article], [change]);
    const { assessments } = sweeper.sweep();

    expect(assessments[0].status).toBe('NOT_AFFECTED');
  });
});
