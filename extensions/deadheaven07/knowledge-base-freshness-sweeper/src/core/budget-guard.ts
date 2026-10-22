import { Article, ChangeEvent, BudgetConfig } from './types.js';

export class BudgetExceededError extends Error {
  public estimatedCost: number;
  public budgetCap: number;

  constructor(estimatedCost: number, budgetCap: number) {
    super(
      `Pre-flight budget guard blocked execution: Estimated cost $${estimatedCost.toFixed(4)} exceeds configured cap $${budgetCap.toFixed(2)}. Use small-sample mode (--sample <N>) or adjust MAX_EVALUATION_COST_USD.`
    );
    this.name = 'BudgetExceededError';
    this.estimatedCost = estimatedCost;
    this.budgetCap = budgetCap;
  }
}

export const DEFAULT_BUDGET_CONFIG: BudgetConfig = {
  max_budget_usd: 1.00,
  cost_per_1k_input_tokens: 0.0015,
  cost_per_1k_output_tokens: 0.0020
};

export interface CostEstimationResult {
  totalInputTokens: number;
  totalOutputTokens: number;
  estimatedCostUsd: number;
  withinBudget: boolean;
  budgetCap: number;
}

export function estimateSweepCost(
  articles: Article[],
  changes: ChangeEvent[],
  config: BudgetConfig = DEFAULT_BUDGET_CONFIG
): CostEstimationResult {
  let totalChars = 0;
  for (const article of articles) {
    totalChars += article.content.length + article.title.length;
  }
  for (const change of changes) {
    totalChars += change.title.length + change.description.length;
  }

  // Approximation: ~4 chars per token
  const baseTokens = Math.ceil(totalChars / 4);
  const inputTokens = baseTokens * changes.length;
  // Estimated response tokens: ~150 tokens per article-change assessment pair
  const outputTokens = articles.length * changes.length * 150;

  const inputCost = (inputTokens / 1000) * config.cost_per_1k_input_tokens;
  const outputCost = (outputTokens / 1000) * config.cost_per_1k_output_tokens;
  const estimatedCost = Number((inputCost + outputCost).toFixed(4));

  return {
    totalInputTokens: inputTokens,
    totalOutputTokens: outputTokens,
    estimatedCostUsd: estimatedCost,
    withinBudget: estimatedCost <= config.max_budget_usd,
    budgetCap: config.max_budget_usd
  };
}

export function enforceBudgetGuard(
  articles: Article[],
  changes: ChangeEvent[],
  config: BudgetConfig = DEFAULT_BUDGET_CONFIG,
  provider: string = 'deterministic'
): CostEstimationResult {
  const estimation = estimateSweepCost(articles, changes, config);

  // If using live or simulated model that charges, enforce hard cap
  if (provider !== 'deterministic' && !estimation.withinBudget) {
    throw new BudgetExceededError(estimation.estimatedCostUsd, config.max_budget_usd);
  }

  return estimation;
}
