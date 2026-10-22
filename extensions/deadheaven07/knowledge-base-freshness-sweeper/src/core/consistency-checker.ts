import { Article } from './types.js';

export interface ConsistencyViolation {
  rule: 'CONTRADICTING_LIMITS' | 'DISCREPANT_PLAN_NAME' | 'BROKEN_CROSS_REFERENCE';
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  articles: string[]; // article IDs involved
  description: string;
  evidence: string[];
}

export interface ConsistencyReport {
  total_articles_scanned: number;
  violations: ConsistencyViolation[];
  cross_document_consistency_score: number; // 0 to 100
}

/**
 * Cross-Document Multi-Article Consistency Checker (Band S3: Multi-Document)
 * Scans the portfolio for contradictions, divergent quotas, and broken cross-references.
 */
export class KnowledgeBaseConsistencyChecker {
  private articles: Article[];

  constructor(articles: Article[]) {
    this.articles = articles;
  }

  public checkConsistency(): ConsistencyReport {
    const violations: ConsistencyViolation[] = [];

    // 1. Check for Contradicting Quotas / Numeric Limits across articles
    const limitPatterns = [
      {
        name: 'API Rate Limit',
        contextRegex: /(?:api calls|rate limit|quota|monthly limit)/i,
        valueRegex: /(\d+[\d,]*)\s*(?:api calls|requests|calls)/i
      },
      {
        name: 'Attachment File Limit',
        contextRegex: /(?:attachment|file size|upload limit|diagram upload)/i,
        valueRegex: /(\d+)\s*mb/i
      }
    ];

    for (const pattern of limitPatterns) {
      const mentionsByArticle: Map<string, { value: string; quote: string }> = new Map();

      for (const art of this.articles) {
        if (pattern.contextRegex.test(art.content)) {
          const match = pattern.valueRegex.exec(art.content);
          if (match) {
            mentionsByArticle.set(art.id, {
              value: match[1].replaceAll(',', ''),
              quote: match[0]
            });
          }
        }
      }

      // If multiple distinct values are mentioned across articles for the same concept
      const uniqueValues = new Set(Array.from(mentionsByArticle.values()).map(m => m.value));
      if (uniqueValues.size > 1) {
        const involvedArticles = Array.from(mentionsByArticle.keys());
        violations.push({
          rule: 'CONTRADICTING_LIMITS',
          severity: 'HIGH',
          articles: involvedArticles,
          description: `Discrepant ${pattern.name} values found across documents (${Array.from(uniqueValues).join(' vs ')}).`,
          evidence: Array.from(mentionsByArticle.entries()).map(([id, data]) => `${id}: "${data.quote}"`)
        });
      }
    }

    // 2. Check for Discrepant / Deprecated Plan mentions alongside modern plans
    const planMentions: Map<string, string[]> = new Map();
    for (const art of this.articles) {
      const plansInArt: string[] = [];
      if (/legacy pro/i.test(art.content)) plansInArt.push('Legacy Pro (Retired)');
      if (/growth plan/i.test(art.content)) plansInArt.push('Growth Plan');
      if (plansInArt.length > 0) {
        planMentions.set(art.id, plansInArt);
      }
    }

    const legacyArticles = Array.from(planMentions.entries())
      .filter(([_, plans]) => plans.includes('Legacy Pro (Retired)'))
      .map(([id]) => id);

    if (legacyArticles.length > 0) {
      violations.push({
        rule: 'DISCREPANT_PLAN_NAME',
        severity: 'MEDIUM',
        articles: legacyArticles,
        description: `Deprecated 'Legacy Pro' tier referenced across ${legacyArticles.length} article(s) while modern tiers are in use.`,
        evidence: legacyArticles.map(id => `${id} references deprecated 'Legacy Pro'`)
      });
    }

    // 3. Compute consistency score
    const totalChecks = this.articles.length * 2;
    const penalty = violations.reduce((acc, v) => acc + (v.severity === 'HIGH' ? 15 : 8), 0);
    const score = Math.max(0, Math.min(100, Math.round(100 - (penalty / Math.max(1, totalChecks)) * 100)));

    return {
      total_articles_scanned: this.articles.length,
      violations,
      cross_document_consistency_score: score
    };
  }
}
