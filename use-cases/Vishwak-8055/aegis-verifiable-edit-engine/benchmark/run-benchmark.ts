#!/usr/bin/env node
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { AegisEngine } from '../src/orchestrator/aegisEngine.js';
import { MockSuperDocClient } from '../src/execution/mockSuperDocClient.js';
import { fixedResult } from '../src/execution/scenarioResolvers.js';
import { Logger } from '../src/logging/logger.js';
import { BENCHMARK_CASES, type BenchmarkCase } from './dataset.js';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const resultsDir = path.join(moduleDir, 'results');
const quietLogger = new Logger('error', false);

interface CaseResult {
  id: string;
  category: BenchmarkCase['category'];
  expected: BenchmarkCase['expected'];
  actualDecision: string;
  actualOutcome: 'SAFE' | 'UNSAFE';
  correct: boolean;
  expectedFindingKind?: string;
  foundExpectedFindingKind: boolean | null;
  findingKinds: string[];
}

async function runCase(testCase: BenchmarkCase): Promise<CaseResult> {
  const engine = new AegisEngine({
    superDocClient: new MockSuperDocClient({ resolver: fixedResult(testCase.after) }),
    logger: quietLogger,
  });
  const result = await engine.runEdit({ document: testCase.before, instruction: testCase.instruction });
  const decision = result.proof.decision;
  const actualOutcome: 'SAFE' | 'UNSAFE' = decision === 'VERIFIED' || decision === 'VERIFIED_WITH_WARNINGS' ? 'SAFE' : 'UNSAFE';
  const findingKinds = result.proof.evidence.findings.map((f) => f.kind);

  return {
    id: testCase.id,
    category: testCase.category,
    expected: testCase.expected,
    actualDecision: decision,
    actualOutcome,
    correct: actualOutcome === testCase.expected,
    expectedFindingKind: testCase.expectedFindingKind,
    foundExpectedFindingKind: testCase.expectedFindingKind ? findingKinds.includes(testCase.expectedFindingKind) : null,
    findingKinds,
  };
}

async function main(): Promise<void> {
  const results: CaseResult[] = [];
  for (const testCase of BENCHMARK_CASES) {
    results.push(await runCase(testCase));
  }

  const byCategory = groupBy(results, (r) => r.category);
  const totalCorrect = results.filter((r) => r.correct).length;

  // Confusion-matrix-style breakdown, computed from what actually ran —
  // nothing here is a placeholder.
  const unsafeCases = results.filter((r) => r.expected === 'UNSAFE');
  const safeCases = results.filter((r) => r.expected === 'SAFE');
  const correctlyCaughtUnsafe = unsafeCases.filter((r) => r.correct).length; // true positives
  const missedUnsafe = unsafeCases.filter((r) => !r.correct); // false negatives — the dangerous kind
  const correctlyPassedSafe = safeCases.filter((r) => r.correct).length; // true negatives
  const falselyBlockedSafe = safeCases.filter((r) => !r.correct); // false positives

  console.log('');
  console.log(`Aegis adversarial benchmark — ${results.length} cases (real pipeline execution, mock adapter)`);
  console.log('='.repeat(78));

  for (const [category, group] of Object.entries(byCategory)) {
    console.log('');
    console.log(`${category.toUpperCase()} (${group.filter((r) => r.correct).length}/${group.length} correct)`);
    for (const r of group) {
      const mark = r.correct ? '✓' : '✗';
      const findingNote = r.expectedFindingKind
        ? ` [expected finding ${r.expectedFindingKind}: ${r.foundExpectedFindingKind ? 'present' : 'NOT FOUND'}]`
        : '';
      console.log(`  ${mark} ${r.id} — expected ${r.expected}, got ${r.actualOutcome} (${r.actualDecision})${findingNote}`);
    }
  }

  console.log('');
  console.log('-'.repeat(78));
  console.log(`Overall: ${totalCorrect}/${results.length} correct (${((totalCorrect / results.length) * 100).toFixed(1)}%)`);
  console.log(`Unsafe edits correctly caught (recall on the dangerous class): ${correctlyCaughtUnsafe}/${unsafeCases.length}`);
  console.log(`Safe edits correctly passed (specificity): ${correctlyPassedSafe}/${safeCases.length}`);
  if (missedUnsafe.length > 0) {
    console.log('');
    console.log(`⚠ MISSED unsafe case(s) — these are the dangerous failure mode (false negatives):`);
    for (const r of missedUnsafe) console.log(`  - ${r.id}: got ${r.actualDecision}, findings: [${r.findingKinds.join(', ') || 'none'}]`);
  }
  if (falselyBlockedSafe.length > 0) {
    console.log('');
    console.log(`Note: safe case(s) that were over-flagged (false positives, annoying but not dangerous):`);
    for (const r of falselyBlockedSafe) console.log(`  - ${r.id}: got ${r.actualDecision}, findings: [${r.findingKinds.join(', ') || 'none'}]`);
  }

  const findingKindChecks = results.filter((r) => r.expectedFindingKind !== undefined);
  const findingKindMatches = findingKindChecks.filter((r) => r.foundExpectedFindingKind).length;
  console.log('');
  console.log(
    `Expected-finding-kind diagnostic (informational, not part of the pass/fail score): ${findingKindMatches}/${findingKindChecks.length} cases surfaced the specific finding kind we predicted.`,
  );

  mkdirSync(resultsDir, { recursive: true });
  const summary = {
    generated_at: new Date().toISOString(),
    total_cases: results.length,
    total_correct: totalCorrect,
    accuracy: totalCorrect / results.length,
    unsafe_recall: `${correctlyCaughtUnsafe}/${unsafeCases.length}`,
    safe_specificity: `${correctlyPassedSafe}/${safeCases.length}`,
    results,
  };
  const outPath = path.join(resultsDir, 'latest.json');
  writeFileSync(outPath, JSON.stringify(summary, null, 2), 'utf-8');
  console.log('');
  console.log(`Full results written to benchmark/results/latest.json`);

  if (missedUnsafe.length > 0) {
    process.exitCode = 1; // a missed unsafe case is a real regression, not just a warning
  }
}

function groupBy<T, K extends string>(items: T[], key: (item: T) => K): Record<K, T[]> {
  const out = {} as Record<K, T[]>;
  for (const item of items) {
    const k = key(item);
    (out[k] ??= []).push(item);
  }
  return out;
}

main().catch((error) => {
  console.error('Benchmark failed to run:', error);
  process.exitCode = 1;
});
