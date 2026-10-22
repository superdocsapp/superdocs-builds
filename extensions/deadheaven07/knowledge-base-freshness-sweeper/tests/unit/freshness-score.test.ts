import { describe, it, expect } from 'vitest';
import { calculatePortfolioMetrics } from '../../src/core/freshness-score.js';
import { Assessment } from '../../src/core/types.js';

describe('Portfolio Freshness Score and Coverage (Test 13)', () => {
  it('computes defensible freshness score and coverage without concealing uncertainty', () => {
    // 40 total articles: 27 healthy, 8 affected, 5 could not assess
    const assessments: Assessment[] = [];
    for (let i = 0; i < 27; i++) {
      assessments.push({ article_id: `healthy-${i}`, change_id: 'c1', status: 'NOT_AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' });
    }
    for (let i = 0; i < 8; i++) {
      assessments.push({ article_id: `affected-${i}`, change_id: 'c1', status: 'AFFECTED', confidence: 'HIGH', evidence: [], affected_sections: [], reason: '' });
    }
    for (let i = 0; i < 5; i++) {
      assessments.push({ article_id: `cna-${i}`, change_id: 'c1', status: 'COULD_NOT_ASSESS', confidence: 'LOW', evidence: [], affected_sections: [], reason: '' });
    }

    const metrics = calculatePortfolioMetrics(40, assessments);

    // Assessed = 27 + 8 = 35
    // Freshness = 27 / 35 = 77.1%
    // Coverage = 35 / 40 = 87.5%
    // CNA Rate = 5 / 40 = 12.5%
    expect(metrics.total_articles).toBe(40);
    expect(metrics.unchanged_articles).toBe(27);
    expect(metrics.affected_articles).toBe(8);
    expect(metrics.could_not_assess).toBe(5);
    expect(metrics.freshness_score).toBe(77.1);
    expect(metrics.assessment_coverage).toBe(87.5);
    expect(metrics.could_not_assess_rate).toBe(12.5);
  });
});
