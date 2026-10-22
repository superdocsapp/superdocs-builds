import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Small-Sample Mode Execution (Test 15)', () => {
  const articles: Article[] = [];
  for (let i = 0; i < 20; i++) {
    articles.push({
      id: `art-${i}`,
      title: `Article ${i}`,
      content: `# Article ${i}\nOn the Pro tier, limit is 10,000 API calls per month.`,
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-06-01'
    });
  }

  const change: ChangeEvent = {
    id: 'c1',
    type: 'CHANGED_LIMIT',
    title: 'Limit update',
    description: '10,000 to 25,000',
    before_state: { value: 10000 },
    after_state: { value: 25000 },
    effective_date: '2026-08-01',
    source: 'Notes'
  };

  it('limits processing strictly to sample_size when --sample is passed', () => {
    const sweeper = new KnowledgeBaseSweeper(articles, [change]);
    const { assessments } = sweeper.sweep({ sample_size: 5 });

    expect(assessments).toHaveLength(5);
  });
});
