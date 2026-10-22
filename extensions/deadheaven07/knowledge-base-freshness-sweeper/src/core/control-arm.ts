import { Article, ChangeEvent, GroundTruthEntry, PortfolioMetrics } from './types.js';

export interface ControlArmAssessment {
  article_id: string;
  change_id?: string;
  status: 'AFFECTED' | 'NOT_AFFECTED';
  matched_keywords: string[];
}

/**
 * Control Arm Baseline Detector
 * A naive keyword-only baseline detector that evaluates the corpus without multi-stage AST parsing,
 * indirect workflow deduction, or confidence/honesty thresholds.
 * Serves as the scientific control arm for empirical comparison.
 */
export class NaiveKeywordControlArm {
  private articles: Article[];
  private changes: ChangeEvent[];

  constructor(articles: Article[], changes: ChangeEvent[]) {
    this.articles = articles;
    this.changes = changes;
  }

  public run(): ControlArmAssessment[] {
    const results: ControlArmAssessment[] = [];

    for (const article of this.articles) {
      const contentLower = article.content.toLowerCase();
      let isAffected = false;
      let matchedChangeId: string | undefined;
      const matchedKeywords: string[] = [];

      for (const change of this.changes) {
        // Naive keyword list derived purely from change metadata without context filtering
        const keywords = this.extractNaiveKeywords(change);

        for (const kw of keywords) {
          if (contentLower.includes(kw.toLowerCase())) {
            isAffected = true;
            matchedChangeId = change.id;
            matchedKeywords.push(kw);
          }
        }
        if (isAffected) break;
      }

      results.push({
        article_id: article.id,
        change_id: matchedChangeId,
        status: isAffected ? 'AFFECTED' : 'NOT_AFFECTED',
        matched_keywords: matchedKeywords
      });
    }

    return results;
  }

  private extractNaiveKeywords(change: ChangeEvent): string[] {
    const kws: string[] = [];
    if (change.before_state.entity_name) kws.push(change.before_state.entity_name);
    if (change.before_state.ui_label) kws.push(change.before_state.ui_label);
    if (change.before_state.value !== undefined) kws.push(String(change.before_state.value));

    // Naive tokens from title
    const titleWords = change.title.split(/\s+/).filter(w => w.length > 4);
    kws.push(...titleWords);

    return Array.from(new Set(kws));
  }

  public evaluate(groundTruth: GroundTruthEntry[]): PortfolioMetrics {
    const assessments = this.run();
    const gtMap = new Map(groundTruth.map(g => [g.article_id, g]));

    let tp = 0;
    let fp = 0;
    let fn = 0;
    let tn = 0;

    for (const a of assessments) {
      const gt = gtMap.get(a.article_id);
      if (!gt) continue;

      const isActuallyAffected = gt.expected_status === 'AFFECTED';
      const isPredictedAffected = a.status === 'AFFECTED';

      if (isPredictedAffected && isActuallyAffected) {
        tp++;
      } else if (isPredictedAffected && !isActuallyAffected) {
        fp++;
      } else if (!isPredictedAffected && isActuallyAffected) {
        fn++;
      } else {
        tn++;
      }
    }

    const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
    const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
    const f1_score = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;

    return {
      total_articles: assessments.length,
      affected_articles: tp + fp,
      stale_articles: tp + fp,
      unchanged_articles: tn + fn,
      could_not_assess: 0, // Naive control arm has no honest CNA bucket
      freshness_score: Math.round(((tn + fn) / assessments.length) * 1000) / 10,
      assessment_coverage: 100, // 100% forced binary assessment
      precision: Math.round(precision * 1000) / 1000,
      recall: Math.round(recall * 1000) / 1000,
      f1_score: Math.round(f1_score * 1000) / 1000,
      true_positives: tp,
      false_positives: fp,
      false_negatives: fn,
      true_negatives: tn,
      could_not_assess_rate: 0,
      actual_cost: 0.0,
      estimated_cost: 0.0,
      budget_limit: 10.0,
      model_calls: 0
    };
  }
}
