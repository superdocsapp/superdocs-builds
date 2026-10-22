import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { Article, ChangeEvent, GroundTruthEntry } from '../../src/core/types.js';
import fs from 'fs';
import path from 'path';

describe('Deterministic Seeded Evaluation Corpus Benchmark (32 Articles)', () => {
  const fixturesDir = path.resolve(__dirname, '../../fixtures/corpus');
  const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
  const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));
  const groundTruth: GroundTruthEntry[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'ground-truth.json'), 'utf-8'));

  it('runs full 32-article corpus evaluation against ground truth with measured precision and recall', () => {
    expect(articles).toHaveLength(32);
    expect(changes).toHaveLength(5);
    expect(groundTruth).toHaveLength(32);

    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    const { proposals, screenshotAssessments } = sweeper.sweep({ provider: 'deterministic' });

    const metrics = sweeper.getMetrics(groundTruth);

    // Assert honesty & coverage metrics
    expect(metrics.total_articles).toBe(32);
    expect(metrics.actual_cost).toBe(0.00); // 100% free offline execution

    // Print benchmark table for visibility during test run
    console.log('\n================ SEEDED EVALUATION BENCHMARK RESULTS ================');
    console.log(`Corpus Size:               ${metrics.total_articles} articles`);
    console.log(`Affected (Stale):          ${metrics.affected_articles}`);
    console.log(`Unchanged (Healthy):       ${metrics.unchanged_articles}`);
    console.log(`Could Not Assess (Honest): ${metrics.could_not_assess}`);
    console.log(`True Positives (TP):       ${metrics.true_positives}`);
    console.log(`False Positives (FP):      ${metrics.false_positives}`);
    console.log(`False Negatives (FN):      ${metrics.false_negatives}`);
    console.log(`True Negatives (TN):       ${metrics.true_negatives}`);
    console.log(`Precision:                 ${(metrics.precision * 100).toFixed(1)}%`);
    console.log(`Recall:                    ${(metrics.recall * 100).toFixed(1)}%`);
    console.log(`F1 Score:                  ${metrics.f1_score}`);
    console.log(`Portfolio Freshness:       ${metrics.freshness_score}%`);
    console.log(`Assessment Coverage:       ${metrics.assessment_coverage}%`);
    console.log(`Could-Not-Assess Rate:     ${metrics.could_not_assess_rate}%`);
    console.log(`Actual Spend:              $${metrics.actual_cost.toFixed(2)}`);
    console.log(`Proposals Generated:       ${proposals.length}`);
    console.log(`Stale Screenshots Flagged: ${screenshotAssessments.filter(s => s.replacement_required).length}`);
    console.log('=====================================================================\n');

    // High fidelity assertions
    expect(metrics.precision).toBeGreaterThanOrEqual(0.90);
    expect(metrics.recall).toBeGreaterThanOrEqual(0.90);
    expect(metrics.could_not_assess).toBe(6);
    expect(metrics.false_positives).toBe(0); // Zero false positives on adversarial traps
    expect(screenshotAssessments.filter(s => s.replacement_required).length).toBe(3);
  });
});
