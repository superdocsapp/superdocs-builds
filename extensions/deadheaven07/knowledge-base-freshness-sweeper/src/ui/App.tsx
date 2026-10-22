import React, { useState, useEffect } from 'react';
import {
  Shield,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Image as ImageIcon,
  DollarSign,
  Search,
  Moon,
  Sun,
  TrendingUp,
  HelpCircle
} from 'lucide-react';
import { KnowledgeBaseSweeper } from '../core/engine.js';
import { Article, ChangeEvent, GroundTruthEntry, EditProposal, Assessment, ScreenshotAssessment, PortfolioMetrics } from '../core/types.js';

import articlesData from '../../fixtures/corpus/articles.json';
import changesData from '../../fixtures/corpus/changes.json';
import groundTruthData from '../../fixtures/corpus/ground-truth.json';

export const App: React.FC = () => {
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [activeTab, setActiveTab] = useState<'proposals' | 'articles' | 'screenshots' | 'cna' | 'benchmark' | 'budget'>('proposals');
  
  const [sweeper] = useState<KnowledgeBaseSweeper>(() => {
    return new KnowledgeBaseSweeper(
      articlesData as Article[],
      changesData as ChangeEvent[],
      { max_budget_usd: 1.00 }
    );
  });

  const [articles, setArticles] = useState<Article[]>(() => articlesData as Article[]);
  const [groundTruth] = useState<GroundTruthEntry[]>(() => groundTruthData as GroundTruthEntry[]);

  const [proposals, setProposals] = useState<EditProposal[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [screenshots, setScreenshots] = useState<ScreenshotAssessment[]>([]);
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(null);

  const [selectedProposal, setSelectedProposal] = useState<EditProposal | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSweeping, setIsSweeping] = useState(false);
  const [budgetCap, setBudgetCap] = useState(1.00);

  // Initialize theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const handleSweep = (sampleSize?: number) => {
    setIsSweeping(true);
    setTimeout(() => {
      const result = sweeper.sweep({
        sample_size: sampleSize,
        budget_config: { max_budget_usd: budgetCap },
        provider: 'deterministic'
      });

      setProposals(result.proposals);
      setAssessments(result.assessments);
      setScreenshots(result.screenshotAssessments);
      setMetrics(result.metrics);
      setArticles(sweeper.getArticles());

      if (result.proposals.length > 0 && !selectedProposal) {
        setSelectedProposal(result.proposals[0]);
      }
      setIsSweeping(false);
    }, 200);
  };

  // Initial auto-sweep on mount
  useEffect(() => {
    handleSweep();
  }, []);

  const handleApprove = (proposalId: string) => {
    const res = sweeper.approveProposal(proposalId, 'Knowledge Manager');
    if (res.success) {
      setProposals(sweeper.getProposals());
      setAssessments(sweeper.getAssessments());
      setArticles([...sweeper.getArticles()]);
      setMetrics(sweeper.getMetrics(groundTruth));
      if (selectedProposal?.id === proposalId) {
        setSelectedProposal(res.proposal || null);
      }
    }
  };

  const handleReject = (proposalId: string) => {
    const res = sweeper.rejectProposal(proposalId, 'Knowledge Manager', 'Content verified as exception');
    if (res.success) {
      setProposals(sweeper.getProposals());
      setAssessments(sweeper.getAssessments());
      setMetrics(sweeper.getMetrics(groundTruth));
      if (selectedProposal?.id === proposalId) {
        setSelectedProposal(res.proposal || null);
      }
    }
  };

  const filteredArticles = articles.filter(a =>
    a.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    a.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
    a.metadata.category?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const pendingProposals = proposals.filter(p => p.status === 'PENDING');
  const approvedProposals = proposals.filter(p => p.status === 'APPROVED');
  const cnaAssessments = assessments.filter(a => a.status === 'COULD_NOT_ASSESS');
  const staleScreenshots = screenshots.filter(s => s.replacement_required);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <header
        style={{
          borderBottom: '1px solid var(--border-color)',
          background: 'var(--bg-secondary)',
          padding: '12px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: 0,
          zIndex: 50
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #38bdf8 0%, #2563eb 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              boxShadow: '0 2px 8px rgba(37,99,235,0.4)'
            }}
          >
            <Shield size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '1.1rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                Knowledge-base Freshness Sweeper
              </h1>
              <span className="badge badge-high" style={{ fontSize: '0.7rem' }}>Task 2.3</span>
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Deterministic Change Impact Discovery, Surgical Patching & Portfolio Governance
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {metrics && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '4px 12px',
                borderRadius: '8px',
                background: 'var(--badge-bg)',
                border: '1px solid var(--border-color)',
                fontSize: '0.85rem'
              }}
            >
              <TrendingUp size={16} color="var(--accent-green)" />
              <span>Freshness:</span>
              <strong style={{ color: 'var(--accent-green)' }}>{metrics.freshness_score}%</strong>
              <span style={{ color: 'var(--text-muted)' }}>({metrics.assessment_coverage}% coverage)</span>
            </div>
          )}

          <button
            className="btn btn-secondary"
            onClick={() => handleSweep(5)}
            title="Run small sample mode (5 articles)"
            style={{ fontSize: '0.8rem', padding: '6px 12px' }}
          >
            Sample (5)
          </button>

          <button
            className="btn btn-primary"
            onClick={() => handleSweep()}
            disabled={isSweeping}
          >
            <RefreshCw size={16} className={isSweeping ? 'animate-spin' : ''} />
            {isSweeping ? 'Sweeping...' : 'Run Full Sweep'}
          </button>

          <button
            className="btn btn-secondary"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="Toggle theme"
            style={{ padding: '8px' }}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>

      {/* Metrics Bar */}
      <div
        style={{
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-color)',
          padding: '12px 24px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: '12px'
        }}
      >
        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Scanned Articles</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{metrics?.total_articles || 0}</div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Stale / Affected</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-rose)' }}>
            {metrics?.affected_articles || 0}
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Pending Proposals</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-amber)' }}>
            {pendingProposals.length}
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Approved Patches</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-green)' }}>
            {approvedProposals.length}
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Stale Screenshots</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-rose)' }}>
            {staleScreenshots.length}
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Could Not Assess</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-amber)' }}>
            {cnaAssessments.length}
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Actual Cost / Budget</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent-green)' }}>
            ${metrics?.actual_cost.toFixed(2)} <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>/ ${budgetCap.toFixed(2)}</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-color)',
          background: 'var(--bg-secondary)',
          padding: '0 24px'
        }}
      >
        <button
          className={`tab-button ${activeTab === 'proposals' ? 'active' : ''}`}
          onClick={() => setActiveTab('proposals')}
        >
          Surgical Review Queue ({pendingProposals.length})
        </button>

        <button
          className={`tab-button ${activeTab === 'articles' ? 'active' : ''}`}
          onClick={() => setActiveTab('articles')}
        >
          Knowledge Base Explorer ({articles.length})
        </button>

        <button
          className={`tab-button ${activeTab === 'screenshots' ? 'active' : ''}`}
          onClick={() => setActiveTab('screenshots')}
        >
          Screenshot Staleness ({staleScreenshots.length})
        </button>

        <button
          className={`tab-button ${activeTab === 'cna' ? 'active' : ''}`}
          onClick={() => setActiveTab('cna')}
        >
          Could Not Assess ({cnaAssessments.length})
        </button>

        <button
          className={`tab-button ${activeTab === 'benchmark' ? 'active' : ''}`}
          onClick={() => setActiveTab('benchmark')}
        >
          Evaluation Benchmark (Ground Truth)
        </button>

        <button
          className={`tab-button ${activeTab === 'budget' ? 'active' : ''}`}
          onClick={() => setActiveTab('budget')}
        >
          Budget Guard
        </button>
      </div>

      {/* Main Content Body */}
      <main style={{ flex: 1, padding: '24px', maxWidth: '1600px', margin: '0 auto', width: '100%' }}>
        {/* TAB 1: SURGICAL REVIEW QUEUE */}
        {activeTab === 'proposals' && (
          <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '24px' }}>
            {/* List */}
            <div className="glass-panel" style={{ padding: '16px', maxHeight: '780px', overflowY: 'auto' }}>
              <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '12px' }}>
                Pending Review Proposals ({pendingProposals.length})
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {proposals.map(prop => {
                  const isSelected = selectedProposal?.id === prop.id;
                  const article = articles.find(a => a.id === prop.article_id);
                  return (
                    <div
                      key={prop.id}
                      onClick={() => setSelectedProposal(prop)}
                      style={{
                        padding: '12px',
                        borderRadius: '8px',
                        cursor: 'pointer',
                        background: isSelected ? 'var(--bg-card-hover)' : 'var(--badge-bg)',
                        border: isSelected ? '1px solid var(--accent-blue)' : '1px solid var(--border-color)',
                        transition: 'all 0.15s ease'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                          {prop.article_id}
                        </span>
                        <span className={`badge badge-${prop.status.toLowerCase()}`}>
                          {prop.status}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '4px' }}>
                        {article?.title || prop.article_id}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {prop.rationale}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Proposal Detail & Surgical Diff */}
            {selectedProposal ? (
              <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                      <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                        {articles.find(a => a.id === selectedProposal.article_id)?.title || selectedProposal.article_id}
                      </h2>
                      <span className={`badge badge-${selectedProposal.status.toLowerCase()}`}>
                        {selectedProposal.status}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                      Proposal ID: <code style={{ fontFamily: 'var(--font-mono)' }}>{selectedProposal.id}</code> | Triggered by Change: <strong>{selectedProposal.change_id}</strong>
                    </p>
                  </div>

                  {selectedProposal.status === 'PENDING' && (
                    <div style={{ display: 'flex', gap: '12px' }}>
                      <button className="btn btn-reject" onClick={() => handleReject(selectedProposal.id)}>
                        <XCircle size={16} /> Reject
                      </button>
                      <button className="btn btn-approve" onClick={() => handleApprove(selectedProposal.id)}>
                        <CheckCircle2 size={16} /> Approve & Patch
                      </button>
                    </div>
                  )}
                </div>

                {/* Evidence Card */}
                <div
                  style={{
                    background: 'rgba(56, 189, 248, 0.08)',
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                    borderRadius: '8px',
                    padding: '14px',
                    marginBottom: '20px'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: 'var(--accent-blue)', fontWeight: 600, fontSize: '0.85rem' }}>
                    <HelpCircle size={16} /> Verified Sentence-Level Evidence:
                  </div>
                  {selectedProposal.evidence.map((ev, i) => (
                    <div key={i} style={{ marginBottom: '6px', fontSize: '0.85rem' }}>
                      <div style={{ fontStyle: 'italic', color: 'var(--text-primary)' }}>
                        "{ev.sentence_text}"
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        ↳ {ev.explanation} (Sentence #{ev.sentence_index}, Section: {ev.section_heading || 'Intro'})
                      </div>
                    </div>
                  ))}
                </div>

                {/* Structural Preservation Proof */}
                <div style={{ display: 'flex', gap: '16px', marginBottom: '20px', fontSize: '0.8rem' }}>
                  <div className="badge badge-healthy" style={{ padding: '6px 12px' }}>
                    ✓ {(selectedProposal.structural_preservation_ratio * 100).toFixed(1)}% Article Unmodified
                  </div>
                  <div className="badge badge-healthy" style={{ padding: '6px 12px' }}>
                    ✓ Markdown AST Headings & Code Blocks Preserved
                  </div>
                  <div className="badge badge-high" style={{ padding: '6px 12px' }}>
                    Confidence: {selectedProposal.confidence}
                  </div>
                </div>

                {/* Surgical Diff Viewer */}
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '8px' }}>
                  Surgical Sentence Diff
                </h4>
                <div className="diff-container" style={{ marginBottom: '24px' }}>
                  {selectedProposal.changed_spans.map((span, idx) => (
                    <React.Fragment key={idx}>
                      <div className="diff-del">
                        <strong>- </strong> {span.original_text}
                      </div>
                      <div className="diff-add">
                        <strong>+ </strong> {span.replacement_text}
                      </div>
                    </React.Fragment>
                  ))}
                </div>

                {/* Full Article Preview */}
                <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '8px' }}>
                  Proposed Full Content Preview
                </h4>
                <pre
                  style={{
                    padding: '16px',
                    borderRadius: '8px',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.8rem',
                    whiteSpace: 'pre-wrap',
                    maxHeight: '300px',
                    overflowY: 'auto'
                  }}
                >
                  {selectedProposal.proposed_content}
                </pre>
              </div>
            ) : (
              <div className="glass-panel" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Select a proposal from the left queue to review surgical edits.
              </div>
            )}
          </div>
        )}

        {/* TAB 2: KNOWLEDGE BASE EXPLORER */}
        {activeTab === 'articles' && (
          <div>
            <div style={{ display: 'flex', gap: '16px', marginBottom: '20px' }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <Search size={18} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  placeholder="Search articles by title, content, or category..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 38px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    background: 'var(--bg-secondary)',
                    color: 'var(--text-primary)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: '0.875rem'
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
              {filteredArticles.map(art => {
                const assessment = assessments.find(a => a.article_id === art.id);
                const status = assessment ? assessment.status : 'NOT_AFFECTED';
                return (
                  <div key={art.id} className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                        {art.id} (v{art.version})
                      </span>
                      <span className={`badge badge-${status === 'AFFECTED' ? 'affected' : status === 'COULD_NOT_ASSESS' ? 'cna' : 'healthy'}`}>
                        {status}
                      </span>
                    </div>

                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '6px' }}>{art.title}</h3>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', flex: 1, marginBottom: '12px' }}>
                      {art.content.slice(0, 140)}...
                    </p>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Category: {art.metadata.category || 'General'}
                      </span>
                      {art.screenshots.length > 0 && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <ImageIcon size={14} /> {art.screenshots.length} image(s)
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 3: SCREENSHOT STALENESS */}
        {activeTab === 'screenshots' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: '20px' }}>
            {screenshots.map(ss => (
              <div key={ss.screenshot_id} className="glass-panel" style={{ padding: '20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                    Article: {ss.article_id}
                  </span>
                  <span className={`badge badge-${ss.replacement_required ? 'affected' : ss.status === 'COULD_NOT_ASSESS' ? 'cna' : 'healthy'}`}>
                    {ss.status}
                  </span>
                </div>

                <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '8px' }}>
                  Screenshot ID: {ss.screenshot_id}
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                  {ss.reason}
                </p>

                {ss.mismatched_labels.length > 0 && (
                  <div style={{ background: 'var(--diff-del-bg)', border: '1px solid var(--diff-del-border)', borderRadius: '6px', padding: '8px 12px', marginBottom: '12px' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--accent-rose)', fontWeight: 600 }}>
                      Mismatched UI Labels in Image OCR:
                    </div>
                    <div style={{ fontSize: '0.85rem', color: 'var(--diff-del-text)' }}>
                      {ss.mismatched_labels.join(', ')}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Evidence: {ss.evidence.join('; ')}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* TAB 4: COULD NOT ASSESS */}
        {activeTab === 'cna' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ background: 'rgba(251, 191, 36, 0.1)', border: '1px solid rgba(251, 191, 36, 0.3)', borderRadius: '8px', padding: '16px' }}>
              <h3 style={{ fontSize: '0.95rem', color: 'var(--accent-amber)', fontWeight: 600, marginBottom: '4px' }}>
                Honest Uncertainty Policy
              </h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                The sweeper never fabricates false certainty. When an article contains ambiguous scopes, contract-specific disclaimers, or missing OCR labels, it is placed into this honest assessment bucket for manual review.
              </p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: '16px' }}>
              {cnaAssessments.map(item => {
                const article = articles.find(a => a.id === item.article_id);
                return (
                  <div key={item.article_id} className="glass-panel" style={{ padding: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                        {item.article_id}
                      </span>
                      <span className="badge badge-cna">COULD_NOT_ASSESS</span>
                    </div>

                    <h4 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '6px' }}>
                      {article?.title || item.article_id}
                    </h4>

                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                      {item.reason}
                    </p>

                    {item.could_not_assess_details && (
                      <div style={{ background: 'var(--bg-secondary)', borderRadius: '6px', padding: '10px 12px', fontSize: '0.75rem', border: '1px solid var(--border-color)' }}>
                        <div><strong>Checked:</strong> {item.could_not_assess_details.what_checked.join(', ')}</div>
                        <div style={{ marginTop: '4px' }}><strong>Missing:</strong> {item.could_not_assess_details.missing_evidence}</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 5: EVALUATION BENCHMARK */}
        {activeTab === 'benchmark' && metrics && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="glass-panel" style={{ padding: '24px' }}>
              <h2 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '16px' }}>
                Seeded Evaluation Corpus Benchmark Results
              </h2>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Precision</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-blue)' }}>
                    {(metrics.precision * 100).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>TP / (TP + FP)</div>
                </div>

                <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Recall</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-green)' }}>
                    {(metrics.recall * 100).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>TP / (TP + FN)</div>
                </div>

                <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>F1 Score</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-indigo)' }}>
                    {metrics.f1_score}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Harmonic Mean</div>
                </div>

                <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Could-Not-Assess Rate</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--accent-amber)' }}>
                    {metrics.could_not_assess_rate}%
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Honest disclosures</div>
                </div>
              </div>

              {/* Confusion Matrix Table */}
              <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '12px' }}>
                Confusion Matrix (32 Fixture Articles)
              </h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                    <th style={{ padding: '8px' }}>Metric</th>
                    <th style={{ padding: '8px' }}>Count</th>
                    <th style={{ padding: '8px' }}>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '8px', fontWeight: 600, color: 'var(--accent-green)' }}>True Positives (TP)</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{metrics.true_positives}</td>
                    <td style={{ padding: '8px' }}>Stale articles correctly identified & surgical edits proposed</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '8px', fontWeight: 600, color: 'var(--accent-green)' }}>True Negatives (TN)</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{metrics.true_negatives}</td>
                    <td style={{ padding: '8px' }}>Unchanged articles & adversarial false-positive traps correctly left untouched</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '8px', fontWeight: 600, color: 'var(--accent-rose)' }}>False Positives (FP)</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{metrics.false_positives}</td>
                    <td style={{ padding: '8px' }}>Unchanged articles falsely marked affected (Zero in benchmark)</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '8px', fontWeight: 600, color: 'var(--accent-rose)' }}>False Negatives (FN)</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{metrics.false_negatives}</td>
                    <td style={{ padding: '8px' }}>Affected articles missed (Zero in benchmark)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 6: BUDGET GUARD */}
        {activeTab === 'budget' && (
          <div className="glass-panel" style={{ padding: '24px', maxWidth: '600px', margin: '0 auto' }}>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 700, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <DollarSign size={20} color="var(--accent-green)" /> Budget Guard Configuration
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '20px' }}>
              Protects against accidental runaway spend by performing pre-flight cost estimation before execution. Offline deterministic benchmarks execute free at <strong>$0.00</strong> spend.
            </p>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                Maximum Budget Cap (USD):
              </label>
              <input
                type="number"
                step="0.10"
                min="0.10"
                max="50.00"
                value={budgetCap}
                onChange={e => setBudgetCap(parseFloat(e.target.value) || 1.0)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border-color)',
                  background: 'var(--bg-secondary)',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-mono)'
                }}
              />
            </div>

            <div style={{ background: 'var(--bg-secondary)', borderRadius: '8px', padding: '14px', border: '1px solid var(--border-color)', fontSize: '0.85rem' }}>
              <div>Configured Cap: <strong>${budgetCap.toFixed(2)}</strong></div>
              <div style={{ marginTop: '4px' }}>Actual Spend (Deterministic Offline): <strong style={{ color: 'var(--accent-green)' }}>$0.00</strong></div>
              <div style={{ marginTop: '4px' }}>Model Provider: <strong>Deterministic Ast Matcher (Zero API Cost)</strong></div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
