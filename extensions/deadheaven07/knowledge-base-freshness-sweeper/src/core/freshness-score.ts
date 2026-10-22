import { PortfolioMetrics, Assessment, GroundTruthEntry } from './types.js';

export function calculatePortfolioMetrics(
  totalArticles: number,
  assessments: Assessment[],
  groundTruthList?: GroundTruthEntry[],
  costStats?: { actual_cost: number; estimated_cost: number; budget_limit: number; model_calls: number }
): PortfolioMetrics {
  let affected = 0;
  let unchanged = 0;
  let couldNotAssess = 0;

  for (const a of assessments) {
    if (a.status === 'AFFECTED') {
      affected++;
    } else if (a.status === 'NOT_AFFECTED') {
      unchanged++;
    } else if (a.status === 'COULD_NOT_ASSESS') {
      couldNotAssess++;
    }
  }

  const assessedTotal = affected + unchanged;
  const freshnessScore =
    assessedTotal > 0
      ? Number(((unchanged / assessedTotal) * 100).toFixed(1))
      : 100.0;

  const assessmentCoverage =
    totalArticles > 0
      ? Number(((assessedTotal / totalArticles) * 100).toFixed(1))
      : 100.0;

  const couldNotAssessRate =
    totalArticles > 0
      ? Number(((couldNotAssess / totalArticles) * 100).toFixed(1))
      : 0.0;

  // Evaluation against Ground Truth (if provided)
  let tp = 0;
  let fp = 0;
  let fn = 0;
  let tn = 0;

  if (groundTruthList && groundTruthList.length > 0) {
    const assessmentMap = new Map<string, Assessment>();
    for (const a of assessments) {
      assessmentMap.set(a.article_id, a);
    }

    for (const gt of groundTruthList) {
      const actual = assessmentMap.get(gt.article_id);
      const actualStatus = actual ? actual.status : 'NOT_AFFECTED';

      if (gt.expected_status === 'AFFECTED') {
        if (actualStatus === 'AFFECTED') {
          tp++;
        } else {
          fn++;
        }
      } else if (gt.expected_status === 'NOT_AFFECTED') {
        if (actualStatus === 'AFFECTED') {
          fp++;
        } else {
          tn++;
        }
      } else if (gt.expected_status === 'COULD_NOT_ASSESS') {
        if (actualStatus === 'AFFECTED') {
          fp++;
        }
      }
    }
  }

  const precision = tp + fp > 0 ? Number((tp / (tp + fp)).toFixed(3)) : 1.0;
  const recall = tp + fn > 0 ? Number((tp / (tp + fn)).toFixed(3)) : 1.0;
  const f1 =
    precision + recall > 0
      ? Number(((2 * precision * recall) / (precision + recall)).toFixed(3))
      : 0.0;

  return {
    total_articles: totalArticles,
    affected_articles: affected,
    stale_articles: affected,
    unchanged_articles: unchanged,
    could_not_assess: couldNotAssess,
    freshness_score: freshnessScore,
    assessment_coverage: assessmentCoverage,
    precision,
    recall,
    f1_score: f1,
    true_positives: tp,
    false_positives: fp,
    false_negatives: fn,
    true_negatives: tn,
    could_not_assess_rate: couldNotAssessRate,
    actual_cost: costStats?.actual_cost || 0.0,
    estimated_cost: costStats?.estimated_cost || 0.0,
    budget_limit: costStats?.budget_limit || 1.0,
    model_calls: costStats?.model_calls || 0
  };
}
