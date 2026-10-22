import { describe, it, expect } from 'vitest';
import { KnowledgeBaseSweeper } from '../../src/core/engine.js';
import { NaiveKeywordControlArm } from '../../src/core/control-arm.js';
import { CorpusDriftSimulator } from '../../src/core/drift-simulator.js';
import { loadGroundTruthFromYaml, loadExpectedYaml } from '../../src/core/yaml-loader.js';
import { Article, ChangeEvent } from '../../src/core/types.js';
import fs from 'fs';
import path from 'path';

describe('Rigorous Pre-Registered YAML Evaluation & Control Arm Benchmark', () => {
  const fixturesDir = path.resolve(__dirname, '../../fixtures/corpus');
  const yamlPath = path.join(fixturesDir, 'expected.yaml');
  const articles: Article[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'articles.json'), 'utf-8'));
  const changes: ChangeEvent[] = JSON.parse(fs.readFileSync(path.join(fixturesDir, 'changes.json'), 'utf-8'));
  const groundTruth = loadGroundTruthFromYaml(yamlPath);
  const expectedStructure = loadExpectedYaml(yamlPath);

  it('validates pre-registered expected.yaml ground truth integrity before execution', () => {
    expect(expectedStructure.version).toBe('1.0.0');
    expect(expectedStructure.protocol).toBe('PRE_REGISTERED_EVALUATION');
    expect(groundTruth).toHaveLength(32);
    expect(expectedStructure.summary_expectations.affected_articles).toBe(15);
    expect(expectedStructure.summary_expectations.unchanged_articles).toBe(11);
    expect(expectedStructure.summary_expectations.could_not_assess_articles).toBe(6);
    expect(expectedStructure.summary_expectations.screenshots_requiring_replacement).toBe(3);
  });

  it('proves multi-stage sweeper strictly outperforms naive keyword control arm on baseline', () => {
    const sweeper = new KnowledgeBaseSweeper(articles, changes);
    sweeper.sweep({ provider: 'deterministic' });
    const sweeperMetrics = sweeper.getMetrics(groundTruth);

    const controlArm = new NaiveKeywordControlArm(articles, changes);
    const controlMetrics = controlArm.evaluate(groundTruth);

    // Multi-stage sweeper achieves high precision & recall with 0 false positives
    expect(sweeperMetrics.precision).toBe(1.0);
    expect(sweeperMetrics.recall).toBe(1.0);
    expect(sweeperMetrics.false_positives).toBe(0);
    expect(sweeperMetrics.could_not_assess).toBe(6);

    // Naive control arm produces false positives on adversarial traps (e.g., 'growth', 'limit', 'subscribe')
    expect(controlMetrics.false_positives).toBeGreaterThan(0);
    expect(controlMetrics.could_not_assess).toBe(0); // Naive baseline has no honest bucket
    expect(sweeperMetrics.precision).toBeGreaterThan(controlMetrics.precision);
  });

  it('runs 10 independent drift epochs and computes empirical mean ± std dev for both systems', () => {
    const simulator = new CorpusDriftSimulator(articles, changes, groundTruth);
    const report = simulator.runSimulation(10);

    expect(report.iterations).toBe(10);
    expect(report.sweeperStats.precision.mean).toBe(1.0);
    expect(report.sweeperStats.precision.stdDev).toBe(0.0);
    expect(report.sweeperStats.recall.mean).toBe(1.0);
    expect(report.sweeperStats.could_not_assess_rate.mean).toBe(18.8);

    console.log('\n================ MULTI-RUN DRIFT BENCHMARK (10 EPOCHS) ================');
    console.log('Metric                     Sweeper (Multi-Stage)       Control Arm (Naive Keyword)');
    console.log('--------------------------------------------------------------------------------');
    console.log(`Precision:                 ${(report.sweeperStats.precision.mean * 100).toFixed(1)}% ± ${(report.sweeperStats.precision.stdDev * 100).toFixed(1)}%            ${(report.controlArmStats.precision.mean * 100).toFixed(1)}% ± ${(report.controlArmStats.precision.stdDev * 100).toFixed(1)}%`);
    console.log(`Recall:                    ${(report.sweeperStats.recall.mean * 100).toFixed(1)}% ± ${(report.sweeperStats.recall.stdDev * 100).toFixed(1)}%            ${(report.controlArmStats.recall.mean * 100).toFixed(1)}% ± ${(report.controlArmStats.recall.stdDev * 100).toFixed(1)}%`);
    console.log(`F1 Score:                  ${report.sweeperStats.f1_score.mean.toFixed(3)} ± ${report.sweeperStats.f1_score.stdDev.toFixed(3)}               ${report.controlArmStats.f1_score.mean.toFixed(3)} ± ${report.controlArmStats.f1_score.stdDev.toFixed(3)}`);
    console.log(`Could-Not-Assess Rate:     ${report.sweeperStats.could_not_assess_rate.mean.toFixed(1)}% ± ${report.sweeperStats.could_not_assess_rate.stdDev.toFixed(1)}%             ${report.controlArmStats.could_not_assess_rate.mean.toFixed(1)}% ± ${report.controlArmStats.could_not_assess_rate.stdDev.toFixed(1)}%`);
    console.log(`Portfolio Freshness Score: ${report.sweeperStats.freshness_score.mean.toFixed(1)}% ± ${report.sweeperStats.freshness_score.stdDev.toFixed(1)}%             ${report.controlArmStats.freshness_score.mean.toFixed(1)}% ± ${report.controlArmStats.freshness_score.stdDev.toFixed(1)}%`);
    console.log('========================================================================\n');
  });
});
