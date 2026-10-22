import {
  Article,
  ChangeEvent,
  Assessment,
  EditProposal,
  ScreenshotAssessment,
  PortfolioMetrics,
  SweepOptions,
  GroundTruthEntry,
  BudgetConfig
} from './types.js';
import { extractSentences, matchDeterministic, matchSemantic } from './matcher.js';
import { extractEvidence } from './evidence.js';
import { classifyAssessment } from './classifier.js';
import { generateSurgicalEdit } from './surgical-editor.js';
import { analyzeScreenshots } from './screenshot-analyzer.js';
import { calculatePortfolioMetrics } from './freshness-score.js';
import { enforceBudgetGuard, DEFAULT_BUDGET_CONFIG } from './budget-guard.js';
import { ArticleSearchIndex } from './search-index.js';
import { SuperDocsClient } from './superdocs-client.js';

export class KnowledgeBaseSweeper {
  private articles: Map<string, Article> = new Map();
  private changes: Map<string, ChangeEvent> = new Map();
  private assessments: Map<string, Assessment> = new Map(); // key: article_id
  private proposals: Map<string, EditProposal> = new Map(); // key: proposal_id
  private screenshotAssessments: Map<string, ScreenshotAssessment[]> = new Map(); // key: article_id
  private searchIndex: ArticleSearchIndex = new ArticleSearchIndex();
  private superdocsClient: SuperDocsClient;
  private modelCalls: number = 0;
  private actualCost: number = 0.0;
  private budgetConfig: BudgetConfig = DEFAULT_BUDGET_CONFIG;

  constructor(
    articles: Article[] = [],
    changes: ChangeEvent[] = [],
    budgetConfig: Partial<BudgetConfig> = {},
    superdocsApiKey?: string
  ) {
    this.budgetConfig = { ...DEFAULT_BUDGET_CONFIG, ...budgetConfig };
    this.superdocsClient = new SuperDocsClient({ apiKey: superdocsApiKey });
    this.addArticles(articles);
    this.addChanges(changes);
  }

  public getSuperDocsClient(): SuperDocsClient {
    return this.superdocsClient;
  }

  public addArticle(article: Article): void {
    this.articles.set(article.id, { ...article });
    this.searchIndex.addArticle(article);
  }

  public addArticles(articles: Article[]): void {
    for (const a of articles) {
      this.addArticle(a);
    }
  }

  public getArticle(id: string): Article | undefined {
    return this.articles.get(id);
  }

  public getArticles(): Article[] {
    return Array.from(this.articles.values());
  }

  public addChange(change: ChangeEvent): void {
    this.changes.set(change.id, { ...change });
  }

  public addChanges(changes: ChangeEvent[]): void {
    for (const c of changes) {
      this.addChange(c);
    }
  }

  public getChanges(): ChangeEvent[] {
    return Array.from(this.changes.values());
  }

  public getProposals(): EditProposal[] {
    return Array.from(this.proposals.values());
  }

  public getAssessments(): Assessment[] {
    return Array.from(this.assessments.values());
  }

  public getScreenshotAssessments(): ScreenshotAssessment[] {
    const all: ScreenshotAssessment[] = [];
    for (const list of this.screenshotAssessments.values()) {
      all.push(...list);
    }
    return all;
  }

