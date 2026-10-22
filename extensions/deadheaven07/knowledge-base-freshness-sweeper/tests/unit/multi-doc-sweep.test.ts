import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Multi-Document Sweep Engine (Test 17)', () => {
  const articles: Article[] = [
    {
      id: 'art-multi-1',
      title: 'API Limits',
      content: '# Limits\nOn Pro tier, 10,000 API calls per month.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-06-01'
    },
    {
      id: 'art-multi-2',
      title: 'Billing Navigation',
      content: '# Billing\nGo to Settings > Billing > Plans to upgrade.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-06-01'
    },
    {
      id: 'art-multi-3',
      title: 'Shortcuts',
      content: '# Shortcuts\nCmd+B is bold.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-06-01'
    }
  ];

  const changes: ChangeEvent[] = [
    {
      id: 'c-limit',
      type: 'CHANGED_LIMIT',
      title: 'Limit Increase',
      description: '10,000 to 25,000',
      before_state: { value: 10000 },
      after_state: { value: 25000 },
      effective_date: '2026-08-01',
      source: 'Notes'
    },
    {
      id: 'c-rename',
      type: 'RENAMED_SCREEN',
      title: 'Plans Rename',
      description: 'Plans to Subscriptions',
      before_state: { ui_label: 'Plans', path: 'Settings > Billing > Plans' },
      after_state: { ui_label: 'Subscriptions', path: 'Settings > Billing > Subscriptions' },
      effective_date: '2026-08-10',
      source: 'UI'
    }
  ];

  it('evaluates multiple articles across multiple change events in batch', () => {
    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    const { assessments, proposals, metrics } = sweeper.sweep();

    expect(assessments).toHaveLength(3);
    expect(proposals).toHaveLength(2);

    const affected = assessments.filter(a => a.status === 'AFFECTED');
    const unchanged = assessments.filter(a => a.status === 'NOT_AFFECTED');

    expect(affected).toHaveLength(2);
    expect(unchanged).toHaveLength(1);
    expect(metrics.freshness_score).toBe(33.3); // 1 / 3 = 33.3%
  });
});
