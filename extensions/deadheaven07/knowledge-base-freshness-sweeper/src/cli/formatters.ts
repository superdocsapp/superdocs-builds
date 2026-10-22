import { PortfolioMetrics, EditProposal } from '../core/types.js';
import { StatisticalSummary } from '../core/drift-simulator.js';

export const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  magenta: '\x1b[35m',
  white: '\x1b[37m'
};

export function formatMetricsTable(metrics: PortfolioMetrics): string {
  const lines: string[] = [];
  lines.push(`${colors.bright}${colors.cyan}┌────────────────────────────────────────────────────────────┐${colors.reset}`);
  lines.push(`${colors.bright}${colors.cyan}│      KNOWLEDGE-BASE FRESHNESS SWEEPER — PORTFOLIO METRICS  │${colors.reset}`);
  lines.push(`${colors.bright}${colors.cyan}├────────────────────────────────────────────────────────────┤${colors.reset}`);
  lines.push(`│ Total Scanned Articles:     ${colors.bright}${metrics.total_articles.toString().padEnd(28)}${colors.reset}│`);
  lines.push(`│ Healthy (Unchanged):        ${colors.green}${metrics.unchanged_articles.toString().padEnd(28)}${colors.reset}│`);
  lines.push(`│ Stale / Affected Articles:  ${colors.red}${metrics.affected_articles.toString().padEnd(28)}${colors.reset}│`);
  lines.push(`│ Could-Not-Assess (Honest):  ${colors.yellow}${metrics.could_not_assess.toString().padEnd(28)}${colors.reset}│`);
  lines.push(`${colors.bright}${colors.cyan}├────────────────────────────────────────────────────────────┤${colors.reset}`);
  lines.push(`│ Portfolio Freshness Score:  ${colors.bright}${colors.green}${(metrics.freshness_score + '%').padEnd(28)}${colors.reset}│`);
  lines.push(`│ Assessment Coverage:        ${colors.bright}${(metrics.assessment_coverage + '%').padEnd(28)}${colors.reset}│`);
  lines.push(`│ Could-Not-Assess Rate:      ${colors.yellow}${(metrics.could_not_assess_rate + '%').padEnd(28)}${colors.reset}│`);
  lines.push(`${colors.bright}${colors.cyan}├────────────────────────────────────────────────────────────┤${colors.reset}`);
  lines.push(`│ Evaluation Precision:       ${colors.bright}${((metrics.precision * 100).toFixed(1) + '%').padEnd(28)}${colors.reset}│`);
  lines.push(`│ Evaluation Recall:          ${colors.bright}${((metrics.recall * 100).toFixed(1) + '%').padEnd(28)}${colors.reset}│`);
  lines.push(`│ Evaluation F1 Score:        ${colors.bright}${metrics.f1_score.toString().padEnd(28)}${colors.reset}│`);
  lines.push(`│ True Positives / Negatives: ${colors.green}${metrics.true_positives}${colors.reset} TP / ${colors.green}${metrics.true_negatives}${colors.reset} TN`.padEnd(52) + '│');
  lines.push(`│ False Positives / Negatives:${colors.red}${metrics.false_positives}${colors.reset} FP / ${colors.red}${metrics.false_negatives}${colors.reset} FN`.padEnd(52) + '│');
  lines.push(`${colors.bright}${colors.cyan}├────────────────────────────────────────────────────────────┤${colors.reset}`);
  lines.push(`│ Configured Budget Cap:      ${('$ ' + metrics.budget_limit.toFixed(2)).padEnd(28)}│`);
  lines.push(`│ Actual Model / API Spend:   ${colors.green}${('$ ' + metrics.actual_cost.toFixed(2)).padEnd(28)}${colors.reset}│`);
  lines.push(`${colors.bright}${colors.cyan}└────────────────────────────────────────────────────────────┘${colors.reset}`);
  return lines.join('\n');
}

