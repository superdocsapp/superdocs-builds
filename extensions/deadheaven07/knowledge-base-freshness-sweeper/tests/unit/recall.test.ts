import { describe, it, expect } from 'vitest';
import { calculatePortfolioMetrics } from '../../src/core/freshness-score.js';
import { Assessment, GroundTruthEntry } from '../../src/core/types.js';

describe('Recall Calculation (Test 12)', () => {
  it('accurately calculates TP / (TP + FN) recall metric', () => {
    const assessments: Assessment[] = [
      { article_id: 'art-1', change_id: 'c1', status: 'AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' },
      { article_id: 'art-2', change_id: 'c1', status: 'NOT_AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' } // FN
    ];

    const groundTruth: GroundTruthEntry[] = [
      { article_id: 'art-1', expected_status: 'AFFECTED', expected_change_ids: ['c1'], expected_affected_sentences: [1], expected_screenshot_replacement: false, category: 'Test', rationale: '' },
      { article_id: 'art-2', expected_status: 'AFFECTED', expected_change_ids: ['c1'], expected_affected_sentences: [1], expected_screenshot_replacement: false, category: 'Test', rationale: '' }
    ];

    // TP = 1 (art-1), FN = 1 (art-2). Recall = 1 / (1 + 1) = 0.500
    const metrics = calculatePortfolioMetrics(2, assessments, groundTruth);
    expect(metrics.true_positives).toBe(1);
    expect(metrics.false_negatives).toBe(1);
    expect(metrics.recall).toBe(0.5);
  });
});
