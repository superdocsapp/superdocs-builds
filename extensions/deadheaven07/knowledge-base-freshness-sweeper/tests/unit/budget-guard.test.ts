import { describe, it, expect } from 'vitest';
import { estimateSweepCost, enforceBudgetGuard, BudgetExceededError } from '../../src/core/budget-guard.js';
import { Article, ChangeEvent, BudgetConfig } from '../../src/core/types.js';

describe('Budget Guard and Pre-flight Cap Enforcement (Test 14)', () => {
  const articles: Article[] = [];
  for (let i = 0; i < 50; i++) {
    articles.push({
      id: `art-${i}`,
      title: `Article ${i} on Product Configuration`,
      content: `# Section ${i}\n` + 'A'.repeat(5000),
      version: 1,
      metadata: {},
      screenshots: [],
      last_updated: '2026-01-01'
    });
  }

  const changes: ChangeEvent[] = [];
  for (let j = 0; j < 10; j++) {
    changes.push({
      id: `change-${j}`,
      type: 'CHANGED_LIMIT',
      title: `Change ${j}`,
      description: 'D'.repeat(2000),
      before_state: {},
      after_state: {},
      effective_date: '2026-08-01',
      source: 'Notes'
    });
  }

  it('estimates token volume and cost before executing sweep', () => {
    const estimation = estimateSweepCost(articles, changes, {
      max_budget_usd: 5.00,
      cost_per_1k_input_tokens: 0.0015,
      cost_per_1k_output_tokens: 0.0020
    });

    expect(estimation.totalInputTokens).toBeGreaterThan(0);
    expect(estimation.estimatedCostUsd).toBeGreaterThan(0);
  });

  it('throws BudgetExceededError when estimated cost exceeds configured budget cap on non-deterministic runs', () => {
    const tinyBudget: BudgetConfig = {
      max_budget_usd: 0.0001, // ultra low cap
      cost_per_1k_input_tokens: 0.0015,
      cost_per_1k_output_tokens: 0.0020
    };

    expect(() => {
      enforceBudgetGuard(articles, changes, tinyBudget, 'simulated-llm');
    }).toThrow(BudgetExceededError);
  });
});
