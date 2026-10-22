import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Unchanged Article Correctly Left Untouched (Test 3)', () => {
  const article: Article = {
    id: 'art-shortcuts',
    title: 'Markdown Keyboard Shortcuts',
    content: '# Keyboard Shortcuts\n\nSpeed up editing with standard keybindings. Press Cmd+B for bold, Cmd+I for italics, and Cmd+K to insert hyperlinks.',
    version: 1,
    metadata: { category: 'Editor' },
    screenshots: [],
    last_updated: '2026-07-01'
  };

  const change: ChangeEvent = {
    id: 'change-billing',
    type: 'RENAMED_SCREEN',
    title: 'Billing Screen Rename',
    description: 'Plans renamed to Subscriptions',
    before_state: { ui_label: 'Plans' },
    after_state: { ui_label: 'Subscriptions' },
    effective_date: '2026-08-10',
    source: 'UI Refactor'
  };

  it('correctly marks unrelated article as NOT_AFFECTED without generating proposals', () => {
    const sweeper = new KnowledgeBaseSweeper([article], [change]);
    const { assessments, proposals } = sweeper.sweep();

    expect(assessments).toHaveLength(1);
    expect(assessments[0].status).toBe('NOT_AFFECTED');
    expect(assessments[0].confidence).toBe('HIGH');
    expect(assessments[0].evidence).toHaveLength(0);
    expect(proposals).toHaveLength(0);
  });
});