  /**
   * Runs the complete multi-stage freshness sweep across articles and changes.
   */
  public sweep(options: SweepOptions = {}): {
    assessments: Assessment[];
    proposals: EditProposal[];
    screenshotAssessments: ScreenshotAssessment[];
    metrics: PortfolioMetrics;
  } {
    let targetArticles = Array.from(this.articles.values());
    if (options.sample_size && options.sample_size > 0) {
      targetArticles = targetArticles.slice(0, options.sample_size);
    }

    const targetChanges = Array.from(this.changes.values());
    const config = { ...this.budgetConfig, ...options.budget_config };
    const provider = options.provider || 'deterministic';

    // 1. Budget Guard Pre-flight Check
    const estimation = enforceBudgetGuard(targetArticles, targetChanges, config, provider);

    // Track simulated / deterministic execution
    this.modelCalls += targetArticles.length * targetChanges.length;
    if (provider !== 'deterministic') {
      this.actualCost = estimation.estimatedCostUsd;
    } else {
      this.actualCost = 0.0; // Offline tests are completely free ($0.00)
    }

    this.assessments.clear();
    this.proposals.clear();
    this.screenshotAssessments.clear();

    for (const article of targetArticles) {
      let combinedAssessment: Assessment | null = null;
      const allScreenshots: ScreenshotAssessment[] = [];

      for (const change of targetChanges) {
        // Stage 0: Split sentences
        const sentences = extractSentences(article.content);

        // Stage 1: Deterministic matching
        const directMatches = matchDeterministic(sentences, change);

        // Stage 2: Semantic matching
        const allMatches = matchSemantic(sentences, change, directMatches);

        // Stage 3: Evidence extraction
        const evidence = extractEvidence(article, allMatches);

        // Stage 4: Classification & Honesty check
        const assessment = classifyAssessment(article, change, evidence);

        // Merge assessment (prioritize AFFECTED > COULD_NOT_ASSESS > NOT_AFFECTED)
        if (!combinedAssessment || assessment.status === 'AFFECTED' || (assessment.status === 'COULD_NOT_ASSESS' && combinedAssessment.status === 'NOT_AFFECTED')) {
          combinedAssessment = assessment;
        }

        // Surgical edit proposal if affected
        if (assessment.status === 'AFFECTED' && evidence.length > 0) {
          const proposal = generateSurgicalEdit(article, change, evidence);
          if (proposal) {
            this.proposals.set(proposal.id, proposal);
          }
        }

        // Screenshot Freshness Analysis
        const ssAssessments = analyzeScreenshots(article, change);
        allScreenshots.push(...ssAssessments);
      }

      // Deduplicate screenshot assessments by screenshot_id (preferring REPLACEMENT_REQUIRED > COULD_NOT_ASSESS > OK)
      const dedupedScreenshotsMap = new Map<string, ScreenshotAssessment>();
      for (const ss of allScreenshots) {
        const existing = dedupedScreenshotsMap.get(ss.screenshot_id);
        if (!existing || ss.status === 'SCREENSHOT_REPLACEMENT_REQUIRED' || (ss.status === 'COULD_NOT_ASSESS' && existing.status === 'SCREENSHOT_OK')) {
          dedupedScreenshotsMap.set(ss.screenshot_id, ss);
        }
      }
      const dedupedScreenshots = Array.from(dedupedScreenshotsMap.values());

      // If screenshot could not be assessed and article is otherwise unchanged, roll up to COULD_NOT_ASSESS
      if (allScreenshots.some(s => s.status === 'COULD_NOT_ASSESS') && combinedAssessment?.status === 'NOT_AFFECTED') {
        combinedAssessment = {
          article_id: article.id,
          change_id: targetChanges[0]?.id || 'unknown',
          status: 'COULD_NOT_ASSESS',
          confidence: 'LOW',
          evidence: [],
          affected_sections: [],
          reason: 'Embedded screenshot lacks visual OCR labels or metadata and could not be verified.',
          could_not_assess_details: {
            what_checked: ['Screenshot OCR labels', 'Visual metadata'],
            missing_evidence: 'Screenshot has empty OCR labels and missing caption.',
            why_insufficient: 'Visual verification cannot be performed without OCR labels.'
          }
        };
      }

      if (combinedAssessment) {
        this.assessments.set(article.id, combinedAssessment);
      }
      if (dedupedScreenshots.length > 0) {
        this.screenshotAssessments.set(article.id, dedupedScreenshots);
      }
    }

    const metrics = this.getMetrics();

    return {
      assessments: Array.from(this.assessments.values()),
      proposals: Array.from(this.proposals.values()),
      screenshotAssessments: this.getScreenshotAssessments(),
      metrics
    };
  }

  /**
   * Approves an edit proposal and surgically applies the patch to the article.
   */
  public approveProposal(
    proposalId: string,
    reviewer: string = 'knowledge-manager',
    notes?: string
  ): { success: boolean; article?: Article; proposal?: EditProposal } {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      return { success: false };
    }

    const article = this.articles.get(proposal.article_id);
    if (!article) {
      return { success: false };
    }

    // Apply surgical edit
    article.content = proposal.proposed_content;
    article.version += 1;
    article.last_updated = new Date().toISOString();

    proposal.status = 'APPROVED';
    proposal.reviewed_at = new Date().toISOString();
    proposal.reviewer = reviewer;
    proposal.review_notes = notes;

    // Update assessment to reflect resolution
    const assessment = this.assessments.get(article.id);
    if (assessment) {
      assessment.status = 'NOT_AFFECTED';
      assessment.reason = `Proposal ${proposalId} approved. Content updated to current state.`;
      assessment.evidence = [];
    }

    // Sync to SuperDocs API if configured
    if (this.superdocsClient.isConfigured()) {
      this.superdocsClient.applySurgicalPatch(article.id, proposal.proposed_content).catch(() => {});
    }

    return { success: true, article, proposal };
  }

  /**
   * Rejects an edit proposal, leaving original article untouched.
   */
  public rejectProposal(
    proposalId: string,
    reviewer: string = 'knowledge-manager',
    notes?: string
  ): { success: boolean; proposal?: EditProposal } {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      return { success: false };
    }

    proposal.status = 'REJECTED';
    proposal.reviewed_at = new Date().toISOString();
    proposal.reviewer = reviewer;
    proposal.review_notes = notes || 'Proposal rejected during human review.';

    return { success: true, proposal };
  }

  public getMetrics(groundTruth?: GroundTruthEntry[]): PortfolioMetrics {
    const allAssessments = Array.from(this.assessments.values());
    return calculatePortfolioMetrics(
      this.articles.size,
      allAssessments,
      groundTruth,
      {
        actual_cost: this.actualCost,
        estimated_cost: 0.0,
        budget_limit: this.budgetConfig.max_budget_usd,
        model_calls: this.modelCalls
      }
    );
  }
}
