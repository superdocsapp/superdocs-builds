import { describe, it, expect } from 'vitest';
import { calculatePortfolioMetrics } from '../../src/core/freshness-score.js';
import { Assessment, GroundTruthEntry } from '../../src/core/types.js';

describe('Precision Calculation (Test 11)', () => {
  it('accurately calculates TP / (TP + FP) precision metric', () => {
    const assessments: Assessment[] = [
      { article_id: 'art-1', change_id: 'c1', status: 'AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' },
      { article_id: 'art-2', change_id: 'c1', status: 'AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' },
      { article_id: 'art-3', change_id: 'c1', status: 'AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' },
      { article_id: 'art-4', change_id: 'c1', status: 'NOT_AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' }
    ];

    const groundTruth: GroundTruthEntry[] = [
      { article_id: 'art-1', expected_status: 'AFFECTED', expected_change_ids: ['c1'], expected_affected_sentences: [1], expected_screenshot_replacement: false, category: 'Test', rationale: '' },
      { article_id: 'art-2', expected_status: 'AFFECTED', expected_change_ids: ['c1'], expected_affected_sentences: [1], expected_screenshot_replacement: false, category: 'Test', rationale: '' },
      { article_id: 'art-3', expected_status: 'NOT_AFFECTED', expected_change_ids: [], expected_affected_sentences: [], expected_screenshot_replacement: false, category: 'Test', rationale: '' }, // FP
      { article_id: 'art-4', expected_status: 'NOT_AFFECTED', expected_change_ids: [], expected_affected_sentences: [], expected_screenshot_replacement: false, category: 'Test', rationale: '' }
    ];

    // TP = 2 (art-1, art-2), FP = 1 (art-3). Precision = 2 / (2 + 1) = 0.667
    const metrics = calculatePortfolioMetrics(4, assessments, groundTruth);
    expect(metrics.true_positives).toBe(2);
    expect(metrics.false_positives).toBe(1);
    expect(metrics.precision).toBe(0.667);
  });
});
