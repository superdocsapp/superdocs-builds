import { createRequire } from 'module';
import path from 'path';
import fs from 'fs';
import {
  Article,
  EditProposal,
  PortfolioMetrics,
  ReviewDecision
} from './types.js';

const require = createRequire(import.meta.url);
const { DatabaseSync } = require('node:sqlite');

export interface SweepRecord {
  id: string;
  created_at: string;
  provider: string;
  total_articles: number;
  affected_articles: number;
  freshness_score: number;
  cost: number;
  metrics: PortfolioMetrics;
}

export interface AgentCheckpoint {
  id: string;
  thread_id: string;
  current_step: string;
  is_interrupted: boolean;
  state_json: string;
  created_at: string;
  updated_at: string;
}

export class KnowledgeBaseDatabase {
  private db: any;

  constructor(dbPath: string = ':memory:') {
    if (dbPath !== ':memory:') {
      const dir = path.dirname(dbPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }
    this.db = new DatabaseSync(dbPath);
    this.initSchema();
  }

  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS articles (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT,
        screenshots_json TEXT,
        last_updated TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS change_events (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        before_state_json TEXT NOT NULL,
        after_state_json TEXT NOT NULL,
        effective_date TEXT NOT NULL,
        source TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS sweeps (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        provider TEXT NOT NULL,
        total_articles INTEGER NOT NULL,
        affected_articles INTEGER NOT NULL,
        freshness_score REAL NOT NULL,
        cost REAL NOT NULL,
        metrics_json TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS proposals (
        id TEXT PRIMARY KEY,
        sweep_id TEXT,
        article_id TEXT NOT NULL,
        change_id TEXT NOT NULL,
        original_content TEXT NOT NULL,
        proposed_content TEXT NOT NULL,
        changed_spans_json TEXT NOT NULL,
        rationale TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        confidence TEXT NOT NULL,
        status TEXT NOT NULL,
        structural_preservation_ratio REAL NOT NULL,
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewer TEXT,
        review_notes TEXT,
        FOREIGN KEY(article_id) REFERENCES articles(id)
      );

      CREATE TABLE IF NOT EXISTS review_audit_log (
        id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        notes TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(proposal_id) REFERENCES proposals(id)
      );

      CREATE TABLE IF NOT EXISTS agent_checkpoints (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL UNIQUE,
        current_step TEXT NOT NULL,
        is_interrupted INTEGER NOT NULL DEFAULT 0,
        state_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
    `);
  }

  public saveArticle(article: Article): void {
    const stmt = this.db.prepare(`
      INSERT INTO articles (id, title, content, version, metadata_json, screenshots_json, last_updated)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        title = excluded.title,
        content = excluded.content,
        version = excluded.version,
        metadata_json = excluded.metadata_json,
        screenshots_json = excluded.screenshots_json,
        last_updated = excluded.last_updated
    `);
    stmt.run(
      article.id,
      article.title,
      article.content,
      article.version,
      JSON.stringify(article.metadata),
      JSON.stringify(article.screenshots),
      article.last_updated
    );
  }

  public getArticles(): Article[] {
    const stmt = this.db.prepare('SELECT * FROM articles');
    const rows = stmt.all() as any[];
    return rows.map(r => ({
      id: r.id,
      title: r.title,
      content: r.content,
      version: r.version,
      metadata: JSON.parse(r.metadata_json || '{}'),
      screenshots: JSON.parse(r.screenshots_json || '[]'),
      last_updated: r.last_updated
    }));
  }

  public saveSweep(sweep: SweepRecord): void {
    const stmt = this.db.prepare(`
      INSERT INTO sweeps (id, created_at, provider, total_articles, affected_articles, freshness_score, cost, metrics_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(
      sweep.id,
      sweep.created_at,
      sweep.provider,
      sweep.total_articles,
      sweep.affected_articles,
      sweep.freshness_score,
      sweep.cost,
      JSON.stringify(sweep.metrics)
    );
  }

  public getSweeps(): SweepRecord[] {
    const stmt = this.db.prepare('SELECT * FROM sweeps ORDER BY created_at DESC');
    const rows = stmt.all() as any[];
    return rows.map(r => ({
      id: r.id,
      created_at: r.created_at,
      provider: r.provider,
      total_articles: r.total_articles,
      affected_articles: r.affected_articles,
      freshness_score: r.freshness_score,
      cost: r.cost,
      metrics: JSON.parse(r.metrics_json)
    }));
  }

  public saveProposal(proposal: EditProposal, sweepId?: string): void {
    const stmt = this.db.prepare(`
      INSERT INTO proposals (
        id, sweep_id, article_id, change_id, original_content, proposed_content,
        changed_spans_json, rationale, evidence_json, confidence, status,
        structural_preservation_ratio, created_at, reviewed_at, reviewer, review_notes
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        status = excluded.status,
        reviewed_at = excluded.reviewed_at,
        reviewer = excluded.reviewer,
        review_notes = excluded.review_notes
    `);
    stmt.run(
      proposal.id,
      sweepId || null,
      proposal.article_id,
      proposal.change_id,
      proposal.original_content,
      proposal.proposed_content,
      JSON.stringify(proposal.changed_spans),
      proposal.rationale,
      JSON.stringify(proposal.evidence),
      proposal.confidence,
      proposal.status,
      proposal.structural_preservation_ratio,
      proposal.created_at,
      proposal.reviewed_at || null,
      proposal.reviewer || null,
      proposal.review_notes || null
    );
  }

  public getProposals(status?: string): EditProposal[] {
    let sql = 'SELECT * FROM proposals';
    const params: any[] = [];
    if (status) {
      sql += ' WHERE status = ?';
      params.push(status);
    }
    const stmt = this.db.prepare(sql);
    const rows = (params.length > 0 ? stmt.all(params[0]) : stmt.all()) as any[];
    return rows.map(r => ({
      id: r.id,
      article_id: r.article_id,
      change_id: r.change_id,
      original_content: r.original_content,
      proposed_content: r.proposed_content,
      changed_spans: JSON.parse(r.changed_spans_json),
      rationale: r.rationale,
      evidence: JSON.parse(r.evidence_json),
      confidence: r.confidence,
      status: r.status,
      structural_preservation_ratio: r.structural_preservation_ratio,
      created_at: r.created_at,
      reviewed_at: r.reviewed_at || undefined,
      reviewer: r.reviewer || undefined,
      review_notes: r.review_notes || undefined
    }));
  }

  public recordReviewDecision(decision: ReviewDecision): void {
    const logId = `audit-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const logStmt = this.db.prepare(`
      INSERT INTO review_audit_log (id, proposal_id, decision, reviewer, notes, timestamp)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    logStmt.run(
      logId,
      decision.proposal_id,
      decision.decision,
      decision.reviewer,
      decision.notes || null,
      decision.timestamp
    );

    const updateProposal = this.db.prepare(`
      UPDATE proposals
      SET status = ?, reviewed_at = ?, reviewer = ?, review_notes = ?
      WHERE id = ?
    `);
    updateProposal.run(
      decision.decision,
      decision.timestamp,
      decision.reviewer,
      decision.notes || null,
      decision.proposal_id
    );
  }

  public saveCheckpoint(threadId: string, step: string, isInterrupted: boolean, state: any): void {
    const checkpointId = `chk-${threadId}-${Date.now().toString(36)}`;
    const now = new Date().toISOString();
    const stmt = this.db.prepare(`
      INSERT INTO agent_checkpoints (id, thread_id, current_step, is_interrupted, state_json, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(thread_id) DO UPDATE SET
        current_step = excluded.current_step,
        is_interrupted = excluded.is_interrupted,
        state_json = excluded.state_json,
        updated_at = excluded.updated_at
    `);
    stmt.run(
      checkpointId,
      threadId,
      step,
      isInterrupted ? 1 : 0,
      JSON.stringify(state),
      now,
      now
    );
  }

  public getCheckpoint(threadId: string): AgentCheckpoint | null {
    const stmt = this.db.prepare('SELECT * FROM agent_checkpoints WHERE thread_id = ?');
    const row = stmt.get(threadId) as any;
    if (!row) return null;
    return {
      id: row.id,
      thread_id: row.thread_id,
      current_step: row.current_step,
      is_interrupted: Boolean(row.is_interrupted),
      state_json: row.state_json,
      created_at: row.created_at,
      updated_at: row.updated_at
    };
  }

  public close(): void {
    this.db.close();
  }
}
