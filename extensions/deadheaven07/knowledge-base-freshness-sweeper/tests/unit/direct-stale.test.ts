import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Direct Stale Article Detection (Test 1)', () => {
  const article: Article = {
    id: 'art-api-limit',
    title: 'API Rate Limits',
    content: '# Quota Guide\n\nOn the Pro tier, you receive 10,000 API calls per month. Throttling triggers beyond this.',
    version: 1,
    metadata: { category: 'API' },
    screenshots: [],
    last_updated: '2026-06-01'
  };

  const change: ChangeEvent = {
    id: 'change-limit-up',
    type: 'CHANGED_LIMIT',
    title: 'Pro API Rate Limit Increase',
    description: 'Pro tier limit increased from 10,000 to 25,000 requests per month.',
    before_state: { entity_name: 'Pro tier', value: 10000 },
    after_state: { entity_name: 'Pro tier', value: 25000 },
    effective_date: '2026-08-01',
    source: 'Release Notes'
  };

  it('detects direct limit change and flags article as AFFECTED with HIGH confidence', () => {
    const sweeper = new KnowledgeBaseSweeper([article], [change]);
    const { assessments, proposals } = sweeper.sweep();

    expect(assessments).toHaveLength(1);
    expect(assessments[0].status).toBe('AFFECTED');
    expect(assessments[0].confidence).toBe('HIGH');
    expect(assessments[0].evidence).toHaveLength(1);
    expect(assessments[0].evidence[0].sentence_text).toContain('10,000 API calls per month');
    expect(proposals).toHaveLength(1);
    expect(proposals[0].proposed_content).toContain('25,000 API calls per month');
  });

  it('detects renamed UI navigation path directly', () => {
    const uiArticle: Article = {
      id: 'art-ui-path',
      title: 'Updating Billing',
      content: '# Billing Info\n\nTo update cards, visit Settings > Billing > Plans. Receipts are mailed monthly.',
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-05-01'
    };

    const uiChange: ChangeEvent = {
      id: 'change-rename-tab',
      type: 'RENAMED_SCREEN',
      title: 'Rename Plans tab',
      description: 'Plans tab in Billing is now Subscriptions',
      before_state: { ui_label: 'Plans', path: 'Settings > Billing > Plans' },
      after_state: { ui_label: 'Subscriptions', path: 'Settings > Billing > Subscriptions' },
      effective_date: '2026-08-10',
      source: 'UI Refactor'
    };

    const sweeper = new KnowledgeBaseSweeper([uiArticle], [uiChange]);
    const { assessments } = sweeper.sweep();

    expect(assessments[0].status).toBe('AFFECTED');
    expect(assessments[0].evidence[0].sentence_text).toContain('Settings > Billing > Plans');
  });
});