export function formatControlArmComparisonTable(
  sweeper: {
    precision: StatisticalSummary;
    recall: StatisticalSummary;
    f1_score: StatisticalSummary;
    could_not_assess_rate: StatisticalSummary;
    freshness_score: StatisticalSummary;
  },
  control: {
    precision: StatisticalSummary;
    recall: StatisticalSummary;
    f1_score: StatisticalSummary;
    could_not_assess_rate: StatisticalSummary;
    freshness_score: StatisticalSummary;
  },
  iterations: number
): string {
  const lines: string[] = [];
  lines.push(`\n${colors.bright}${colors.cyan}================ MULTI-RUN DRIFT BENCHMARK (${iterations} INDEPENDENT EPOCHS) ================${colors.reset}`);
  lines.push(`${colors.bright}Metric                     Multi-Stage Sweeper         Control Arm (Naive Keyword)   Delta${colors.reset}`);
  lines.push(`------------------------------------------------------------------------------------------------`);
  
  const pDiff = ((sweeper.precision.mean - control.precision.mean) * 100).toFixed(1);
  const rDiff = ((sweeper.recall.mean - control.recall.mean) * 100).toFixed(1);
  const f1Diff = (sweeper.f1_score.mean - control.f1_score.mean).toFixed(3);

  lines.push(`Precision:                 ${colors.green}${(sweeper.precision.mean * 100).toFixed(1)}% ± ${(sweeper.precision.stdDev * 100).toFixed(1)}%${colors.reset}            ${(control.precision.mean * 100).toFixed(1)}% ± ${(control.precision.stdDev * 100).toFixed(1)}%            ${colors.green}+${pDiff}%${colors.reset}`);
  lines.push(`Recall:                    ${colors.green}${(sweeper.recall.mean * 100).toFixed(1)}% ± ${(sweeper.recall.stdDev * 100).toFixed(1)}%${colors.reset}            ${(control.recall.mean * 100).toFixed(1)}% ± ${(control.recall.stdDev * 100).toFixed(1)}%            ${colors.green}+${rDiff}%${colors.reset}`);
  lines.push(`F1 Score:                  ${colors.green}${sweeper.f1_score.mean.toFixed(3)} ± ${sweeper.f1_score.stdDev.toFixed(3)}${colors.reset}               ${control.f1_score.mean.toFixed(3)} ± ${control.f1_score.stdDev.toFixed(3)}               ${colors.green}+${f1Diff}${colors.reset}`);
  lines.push(`Could-Not-Assess Rate:     ${colors.yellow}${sweeper.could_not_assess_rate.mean.toFixed(1)}% ± ${sweeper.could_not_assess_rate.stdDev.toFixed(1)}%${colors.reset}             ${control.could_not_assess_rate.mean.toFixed(1)}% ± ${control.could_not_assess_rate.stdDev.toFixed(1)}%             ${colors.cyan}Honest Bucket${colors.reset}`);
  lines.push(`Portfolio Freshness Score: ${sweeper.freshness_score.mean.toFixed(1)}% ± ${sweeper.freshness_score.stdDev.toFixed(1)}%             ${control.freshness_score.mean.toFixed(1)}% ± ${control.freshness_score.stdDev.toFixed(1)}%             ${colors.dim}Calibrated${colors.reset}`);
  lines.push(`================================================================================================\n`);
  return lines.join('\n');
}

export function formatProposalDiff(proposal: EditProposal): string {
  const lines: string[] = [];
  lines.push(`\n${colors.bright}${colors.yellow}================ PROPOSED SURGICAL EDIT ================${colors.reset}`);
  lines.push(`Article ID:   ${colors.bright}${proposal.article_id}${colors.reset}`);
  lines.push(`Change ID:    ${proposal.change_id}`);
  lines.push(`Confidence:   ${proposal.confidence === 'HIGH' ? colors.green + 'HIGH' : colors.yellow + 'MEDIUM'}${colors.reset}`);
  lines.push(`Preservation: ${colors.green}${(proposal.structural_preservation_ratio * 100).toFixed(1)}%${colors.reset} of article content preserved unmodified`);
  lines.push(`Rationale:    ${proposal.rationale}\n`);

  lines.push(`${colors.bright}--- Evidence Quotes ---${colors.reset}`);
  for (const e of proposal.evidence) {
    lines.push(`  [Sentence ${e.sentence_index}] ${colors.dim}"${e.sentence_text}"${colors.reset}`);
    lines.push(`  ↳ ${e.explanation}`);
  }

  lines.push(`\n${colors.bright}--- Surgical Diff Spans ---${colors.reset}`);
  for (const span of proposal.changed_spans) {
    lines.push(`${colors.red}- ${span.original_text}${colors.reset}`);
    lines.push(`${colors.green}+ ${span.replacement_text}${colors.reset}`);
  }
  return lines.join('\n');
}
