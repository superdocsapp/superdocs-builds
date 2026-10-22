import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Indirect / Semantic Stale Reference Detection (Test 2)', () => {
  const workflowArticle: Article = {
    id: 'art-export-flow',
    title: 'How to Export Historical Records',
    content: '# Data Operations\n\nTo export historical records, administrators must run export script and download row by row from the server console. This generates discrete CSV summaries.',
    version: 1,
    metadata: { category: 'Data Management' },
    screenshots: [],
    last_updated: '2026-03-15'
  };

  const workflowChange: ChangeEvent = {
    id: 'change-bulk-export',
    type: 'CHANGED_WORKFLOW',
    title: 'One-Click Bulk CSV Export Feature',
    description: 'Manual row-by-row batch export script is replaced with a single Export All CSV button.',
    before_state: {
      workflow_steps: ['run export script', 'download row by row', 'manual batch export'],
      details: 'Users previously had to run export script and download row by row'
    },
    after_state: {
      workflow_steps: ['click Export All CSV button in toolbar'],
      details: 'Direct bulk export via dashboard toolbar'
    },
    effective_date: '2026-08-20',
    source: 'Product Release v4.15'
  };

  it('detects indirect references to deprecated multi-step workflows even when feature name differs', () => {
    const sweeper = new KnowledgeBaseSweeper([workflowArticle], [workflowChange]);
    const { assessments } = sweeper.sweep();

    expect(assessments).toHaveLength(1);
    expect(assessments[0].status).toBe('AFFECTED');
    expect(assessments[0].evidence).toHaveLength(1);
    expect(assessments[0].evidence[0].is_indirect).toBe(true);
    expect(assessments[0].evidence[0].explanation).toContain('Describes legacy workflow steps invalidated');
  });
});
