import {
  Article,
  ChangeEvent,
  Assessment,
  EditProposal,
  ScreenshotAssessment,
  ReviewDecision,
  PortfolioMetrics
} from './types.js';
import { extractSentences, matchDeterministic, matchSemantic } from './matcher.js';
import { extractEvidence } from './evidence.js';
import { classifyAssessment } from './classifier.js';
import { generateSurgicalEdit } from './surgical-editor.js';
import { analyzeScreenshots } from './screenshot-analyzer.js';
import { calculatePortfolioMetrics } from './freshness-score.js';
import { KnowledgeBaseDatabase } from './db.js';

export type GraphNode =
  | 'INIT'
  | 'DISCOVER_IMPACT'
  | 'CLASSIFY_CONFIDENCE'
  | 'DRAFT_SURGICAL_EDITS'
  | 'ANALYZE_SCREENSHOTS'
  | 'HUMAN_GATE_INTERRUPT'
  | 'APPLY_REVIEWS_AND_COMMIT'
  | 'FINALIZE_METRICS'
  | 'COMPLETED';

export interface GraphState {
  thread_id: string;
  articles: Article[];
  changes: ChangeEvent[];
  assessments: Assessment[];
  proposals: EditProposal[];
  screenshot_assessments: ScreenshotAssessment[];
  review_decisions: ReviewDecision[];
  applied_articles: Article[];
  status: 'RUNNING' | 'INTERRUPTED_AT_HUMAN_GATE' | 'COMPLETED' | 'FAILED';
  current_node: GraphNode;
  metrics?: PortfolioMetrics;
  logs: string[];
}

/**
 * Resumable Human-In-The-Loop (HITL) StateGraph Workflow Engine
 * Implements checkpointing, gate interrupts at human approval, and deterministic resumption.
 */
export class FreshnessSweeperAgentGraph {
  private db: KnowledgeBaseDatabase;

  constructor(db?: KnowledgeBaseDatabase) {
    this.db = db || new KnowledgeBaseDatabase(':memory:');
  }

  public async start(
    threadId: string,
    articles: Article[],
    changes: ChangeEvent[]
  ): Promise<GraphState> {
    for (const art of articles) {
      this.db.saveArticle(art);
    }

    const initialState: GraphState = {
      thread_id: threadId,
      articles: [...articles],
      changes: [...changes],
      assessments: [],
      proposals: [],
      screenshot_assessments: [],
      review_decisions: [],
      applied_articles: [...articles],
      status: 'RUNNING',
      current_node: 'DISCOVER_IMPACT',
      logs: [`[${new Date().toISOString()}] Workflow initialized for thread ${threadId}`]
    };

    return this.runUntilInterrupt(initialState);
  }

  public async resume(
    threadId: string,
    decisions: ReviewDecision[]
  ): Promise<GraphState> {
    const checkpoint = this.db.getCheckpoint(threadId);
    if (!checkpoint) {
      throw new Error(`No checkpoint found for thread ${threadId}`);
    }

    const state: GraphState = JSON.parse(checkpoint.state_json);
    if (state.status !== 'INTERRUPTED_AT_HUMAN_GATE') {
      throw new Error(`Thread ${threadId} is not interrupted at human gate (current: ${state.status})`);
    }

    state.review_decisions.push(...decisions);
    state.logs.push(`[${new Date().toISOString()}] Received ${decisions.length} human review decisions. Resuming graph.`);
    state.current_node = 'APPLY_REVIEWS_AND_COMMIT';
    state.status = 'RUNNING';

    return this.runUntilInterrupt(state);
  }

  public getStatus(threadId: string): GraphState | null {
    const checkpoint = this.db.getCheckpoint(threadId);
    if (!checkpoint) return null;
    return JSON.parse(checkpoint.state_json) as GraphState;
  }

