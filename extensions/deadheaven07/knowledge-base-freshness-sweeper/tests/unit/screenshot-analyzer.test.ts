import { describe, it, expect } from 'vitest';
import { analyzeScreenshots } from '../../src/core/screenshot-analyzer.js';
import { Article, ChangeEvent } from '../../src/core/types.js';

describe('Screenshot / Image Staleness Mismatch Detection (Test 8)', () => {
  const change: ChangeEvent = {
    id: 'change-billing-rename',
    type: 'RENAMED_SCREEN',
    title: 'Billing Screen Rename',
    description: 'Plans renamed to Subscriptions',
    before_state: { ui_label: 'Plans', path: 'Settings > Billing > Plans' },
    after_state: { ui_label: 'Subscriptions', path: 'Settings > Billing > Subscriptions' },
    effective_date: '2026-08-10',
    source: 'UI'
  };

  it('flags SCREENSHOT_REPLACEMENT_REQUIRED when visible OCR labels contain deprecated UI text', () => {
    const article: Article = {
      id: 'art-with-stale-img',
      title: 'Billing Settings',
      content: '# Billing\n\nSee the screenshot below.',
      version: 1,
      metadata: {},
      screenshots: [
        {
          id: 'ss-1',
          url: 'https://example.com/plans.png',
          caption: 'Plans menu screen',
          ocr_labels: ['Settings', 'Billing', 'Plans', 'Save']
        }
      ],
      last_updated: '2026-05-01'
    };

    const results = analyzeScreenshots(article, change);
    expect(results).toHaveLength(1);
    expect(results[0].status).toBe('SCREENSHOT_REPLACEMENT_REQUIRED');
    expect(results[0].replacement_required).toBe(true);
    expect(results[0].mismatched_labels).toContain('Plans');
  });

  it('returns COULD_NOT_ASSESS for screenshots lacking OCR labels and caption', () => {
    const articleUnlabeled: Article = {
      id: 'art-unlabeled-img',
      title: 'Visual Overview',
      content: '# Overview\n\nVisual guide.',
      version: 1,
      metadata: {},
      screenshots: [
        {
          id: 'ss-2',
          url: 'https://example.com/unlabeled.png',
          caption: '',
          ocr_labels: []
        }
      ],
      last_updated: '2026-05-01'
    };

    const results = analyzeScreenshots(articleUnlabeled, change);
    expect(results).toHaveLength(1);
    expect(results[0].status).toBe('COULD_NOT_ASSESS');
    expect(results[0].replacement_required).toBe(false);
  });
});