  private async runUntilInterrupt(state: GraphState): Promise<GraphState> {
    while (state.status === 'RUNNING' && state.current_node !== 'COMPLETED') {
      switch (state.current_node) {
        case 'DISCOVER_IMPACT':
          state = this.nodeDiscoverImpact(state);
          state.current_node = 'CLASSIFY_CONFIDENCE';
          break;

        case 'CLASSIFY_CONFIDENCE':
          state = this.nodeClassifyConfidence(state);
          state.current_node = 'DRAFT_SURGICAL_EDITS';
          break;

        case 'DRAFT_SURGICAL_EDITS':
          state = this.nodeDraftSurgicalEdits(state);
          state.current_node = 'ANALYZE_SCREENSHOTS';
          break;

        case 'ANALYZE_SCREENSHOTS':
          state = this.nodeAnalyzeScreenshots(state);
          state.current_node = 'HUMAN_GATE_INTERRUPT';
          break;

        case 'HUMAN_GATE_INTERRUPT':
          // Check if there are pending proposals requiring human signoff
          if (state.proposals.length > 0 && state.review_decisions.length < state.proposals.length) {
            state.status = 'INTERRUPTED_AT_HUMAN_GATE';
            state.logs.push(`[${new Date().toISOString()}] Human Gate: ${state.proposals.length} proposal(s) awaiting review. Interrupting.`);
            this.db.saveCheckpoint(state.thread_id, state.current_node, true, state);
            return state;
          }
          state.current_node = 'APPLY_REVIEWS_AND_COMMIT';
          break;

        case 'APPLY_REVIEWS_AND_COMMIT':
          state = this.nodeApplyReviewsAndCommit(state);
          state.current_node = 'FINALIZE_METRICS';
          break;

        case 'FINALIZE_METRICS':
          state = this.nodeFinalizeMetrics(state);
          state.current_node = 'COMPLETED';
          state.status = 'COMPLETED';
          state.logs.push(`[${new Date().toISOString()}] Workflow completed successfully.`);
          this.db.saveCheckpoint(state.thread_id, state.current_node, false, state);
          break;

        default:
          throw new Error(`Unknown node: ${state.current_node}`);
      }
    }

    return state;
  }

  private nodeDiscoverImpact(state: GraphState): GraphState {
    state.logs.push(`[${new Date().toISOString()}] Node DISCOVER_IMPACT: Scanning ${state.articles.length} articles across ${state.changes.length} changes.`);
    return state;
  }

  private nodeClassifyConfidence(state: GraphState): GraphState {
    const assessments: Assessment[] = [];

    for (const article of state.articles) {
      const sentences = extractSentences(article.content);
      for (const change of state.changes) {
        const detMatches = matchDeterministic(sentences, change);
        const matches = matchSemantic(sentences, change, detMatches);
        const evidence = extractEvidence(article, matches);
        const assessment = classifyAssessment(article, change, evidence);
        assessments.push(assessment);
      }
    }

    state.assessments = assessments;
    state.logs.push(`[${new Date().toISOString()}] Node CLASSIFY_CONFIDENCE: Produced ${assessments.length} assessment classifications.`);
    return state;
  }

  private nodeDraftSurgicalEdits(state: GraphState): GraphState {
    const proposals: EditProposal[] = [];
    const changeMap = new Map(state.changes.map(c => [c.id, c]));

    for (const a of state.assessments) {
      if (a.status === 'AFFECTED' && a.evidence.length > 0) {
        const article = state.articles.find(art => art.id === a.article_id);
        const change = changeMap.get(a.change_id);
        if (article && change) {
          const proposal = generateSurgicalEdit(article, change, a.evidence);
          if (proposal) {
            proposals.push(proposal);
            this.db.saveProposal(proposal, state.thread_id);
          }
        }
      }
    }

    state.proposals = proposals;
    state.logs.push(`[${new Date().toISOString()}] Node DRAFT_SURGICAL_EDITS: Generated ${proposals.length} surgical edit proposals.`);
    return state;
  }

  private nodeAnalyzeScreenshots(state: GraphState): GraphState {
    const allScreenshots: ScreenshotAssessment[] = [];
    for (const article of state.articles) {
      for (const change of state.changes) {
        const assessments = analyzeScreenshots(article, change);
        allScreenshots.push(...assessments);
      }
    }
    state.screenshot_assessments = allScreenshots;
    return state;
  }

  private nodeApplyReviewsAndCommit(state: GraphState): GraphState {
    const articleMap = new Map(state.applied_articles.map(a => [a.id, { ...a }]));
    const decisionMap = new Map(state.review_decisions.map(d => [d.proposal_id, d]));

    for (const proposal of state.proposals) {
      const decision = decisionMap.get(proposal.id);
      if (decision) {
        proposal.status = decision.decision;
        proposal.reviewed_at = decision.timestamp;
        proposal.reviewer = decision.reviewer;
        proposal.review_notes = decision.notes;

        this.db.recordReviewDecision(decision);

        if (decision.decision === 'APPROVED') {
          const target = articleMap.get(proposal.article_id);
          if (target) {
            target.content = proposal.proposed_content;
            target.version += 1;
            target.last_updated = decision.timestamp;
            this.db.saveArticle(target);
          }
        }
      }
    }

    state.applied_articles = Array.from(articleMap.values());
    state.logs.push(`[${new Date().toISOString()}] Node APPLY_REVIEWS_AND_COMMIT: Applied approved surgical edits into persistent store.`);
    return state;
  }

  private nodeFinalizeMetrics(state: GraphState): GraphState {
    const metrics = calculatePortfolioMetrics(state.articles.length, state.assessments);
    state.metrics = metrics;
    return state;
  }
}
