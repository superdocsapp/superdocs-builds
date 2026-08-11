import { useState, useEffect, useRef } from 'react';
import { api } from './api';
import type { Dossier, DossierFinding, Document, AccessibilityAudit, DossierMetrics } from './types';
import './App.css';

type View =
  | { type: 'dashboard' }
  | { type: 'dossier-detail'; dossierId: string }
  | { type: 'finding-review'; dossierId: string; findingId: string }
  | { type: 'create-dossier' }
  | { type: 'data-room' }
  | { type: 'accessibility' };

interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

export default function App() {
  const [view, setView] = useState<View>({ type: 'dashboard' });
  const [history, setHistory] = useState<View[]>([]);
  const [investorMode, setInvestorMode] = useState(false);
  
  // Data States
  const [dossiers, setDossiers] = useState<Dossier[]>([]);
  const [currentDossier, setCurrentDossier] = useState<Dossier | null>(null);
  const [currentFinding, setCurrentFinding] = useState<DossierFinding | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [dossierMetrics, setDossierMetrics] = useState<DossierMetrics | null>(null);
  
  // Accessibility States
  const [accessRawText, setAccessRawText] = useState('');
  const [accessAudit, setAccessAudit] = useState<AccessibilityAudit | null>(null);
  const [accessAltOverrides, setAccessAltOverrides] = useState<Record<string, string>>({});
  const [accessRemediatedHtml, setAccessRemediatedHtml] = useState('');
  const [accessReport, setAccessReport] = useState('');
  const [accessFile, setAccessFile] = useState<File | null>(null);
  
  // Loading & Error States
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  
  // Modal States
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [showRetryModal, setShowRetryModal] = useState(false);
  
  // Edit Mode States
  const [isEditing, setIsEditing] = useState(false);
  const [editAnswer, setEditAnswer] = useState('');
  const [editReasoning, setEditReasoning] = useState('');

  // Form State for creating dossier
  const [newDossierName, setNewDossierName] = useState('');
  const [newQuestionText, setNewQuestionText] = useState('');
  const [newQuestionsList, setNewQuestionsList] = useState<string[]>([]);
  
  // File Upload Reference
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Navigation Helper
  const navigateTo = (newView: View) => {
    setHistory((prev) => [...prev, view]);
    setView(newView);
  };

  const navigateBack = () => {
    if (history.length > 0) {
      const prev = history[history.length - 1];
      setHistory(history.slice(0, -1));
      setView(prev);
    } else {
      setView({ type: 'dashboard' });
    }
  };

  // Toast Helpers
  const addToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      removeToast(id);
    }, 4000);
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Refresh data based on view
  useEffect(() => {
    if (view.type === 'dashboard') {
      fetchDossiers();
    } else if (view.type === 'dossier-detail') {
      fetchDossierDetails(view.dossierId);
    } else if (view.type === 'finding-review') {
      fetchFindingDetails(view.dossierId, view.findingId);
    } else if (view.type === 'data-room') {
      fetchDocuments();
    }
  }, [view]);

  // Periodic polling for running dossiers
  useEffect(() => {
    let interval: any;
    const hasRunningDossiers = dossiers.some((d) => d.status === 'running' || d.status === 'pending');
    const isDetailViewRunning = view.type === 'dossier-detail' && currentDossier?.status === 'running';

    if (hasRunningDossiers || isDetailViewRunning) {
      interval = setInterval(() => {
        if (view.type === 'dossier-detail' && currentDossier) {
          fetchDossierDetails(currentDossier.id, true);
        } else if (view.type === 'dashboard') {
          fetchDossiers(true);
        }
      }, 3000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [dossiers, view, currentDossier]);

  // API Actions
  const fetchDossiers = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await api.getDossiers();
      setDossiers(data);
    } catch (err: any) {
      addToast(err.message || 'Failed to load dossiers', 'error');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const fetchDossierDetails = async (dossierId: string, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await api.getDossier(dossierId);
      setCurrentDossier(data);
      try {
        const metricsData = await api.getDossierMetrics(dossierId);
        setDossierMetrics(metricsData);
      } catch (metricsErr) {
        console.warn('Failed to load metrics', metricsErr);
      }
    } catch (err: any) {
      addToast(err.message || 'Failed to load dossier details', 'error');
      setView({ type: 'dashboard' });
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const fetchFindingDetails = async (dossierId: string, findingId: string) => {
    setLoading(true);
    try {
      const data = await api.getDossierFinding(dossierId, findingId);
      setCurrentFinding(data);
      setEditAnswer(data.answer || '');
      setEditReasoning(data.reasoning_summary || '');
    } catch (err: any) {
      addToast(err.message || 'Failed to load finding details', 'error');
    } finally {
      setLoading(false);
    }
  };

  const fetchDocuments = async () => {
    setLoading(true);
    try {
      const data = await api.getDocuments();
      setDocuments(data);
    } catch (err: any) {
      addToast(err.message || 'Failed to load documents', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateDossier = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDossierName.trim()) {
      addToast('Dossier name is required', 'error');
      return;
    }
    if (newQuestionsList.length === 0) {
      addToast('At least one diligence question must be added', 'error');
      return;
    }

    setSubmitting(true);
    try {
      const dossier = await api.createDossier(newDossierName.trim());
      await api.addQuestions(dossier.id, newQuestionsList);
      const updated = await api.runDossier(dossier.id);
      addToast('Dossier created and execution started successfully!', 'success');
      
      // Reset form
      setNewDossierName('');
      setNewQuestionsList([]);
      
      // Navigate to detail
      setView({ type: 'dossier-detail', dossierId: updated.id });
    } catch (err: any) {
      addToast(err.message || 'Failed to create dossier', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleExportDossier = async () => {
    if (!currentDossier) return;
    setLoading(true);
    try {
      const md = await api.exportDossier(currentDossier.id);
      const blob = new Blob([md], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${currentDossier.name.replace(/\s+/g, '_')}_diligence_report.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      addToast('Dossier Markdown report downloaded successfully!', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to export dossier', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRunDossier = async () => {
    if (!currentDossier) return;
    setSubmitting(true);
    try {
      const updated = await api.runDossier(currentDossier.id);
      setCurrentDossier(updated);
      addToast('Dossier execution loop triggered', 'info');
    } catch (err: any) {
      addToast(err.message || 'Failed to run dossier findings', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleApproveFinding = async () => {
    if (!currentDossier || !currentFinding) return;
    setSubmitting(true);
    try {
      const updated = await api.approveFinding(currentDossier.id, currentFinding.id);
      setCurrentFinding(updated);
      addToast('Finding response approved successfully', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to approve finding', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRejectFinding = async () => {
    if (!currentDossier || !currentFinding) return;
    if (!rejectReason.trim()) {
      addToast('Rejection reason is required', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const updated = await api.rejectFinding(currentDossier.id, currentFinding.id, rejectReason.trim());
      setCurrentFinding(updated);
      setShowRejectModal(false);
      setRejectReason('');
      addToast('Finding response rejected successfully', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to reject finding', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleEditFinding = async () => {
    if (!currentDossier || !currentFinding) return;
    if (!editAnswer.trim() || !editReasoning.trim()) {
      addToast('Answer and reasoning summary cannot be empty', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const updated = await api.editFinding(
        currentDossier.id,
        currentFinding.id,
        editAnswer.trim(),
        editReasoning.trim()
      );
      setCurrentFinding(updated);
      setIsEditing(false);
      addToast('Finding manually overridden and saved successfully', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to save edits', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetryFinding = async () => {
    if (!currentDossier || !currentFinding) return;
    setSubmitting(true);
    try {
      const updated = await api.retryFinding(currentDossier.id, currentFinding.id);
      setCurrentFinding(updated);
      setShowRetryModal(false);
      addToast('New execution thread initiated for this finding', 'info');
      // Navigate back to dossier details to track progress
      setView({ type: 'dossier-detail', dossierId: currentDossier.id });
    } catch (err: any) {
      addToast(err.message || 'Failed to retry finding execution', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    
    setLoading(true);
    try {
      await api.uploadDocument(file);
      addToast(`Document '${file.name}' uploaded and queued for parsing`, 'success');
      fetchDocuments();
    } catch (err: any) {
      addToast(err.message || 'File upload failed', 'error');
    } finally {
      setLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleAccessibilityUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    setAccessFile(file);
    setLoading(true);
    try {
      const audit = await api.checkAccessibility(file);
      setAccessAudit(audit);
      setAccessRawText(audit.original_text);
      const initialOverrides: Record<string, string> = {};
      audit.detected_images.forEach(img => {
        initialOverrides[img.url] = img.current_alt || '';
      });
      setAccessAltOverrides(initialOverrides);
      setAccessRemediatedHtml('');
      setAccessReport('');
      addToast('Document scanned for accessibility issues!', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to scan document', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleAccessibilityCheckText = async () => {
    if (!accessRawText.trim()) {
      addToast('Please enter document content first', 'error');
      return;
    }
    setLoading(true);
    try {
      const audit = await api.checkAccessibilityText(accessRawText);
      setAccessAudit(audit);
      const initialOverrides: Record<string, string> = {};
      audit.detected_images.forEach(img => {
        initialOverrides[img.url] = img.current_alt || '';
      });
      setAccessAltOverrides(initialOverrides);
      setAccessRemediatedHtml('');
      setAccessReport('');
      addToast('Text scanned for accessibility issues!', 'success');
    } catch (err: any) {
      addToast(err.message || 'Failed to scan text', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleAccessibilityRemediate = async () => {
    if (!accessRawText.trim()) {
      addToast('Please input document text first', 'error');
      return;
    }
    setLoading(true);
    try {
      const res = await api.remediateAccessibility(accessRawText, accessAltOverrides);
      setAccessRemediatedHtml(res.remediated_html);
      setAccessReport(res.plain_language_report);
      addToast('Accessibility fixes applied successfully!', 'success');
    } catch (err: any) {
      addToast(err.message || 'Remediation failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const downloadRemediatedHtml = () => {
    if (!accessRemediatedHtml) return;
    const blob = new Blob([accessRemediatedHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'accessibility_remediated_document.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    addToast('Remediated HTML downloaded!', 'success');
  };

  const downloadAccessibilityReport = () => {
    if (!accessReport) return;
    const blob = new Blob([accessReport], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'accessibility_audit_report.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    addToast('Accessibility report downloaded!', 'success');
  };

  const handleDeleteDocument = async (docId: string, filename: string) => {
    if (!confirm(`Are you sure you want to remove '${filename}' from the data room?`)) return;
    setLoading(true);
    try {
      await api.deleteDocument(docId);
      addToast('Document deleted successfully', 'success');
      fetchDocuments();
    } catch (err: any) {
      addToast(err.message || 'Failed to delete document', 'error');
    } finally {
      setLoading(false);
    }
  };

  // Helper calculation for Dossiers Stats
  const getStats = () => {
    const total = dossiers.length;
    const running = dossiers.filter((d) => d.status === 'running' || d.status === 'pending').length;
    const completed = dossiers.filter((d) => d.status === 'completed').length;
    const failed = dossiers.filter((d) => d.status === 'failed').length;
    const review = dossiers.filter((d) => d.status === 'review_required').length;
    return { total, running, completed, failed, review };
  };

  const stats = getStats();

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="navbar">
          <div className="brand" onClick={() => setView({ type: 'dashboard' })}>
            <div className="brand-logo">S</div>
            <div className="brand-name">SuperDocs Intelligence</div>
          </div>
          <nav className="nav-links">
            <div
              className={`nav-item ${view.type !== 'data-room' && view.type !== 'accessibility' ? 'active' : ''}`}
              onClick={() => setView({ type: 'dashboard' })}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="9" rx="1" />
                <rect x="14" y="3" width="7" height="5" rx="1" />
                <rect x="14" y="12" width="7" height="9" rx="1" />
                <rect x="3" y="16" width="7" height="5" rx="1" />
              </svg>
              Dossiers
            </div>
            <div
              className={`nav-item ${view.type === 'data-room' ? 'active' : ''}`}
              onClick={() => setView({ type: 'data-room' })}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                <path d="M6 6h10M6 10h10" />
              </svg>
              Data Room
            </div>
            <div
              className={`nav-item ${view.type === 'accessibility' ? 'active' : ''}`}
              onClick={() => setView({ type: 'accessibility' })}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 8v8M8 12h8" />
              </svg>
              Accessibility Tool
            </div>
          </nav>
          
          <div className="mode-toggle-switch" style={{ display: 'flex', gap: '0.25rem', padding: '0.25rem', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <button
              className={`btn btn-sm ${!investorMode ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', margin: 0, border: 'none', cursor: 'pointer' }}
              onClick={() => setInvestorMode(false)}
            >
              Founder Mode
            </button>
            <button
              className={`btn btn-sm ${investorMode ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', margin: 0, border: 'none', cursor: 'pointer' }}
              onClick={() => setInvestorMode(true)}
            >
              Investor Mode
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="main-content">
        {loading && (
          <div className="skeleton-container animate-fade-in" style={{ padding: '2rem 0' }}>
            <div className="skeleton-header"></div>
            <div className="skeleton-card"></div>
          </div>
        )}

        {!loading && (
          <>
            {/* VIEW: DASHBOARD */}
            {view.type === 'dashboard' && (
              <div className="animate-fade-in">
                <div className="section-header">
                  <div>
                    <h1 className="page-title">Diligence Dashboard</h1>
                    <div className="page-subtitle">Coordinate and audit batch startup diligence reviews</div>
                  </div>
                  {!investorMode && (
                    <button className="btn btn-primary" onClick={() => navigateTo({ type: 'create-dossier' })}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <line x1="12" y1="5" x2="12" y2="19"></line>
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                      </svg>
                      Create Dossier
                    </button>
                  )}
                </div>

                {/* Summary Statistics */}
                <div className="stats-grid">
                  <div className="stat-card" style={{ '--accent-color': 'var(--primary)' } as any}>
                    <div className="stat-label">Total Dossiers</div>
                    <div className="stat-value">{stats.total}</div>
                  </div>
                  <div className="stat-card" style={{ '--accent-color': 'var(--color-running)' } as any}>
                    <div className="stat-label">Running</div>
                    <div className="stat-value">{stats.running}</div>
                  </div>
                  <div className="stat-card" style={{ '--accent-color': 'var(--color-success)' } as any}>
                    <div className="stat-label">Completed</div>
                    <div className="stat-value">{stats.completed}</div>
                  </div>
                  <div className="stat-card" style={{ '--accent-color': 'var(--color-warning)' } as any}>
                    <div className="stat-label">Awaiting Review</div>
                    <div className="stat-value">{stats.review}</div>
                  </div>
                  <div className="stat-card" style={{ '--accent-color': 'var(--color-danger)' } as any}>
                    <div className="stat-label">Failed</div>
                    <div className="stat-value">{stats.failed}</div>
                  </div>
                </div>

                {/* Dossier List */}
                <h2 className="findings-list-header">Active Dossiers</h2>
                {dossiers.length === 0 ? (
                  <div className="review-card" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
                    <p style={{ color: 'var(--text-secondary)' }}>No dossiers found. Create a new dossier to begin diligence validation.</p>
                  </div>
                ) : (
                  <div className="dossiers-grid">
                    {dossiers.map((d) => {
                      const completedCount = d.findings.filter((f) => f.status === 'answered' || f.status === 'insufficient_evidence' || f.status === 'conflict').length;
                      const totalCount = d.findings.length;
                      const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
                      
                      return (
                        <div key={d.id} className="dossier-card animate-fade-in" onClick={() => navigateTo({ type: 'dossier-detail', dossierId: d.id })}>
                          <div className="dossier-card-header">
                            <h3 className="dossier-card-title">{d.name}</h3>
                            <span className={`badge badge-${d.status}`}>{d.status.replace('_', ' ')}</span>
                          </div>
                          
                          <div className="progress-container" style={{ margin: '1rem 0 1.5rem' }}>
                            <div className="progress-label-row">
                              <span>Progress</span>
                              <span>{progressPct}% ({completedCount}/{totalCount})</span>
                            </div>
                            <div className="progress-track">
                              <div className="progress-bar" style={{ width: `${progressPct}%` }}></div>
                            </div>
                          </div>

                          <div className="findings-count-summary">
                            <span>Questions: <strong>{totalCount}</strong></span>
                            <span>Review Required: <strong>{d.findings.filter(f => f.review_status === 'pending').length}</strong></span>
                          </div>

                          <div className="dossier-card-meta">
                            <span>ID: {d.id.substring(0, 8)}...</span>
                            <span>Updated: {new Date(d.updated_at).toLocaleDateString()}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* VIEW: CREATE DOSSIER */}
            {view.type === 'create-dossier' && (
              <div className="animate-fade-in">
                <div className="back-btn-container">
                  <button className="back-btn" onClick={navigateBack}>
                    &larr; Back to Dashboard
                  </button>
                </div>
                
                <h1 className="page-title" style={{ marginBottom: '1.5rem' }}>New Diligence Dossier</h1>
                
                <div className="create-form-container">
                  <form onSubmit={handleCreateDossier}>
                    <div className="form-group">
                      <label className="form-label" htmlFor="dossier-name">Dossier Name</label>
                      <input
                        id="dossier-name"
                        type="text"
                        className="form-input"
                        placeholder="e.g. Series A Due Diligence - Acme Corp"
                        value={newDossierName}
                        onChange={(e) => setNewDossierName(e.target.value)}
                        required
                        disabled={submitting}
                      />
                    </div>

                    <div className="form-group">
                      <label className="form-label">Diligence Questions</label>
                      <div className="questions-builder">
                        {newQuestionsList.length === 0 ? (
                          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: '0.5rem 0' }}>
                            No questions added yet. Enter questions below.
                          </p>
                        ) : (
                          <div style={{ marginBottom: '1rem' }}>
                            {newQuestionsList.map((q, idx) => (
                              <div key={idx} className="question-builder-item">
                                <span style={{ textAlign: 'left', flex: 1, paddingRight: '1rem' }}>
                                  {idx + 1}. {q}
                                </span>
                                <button
                                  type="button"
                                  className="action-icon-btn"
                                  onClick={() => setNewQuestionsList(prev => prev.filter((_, i) => i !== idx))}
                                  disabled={submitting}
                                  style={{ color: 'var(--color-danger)' }}
                                >
                                  Delete
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                        
                        <div className="question-builder-input-row">
                          <input
                            type="text"
                            className="form-input"
                            placeholder="Add a due diligence question..."
                            value={newQuestionText}
                            onChange={(e) => setNewQuestionText(e.target.value)}
                            disabled={submitting}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                if (newQuestionText.trim()) {
                                  setNewQuestionsList(prev => [...prev, newQuestionText.trim()]);
                                  setNewQuestionText('');
                                }
                              }
                            }}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => {
                              if (newQuestionText.trim()) {
                                setNewQuestionsList(prev => [...prev, newQuestionText.trim()]);
                                setNewQuestionText('');
                              }
                            }}
                            disabled={submitting}
                          >
                            Add
                          </button>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '1rem', marginTop: '2rem', justifyContent: 'flex-end' }}>
                      <button type="button" className="btn btn-secondary" onClick={navigateBack} disabled={submitting}>
                        Cancel
                      </button>
                      <button type="submit" className="btn btn-primary" disabled={submitting}>
                        {submitting ? 'Creating...' : 'Create & Initiate Run'}
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {/* VIEW: DOSSIER DETAIL */}
            {view.type === 'dossier-detail' && currentDossier && (
              <div className="animate-fade-in">
                {investorMode ? (
                  <>
                    <div className="back-btn-container">
                      <button className="back-btn" onClick={() => setView({ type: 'dashboard' })}>
                        &larr; Back to Dashboard
                      </button>
                    </div>

                    <div className="section-header" style={{ marginBottom: '1.5rem' }}>
                      <div>
                        <h1 className="page-title">{currentDossier.name} <span style={{ fontSize: '1rem', color: 'var(--primary)', marginLeft: '1rem' }}>(Investor View)</span></h1>
                        <div className="page-subtitle">Dossier ID: {currentDossier.id}</div>
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <span className={`badge badge-${currentDossier.status}`} style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
                          {currentDossier.status.replace('_', ' ')}
                        </span>
                        <button className="btn btn-primary" onClick={handleExportDossier} disabled={loading}>
                          Export Dossier (MD)
                        </button>
                      </div>
                    </div>

                    {/* Summary Statistics */}
                    <div className="stats-grid" style={{ marginBottom: '2rem' }}>
                      <div className="stat-card" style={{ '--accent-color': 'var(--primary)' } as any}>
                        <div className="stat-label">Total Findings</div>
                        <div className="stat-value">{currentDossier.findings.length}</div>
                      </div>
                      <div className="stat-card" style={{ '--accent-color': 'var(--color-success)' } as any}>
                        <div className="stat-label">Approved</div>
                        <div className="stat-value">
                          {currentDossier.findings.filter(f => f.review_status === 'approved' || f.review_status === 'edited').length}
                        </div>
                      </div>
                      <div className="stat-card" style={{ '--accent-color': 'var(--color-danger)' } as any}>
                        <div className="stat-label">Rejected</div>
                        <div className="stat-value">
                          {currentDossier.findings.filter(f => f.review_status === 'rejected').length}
                        </div>
                      </div>
                      <div className="stat-card" style={{ '--accent-color': 'var(--color-warning)' } as any}>
                        <div className="stat-label">Pending Review</div>
                        <div className="stat-value">
                          {currentDossier.findings.filter(f => f.review_status === 'pending').length}
                        </div>
                      </div>
                      <div className="stat-card" style={{ '--accent-color': 'var(--color-warning)' } as any}>
                        <div className="stat-label">Evidence Gaps</div>
                        <div className="stat-value">
                          {currentDossier.findings.filter(f => f.status === 'insufficient_evidence').length}
                        </div>
                      </div>
                      <div className="stat-card" style={{ '--accent-color': 'var(--color-danger)' } as any}>
                        <div className="stat-label">Conflicts</div>
                        <div className="stat-value">
                          {currentDossier.findings.filter(f => f.status === 'conflict').length}
                        </div>
                      </div>
                    </div>

                    {dossierMetrics && dossierMetrics.stages && dossierMetrics.stages.length > 0 && (
                      <div className="detail-card animate-fade-in" style={{ marginBottom: '2rem', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border)', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                        <h3 style={{ margin: '0 0 1rem', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-primary)' }}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <line x1="18" y1="20" x2="18" y2="10" />
                            <line x1="12" y1="20" x2="12" y2="4" />
                            <line x1="6" y1="20" x2="6" y2="14" />
                          </svg>
                          Workflow Execution & Cost Metrics
                        </h3>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Total Execution Time</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--primary)', marginTop: '0.25rem' }}>
                              {(dossierMetrics.total_duration_ms / 1000).toFixed(2)}s
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Estimated Token Usage</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                              {dossierMetrics.total_tokens.toLocaleString()} <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>(approx)</span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.1rem' }}>
                              In: {dossierMetrics.total_input_tokens.toLocaleString()} | Out: {dossierMetrics.total_output_tokens.toLocaleString()}
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Estimated Cost</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--color-success)', marginTop: '0.25rem' }}>
                              ${dossierMetrics.estimated_total_cost.toFixed(4)}
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                              Est: Input $5.00/1M, Output $15.00/1M
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Workflow Node Stages</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                              <span style={{ color: 'var(--color-success)' }}>{dossierMetrics.successful_stages}</span>
                              {' / '}
                              <span style={{ color: dossierMetrics.failed_stages > 0 ? 'var(--color-danger)' : 'var(--text-secondary)' }}>
                                {dossierMetrics.stages.length}
                              </span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                              {dossierMetrics.failed_stages} failed stage(s)
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Gaps List */}
                    <h2 className="findings-list-header">Diligence Gaps</h2>
                    {(() => {
                      const gaps = currentDossier.findings.filter(f => f.status === 'insufficient_evidence');
                      if (gaps.length === 0) {
                        return (
                          <div className="review-card" style={{ padding: '2rem', textAlign: 'center', marginBottom: '2rem' }}>
                            <p style={{ color: 'var(--color-success)', margin: 0, fontWeight: 500 }}>No active diligence evidence gaps detected in this dossier.</p>
                          </div>
                        );
                      }
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '2rem' }}>
                          {gaps.map((f) => (
                            <div key={f.id} className="review-card animate-fade-in" style={{ borderLeft: '4px solid var(--color-warning)' }}>
                              <h4 style={{ margin: '0 0 0.5rem', fontSize: '1.05rem', color: 'var(--text-primary)' }}>Q: {f.question}</h4>
                              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                                <span className={`badge badge-${f.status}`}>{f.status.replace('_', ' ')}</span>
                                <span className={`badge badge-${f.review_status}`}>{f.review_status.replace('_', ' ')}</span>
                              </div>
                              <p style={{ fontSize: '0.9rem', margin: '0.5rem 0' }}>
                                <strong>Why Evidence is Insufficient:</strong> {f.reasoning_summary || 'Evidence was evaluated to be insufficient to fulfill this query.'}
                              </p>
                              
                              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.75rem 0', backgroundColor: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '4px' }}>
                                <strong>Documents/Citations Checked:</strong>
                                {f.citations && f.citations.length > 0 ? (
                                  <ul style={{ margin: '0.25rem 0 0 1.25rem', padding: 0 }}>
                                    {f.citations.map((c: any, idx: number) => (
                                      <li key={idx}>
                                        File: <code>{c.filename}</code> {c.section ? `| Section: ${c.section}` : ''} {c.page_number ? `| Page: ${c.page_number}` : ''}
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <span style={{ color: 'var(--color-danger)' }}>Evidence was not found in the data room documents.</span>
                                )}
                              </div>
                              
                              <p style={{ fontSize: '0.85rem', margin: '0.5rem 0 0', color: 'var(--primary)' }}>
                                <strong>Needed to Close Gap:</strong> Please upload a valid due diligence document containing facts to answer this question.
                              </p>
                            </div>
                          ))}
                        </div>
                      );
                    })()}

                    {/* Needs Review List */}
                    <h2 className="findings-list-header">Needs Review</h2>
                    {(() => {
                      const needsReview = currentDossier.findings.filter(f => f.review_status === 'pending' && f.status !== 'insufficient_evidence');
                      if (needsReview.length === 0) {
                        return (
                          <div className="review-card" style={{ padding: '2rem', textAlign: 'center', marginBottom: '2rem' }}>
                            <p style={{ color: 'var(--color-success)', margin: 0, fontWeight: 500 }}>No findings currently awaiting review.</p>
                          </div>
                        );
                      }
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '2rem' }}>
                          {needsReview.map((f) => (
                            <div key={f.id} className="review-card animate-fade-in" style={{ borderLeft: '4px solid var(--primary)' }}>
                              <h4 style={{ margin: '0 0 0.5rem', fontSize: '1.05rem', color: 'var(--text-primary)' }}>Q: {f.question}</h4>
                              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                                <span className={`badge badge-${f.status}`}>{f.status.replace('_', ' ')}</span>
                                <span className={`badge badge-${f.review_status}`}>{f.review_status.replace('_', ' ')}</span>
                              </div>
                              <p style={{ fontSize: '0.9rem', margin: '0.5rem 0' }}>
                                <strong>Answer Draft:</strong> {f.answer || 'No answer generated.'}
                              </p>
                              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.75rem 0', backgroundColor: 'rgba(255,255,255,0.02)', padding: '0.75rem', borderRadius: '4px' }}>
                                <strong>Documents/Citations Checked:</strong>
                                {f.citations && f.citations.length > 0 ? (
                                  <ul style={{ margin: '0.25rem 0 0 1.25rem', padding: 0 }}>
                                    {f.citations.map((c: any, idx: number) => (
                                      <li key={idx}>
                                        File: <code>{c.filename}</code> {c.section ? `| Section: ${c.section}` : ''} {c.page_number ? `| Page: ${c.page_number}` : ''}
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <span style={{ color: 'var(--color-danger)' }}>Evidence was not found in the data room documents.</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })()}

                    {/* Findings Table List */}
                    <h2 className="findings-list-header">Diligence Findings</h2>
                    <div className="findings-table-card animate-fade-in" style={{ marginBottom: '2rem' }}>
                      <div className="finding-row" style={{ backgroundColor: 'rgba(255,255,255,0.02)', fontWeight: '600', borderBottom: '2px solid var(--border-color)', cursor: 'default' }}>
                        <div>Question</div>
                        <div>Workflow Status</div>
                        <div>Review Status</div>
                        <div>Confidence</div>
                        <div style={{ textAlign: 'right' }}>Actions</div>
                      </div>
                      
                      {currentDossier.findings.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '3rem 1.5rem', color: 'var(--text-secondary)' }}>
                          No diligence questions added yet.
                        </div>
                      ) : (
                        currentDossier.findings.map((f) => (
                          <div
                            key={f.id}
                            className="finding-row"
                            onClick={() => {
                              if (f.status !== 'pending') {
                                setView({ type: 'finding-review', dossierId: currentDossier.id, findingId: f.id });
                              }
                            }}
                          >
                            <div className="finding-question" title={f.question}>{f.question}</div>
                            <div>
                              <span className={`badge badge-${f.status}`}>{f.status.replace('_', ' ')}</span>
                            </div>
                            <div>
                              <span className={`badge badge-${f.review_status}`}>{f.review_status.replace('_', ' ')}</span>
                            </div>
                            <div className="finding-confidence">
                              {f.confidence !== null && f.confidence !== undefined ? `${Math.round(f.confidence * 100)}%` : 'N/A'}
                            </div>
                            <div className="finding-actions-col">
                              <button
                                className="action-icon-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (f.status !== 'pending') {
                                    setView({ type: 'finding-review', dossierId: currentDossier.id, findingId: f.id });
                                  }
                                }}
                                title="View Details"
                              >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                                  <circle cx="12" cy="12" r="3" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        ))
                      )}
                    </div>

                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: '1rem', marginTop: '2rem' }}>
                      <p><em>Note: Secure external sharing is not implemented. Use Export Dossier to download the report.</em></p>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="back-btn-container">
                      <button className="back-btn" onClick={() => setView({ type: 'dashboard' })}>
                        &larr; Back to Dashboard
                      </button>
                    </div>

                    <div className="section-header" style={{ marginBottom: '1.5rem' }}>
                      <div>
                        <h1 className="page-title">{currentDossier.name}</h1>
                        <div className="page-subtitle">Dossier ID: {currentDossier.id}</div>
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <span className={`badge badge-${currentDossier.status}`} style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
                          {currentDossier.status.replace('_', ' ')}
                        </span>
                        {(currentDossier.status === 'pending' || currentDossier.status === 'failed') && (
                          <button className="btn btn-primary" onClick={handleRunDossier} disabled={submitting}>
                            {submitting ? 'Starting...' : 'Execute Workflow'}
                          </button>
                        )}
                      </div>
                    </div>

                    {dossierMetrics && dossierMetrics.stages && dossierMetrics.stages.length > 0 && (
                      <div className="detail-card animate-fade-in" style={{ marginBottom: '1.5rem', padding: '1.25rem', borderRadius: '8px', border: '1px solid var(--border)', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                        <h3 style={{ margin: '0 0 1rem', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-primary)' }}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <line x1="18" y1="20" x2="18" y2="10" />
                            <line x1="12" y1="20" x2="12" y2="4" />
                            <line x1="6" y1="20" x2="6" y2="14" />
                          </svg>
                          Workflow Execution & Cost Metrics
                        </h3>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Total Execution Time</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--primary)', marginTop: '0.25rem' }}>
                              {(dossierMetrics.total_duration_ms / 1000).toFixed(2)}s
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Estimated Token Usage</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                              {dossierMetrics.total_tokens.toLocaleString()} <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>(approx)</span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.1rem' }}>
                              In: {dossierMetrics.total_input_tokens.toLocaleString()} | Out: {dossierMetrics.total_output_tokens.toLocaleString()}
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Estimated Cost</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--color-success)', marginTop: '0.25rem' }}>
                              ${dossierMetrics.estimated_total_cost.toFixed(4)}
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                              Est: Input $5.00/1M, Output $15.00/1M
                            </div>
                          </div>
                          <div style={{ padding: '0.75rem', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Workflow Node Stages</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                              <span style={{ color: 'var(--color-success)' }}>{dossierMetrics.successful_stages}</span>
                              {' / '}
                              <span style={{ color: dossierMetrics.failed_stages > 0 ? 'var(--color-danger)' : 'var(--text-secondary)' }}>
                                {dossierMetrics.stages.length}
                              </span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                              {dossierMetrics.failed_stages} failed stage(s)
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="dossier-meta-grid">
                      <div className="detail-card">
                        <h3 style={{ margin: '0 0 1rem', fontSize: '1.1rem' }}>Overall Progress</h3>
                        
                        {(() => {
                          const completedCount = currentDossier.findings.filter((f) => f.status === 'answered' || f.status === 'insufficient_evidence' || f.status === 'conflict').length;
                          const totalCount = currentDossier.findings.length;
                          const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
                          
                          return (
                            <div className="progress-container">
                              <div className="progress-label-row">
                                <span>Completed Findings</span>
                                <span>{progressPct}% ({completedCount}/{totalCount})</span>
                              </div>
                              <div className="progress-track" style={{ height: '1rem' }}>
                                <div className="progress-bar" style={{ width: `${progressPct}%` }}></div>
                              </div>
                            </div>
                          );
                        })()}
                      </div>

                      <div className="detail-card">
                        <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.1rem' }}>Run Metadata</h3>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                          <p style={{ margin: '0.25rem 0' }}>Created: {new Date(currentDossier.created_at).toLocaleString()}</p>
                          <p style={{ margin: '0.25rem 0' }}>Updated: {new Date(currentDossier.updated_at).toLocaleString()}</p>
                        </div>
                      </div>
                    </div>

                    {/* Findings Table List */}
                    <h2 className="findings-list-header">Diligence Findings</h2>
                    <div className="findings-table-card animate-fade-in">
                      <div className="finding-row" style={{ backgroundColor: 'rgba(255,255,255,0.02)', fontWeight: '600', borderBottom: '2px solid var(--border-color)', cursor: 'default' }}>
                        <div>Question</div>
                        <div>Workflow Status</div>
                        <div>Review Status</div>
                        <div>Confidence</div>
                        <div style={{ textAlign: 'right' }}>Actions</div>
                      </div>
                      
                      {currentDossier.findings.length === 0 ? (
                        <div style={{ textAlign: 'center', padding: '3rem 1.5rem', color: 'var(--text-secondary)' }}>
                          No diligence questions added yet.
                        </div>
                      ) : (
                        currentDossier.findings.map((f) => (
                          <div
                            key={f.id}
                            className="finding-row"
                            onClick={() => {
                              if (f.status !== 'pending') {
                                setView({ type: 'finding-review', dossierId: currentDossier.id, findingId: f.id });
                              } else {
                                addToast('Finding is currently queued. Execute run to begin parsing.', 'info');
                              }
                            }}
                          >
                            <div className="finding-question" title={f.question}>{f.question}</div>
                            <div>
                              <span className={`badge badge-${f.status}`}>{f.status.replace('_', ' ')}</span>
                            </div>
                            <div>
                              <span className={`badge badge-${f.review_status}`}>{f.review_status.replace('_', ' ')}</span>
                            </div>
                            <div className="finding-confidence">
                              {f.confidence !== null && f.confidence !== undefined ? `${Math.round(f.confidence * 100)}%` : 'N/A'}
                            </div>
                            <div className="finding-actions-col">
                              <button
                                className="action-icon-btn"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (f.status !== 'pending') {
                                    setView({ type: 'finding-review', dossierId: currentDossier.id, findingId: f.id });
                                  }
                                }}
                                title="Review Details"
                              >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                                  <circle cx="12" cy="12" r="3" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* VIEW: FINDING REVIEW */}
            {view.type === 'finding-review' && currentFinding && (
              <div className="animate-fade-in">
                <div className="back-btn-container">
                  <button className="back-btn" onClick={navigateBack}>
                    &larr; Back to Dossier Detail
                  </button>
                </div>

                <div className="section-header" style={{ marginBottom: '1.5rem' }}>
                  <div>
                    <h1 className="page-title" style={{ fontSize: '1.75rem' }}>Review Diligence Finding</h1>
                    <div className="page-subtitle">Finding ID: {currentFinding.id}</div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <span className={`badge badge-${currentFinding.status}`}>
                      Workflow: {currentFinding.status.replace('_', ' ')}
                    </span>
                    <span className={`badge badge-${currentFinding.review_status}`}>
                      Governance: {currentFinding.review_status.replace('_', ' ')}
                    </span>
                  </div>
                </div>

                {/* Workflow progress Visualizer */}
                <div className="workflow-visualizer-card">
                  <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
                    Workflow Execution History Pipeline
                  </h3>
                  
                  {(() => {
                    const status = currentFinding.status;
                    const rStatus = currentFinding.review_status;
                    
                    const steps = [
                      { label: 'Query Analysis', nodes: ['pending', 'running', 'answered', 'insufficient_evidence', 'conflict', 'failed'] },
                      { label: 'Retrieval', nodes: ['pending', 'running', 'answered', 'insufficient_evidence', 'conflict', 'failed'], failOn: ['failed'] },
                      { label: 'Sufficiency', nodes: ['answered', 'insufficient_evidence', 'conflict', 'failed'], skippedOn: ['insufficient_evidence'] },
                      { label: 'Conflict Detection', nodes: ['answered', 'conflict', 'failed'] },
                      { label: 'Answer Gen', nodes: ['answered', 'conflict', 'failed'] },
                      { label: 'Citations', nodes: ['answered', 'conflict', 'failed'] },
                      { label: 'Quality Gate', nodes: ['answered', 'conflict', 'failed'] },
                      { label: 'Human Review', nodes: ['answered', 'conflict', 'failed'] },
                      { label: 'Finalization', nodes: ['answered', 'insufficient_evidence', 'conflict', 'failed'] }
                    ];

                    return (
                      <div className="workflow-steps-list">
                        {steps.map((step, idx) => {
                          let stepClass = 'pending';
                          
                          if (status === 'failed') {
                            stepClass = idx === 1 ? 'failed' : (idx < 1 ? 'completed' : 'skipped');
                          } else if (status === 'insufficient_evidence') {
                            if (idx < 2) stepClass = 'completed';
                            else if (idx === 2) stepClass = 'completed'; // sufficiency decided insufficient
                            else if (idx === 8) stepClass = 'completed'; // finalized
                            else stepClass = 'skipped';
                          } else if (status === 'answered' || status === 'conflict') {
                            if (idx < 7) {
                              stepClass = 'completed';
                            } else if (idx === 7) {
                              stepClass = rStatus === 'pending' ? 'current' : 'completed';
                            } else if (idx === 8) {
                              stepClass = rStatus === 'pending' ? 'pending' : 'completed';
                            }
                          }
                          
                          return (
                            <div key={idx} className={`workflow-step-node ${stepClass}`}>
                              <div className="workflow-step-dot">{idx + 1}</div>
                              <div className="workflow-step-label">{step.label}</div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
                </div>

                {/* Details layout split */}
                <div className="review-panel-layout animate-fade-in">
                  
                  {/* Left Side: Question, Answer, and Evidence */}
                  <div>
                    <div className="review-card">
                      <div className="question-box">
                        Q: {currentFinding.question}
                      </div>
                      
                      <h3 className="review-section-title">Final Answer Draft</h3>
                      {isEditing ? (
                        <div className="edit-fields-container">
                          <textarea
                            className="form-input"
                            rows={6}
                            value={editAnswer}
                            onChange={(e) => setEditAnswer(e.target.value)}
                            placeholder="Enter the modified answer..."
                          />
                        </div>
                      ) : (
                        <div className="answer-box">
                          {currentFinding.answer || (
                            <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                              No answer has been formulated.
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Conflict Highlight Comparative UX */}
                    {currentFinding.status === 'conflict' && (
                      <div className="review-card">
                        <div className="conflict-alert animate-fade-in">
                          <span className="conflict-alert-icon">&#9888;</span>
                          <div>
                            <strong>Diligence Contradiction Alert:</strong> Fact-room conflict detected on matching parameters. Assertions below represent contradicting statements parsed from raw source files.
                          </div>
                        </div>

                        <div className="evidence-comparison">
                          {/* Supporting Evidence Column */}
                          <div className="evidence-column">
                            <div className="evidence-column-title supporting">
                              <span style={{ fontSize: '1.2rem' }}>&#10003;</span> Supporting Evidence
                            </div>
                            {currentFinding.supporting_evidence && currentFinding.supporting_evidence.length > 0 ? (
                              currentFinding.supporting_evidence.map((ev, idx) => (
                                <div key={idx} className="evidence-item">
                                  <div className="evidence-item-header">
                                    <span>Doc: {ev.filename}</span>
                                    <span>Score: {Math.round(ev.retrieval_score * 100)}%</span>
                                  </div>
                                  <div className="evidence-item-content">"{ev.content}"</div>
                                </div>
                              ))
                            ) : (
                              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No supporting data available.</p>
                            )}
                          </div>

                          {/* Contradicting Evidence Column */}
                          <div className="evidence-column">
                            <div className="evidence-column-title contradicting">
                              <span style={{ fontSize: '1.2rem' }}>&#10007;</span> Contradicting Evidence
                            </div>
                            {currentFinding.contradicting_evidence && currentFinding.contradicting_evidence.length > 0 ? (
                              currentFinding.contradicting_evidence.map((ev, idx) => (
                                <div key={idx} className="evidence-item">
                                  <div className="evidence-item-header">
                                    <span>Doc: {ev.filename}</span>
                                    <span>Score: {Math.round(ev.retrieval_score * 100)}%</span>
                                  </div>
                                  <div className="evidence-item-content">"{ev.content}"</div>
                                </div>
                              ))
                            ) : (
                              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No contradicting data room facts parsed.</p>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Citations Explorer */}
                    <div className="review-card">
                      <h3 className="review-section-title">Reference Citations</h3>
                      {currentFinding.citations && currentFinding.citations.length > 0 ? (
                        <div className="citation-list">
                          {currentFinding.citations.map((cit, idx) => (
                            <div key={idx} className="citation-card animate-fade-in">
                              <div className="citation-meta">
                                <span className="citation-meta-item">Document: <strong>{cit.filename}</strong></span>
                                {cit.page_number && <span className="citation-meta-item">Page: <strong>{cit.page_number}</strong></span>}
                                {cit.section && <span className="citation-meta-item">Section: <strong>{cit.section}</strong></span>}
                                <span className="citation-meta-item" style={{ color: 'var(--text-muted)' }}>Chunk ID: {cit.chunk_id.substring(0, 8)}...</span>
                              </div>
                              {cit.excerpt && <p className="citation-excerpt">"{cit.excerpt}"</p>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No reference citations parsed.</p>
                      )}
                    </div>
                  </div>

                  {/* Right Side: Metadata, Reasoning Summary & Actions */}
                  <div>
                    <div className="review-card">
                      <h3 style={{ margin: '0 0 1rem', fontSize: '1.1rem' }}>Finding Analytics</h3>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Confidence Score</span>
                          <span style={{ fontWeight: '700', color: currentFinding.confidence && currentFinding.confidence >= 0.6 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                            {currentFinding.confidence !== null && currentFinding.confidence !== undefined ? `${Math.round(currentFinding.confidence * 100)}%` : 'N/A'}
                          </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Thread ID</span>
                          <span style={{ fontFamily: 'monospace' }}>{currentFinding.workflow_thread_id.substring(0, 12)}...</span>
                        </div>
                        {currentFinding.review_reason && (
                          <div style={{ marginTop: '0.5rem', padding: '0.75rem', backgroundColor: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 'var(--radius-sm)' }}>
                            <strong style={{ color: '#fca5a5', display: 'block', fontSize: '0.8rem', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Rejection Reason</strong>
                            <p style={{ fontSize: '0.85rem', margin: 0 }}>{currentFinding.review_reason}</p>
                          </div>
                        )}
                      </div>

                      <h3 style={{ margin: '1.5rem 0 0.5rem', fontSize: '1rem', fontWeight: '600' }}>Reasoning Logic</h3>
                      {isEditing ? (
                        <div className="edit-fields-container">
                          <textarea
                            className="form-input"
                            rows={4}
                            value={editReasoning}
                            onChange={(e) => setEditReasoning(e.target.value)}
                            placeholder="Enter manual reasoning details..."
                          />
                          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                            <button className="btn btn-secondary" onClick={() => setIsEditing(false)} disabled={submitting}>
                              Cancel
                            </button>
                            <button className="btn btn-primary" onClick={handleEditFinding} disabled={submitting}>
                              Save Edits
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="reasoning-box">
                            {currentFinding.reasoning_summary || 'No reasoning summary provided.'}
                          </div>
                          {currentFinding.review_status === 'pending' && !investorMode && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '2rem' }}>
                              <button className="btn btn-success" onClick={handleApproveFinding} disabled={submitting}>
                                Approve Draft
                              </button>
                              <button className="btn btn-secondary" onClick={() => setIsEditing(true)} disabled={submitting}>
                                Edit & Overwrite State
                              </button>
                              <button className="btn btn-danger" onClick={() => setShowRejectModal(true)} disabled={submitting}>
                                Reject Draft
                              </button>
                            </div>
                          )}
                        </>
                      )}
                      
                      {(currentFinding.status === 'failed' || currentFinding.review_status === 'rejected') && !investorMode && (
                        <div style={{ marginTop: '2rem' }}>
                          <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => setShowRetryModal(true)} disabled={submitting}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                            </svg>
                            Retry Execution Thread
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                </div>
              </div>
            )}

            {/* VIEW: DATA ROOM */}
            {view.type === 'data-room' && (
              <div className="animate-fade-in">
                <div className="section-header">
                  <div>
                    <h1 className="page-title">Diligence Data Room</h1>
                    <div className="page-subtitle">Manage, ingest, and index startup investment source documents</div>
                  </div>
                  <div>
                    <input
                      type="file"
                      ref={fileInputRef}
                      style={{ display: 'none' }}
                      onChange={handleFileUpload}
                      accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
                    />
                    <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()}>
                      Upload Document
                    </button>
                  </div>
                </div>

                {/* Upload drag drop zone */}
                <div className="upload-zone animate-fade-in" onClick={() => fileInputRef.current?.click()}>
                  <div className="upload-zone-icon">&#8682;</div>
                  <h3>Select or drag document to ingest</h3>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.5rem' }}>
                    Supported formats: PDF, DOCX, XLSX, TXT, MD, CSV (Max 10MB). Legacy `.xls` remains explicitly unsupported.
                  </p>
                </div>

                {/* Document List */}
                <h2 className="findings-list-header">Ingested Files</h2>
                {documents.length === 0 ? (
                  <div className="review-card" style={{ textAlign: 'center', padding: '3rem 1.5rem', color: 'var(--text-secondary)' }}>
                    No files found in the data room. Ingest files to seed semantic retrieval.
                  </div>
                ) : (
                  <div className="document-list">
                    {documents.map((doc) => (
                      <div key={doc.id} className="document-card animate-fade-in">
                        <h4 className="document-name" title={doc.filename}>{doc.filename}</h4>
                        <span className={`badge badge-${doc.status}`} style={{ alignSelf: 'flex-start' }}>
                          {doc.status}
                        </span>
                        
                        {doc.error_message && (
                          <div style={{ marginTop: '0.5rem', padding: '0.5rem', backgroundColor: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.1)', borderRadius: 'var(--radius-sm)', fontSize: '0.75rem', color: '#fca5a5' }}>
                            {doc.error_message}
                          </div>
                        )}

                        <button className="document-delete-btn" onClick={() => handleDeleteDocument(doc.id, doc.filename)} title="Remove file">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                          </svg>
                        </button>
                        
                        <div className="document-meta-row">
                          <span>{(doc.file_size / 1024).toFixed(1)} KB</span>
                          <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* VIEW: ACCESSIBILITY TOOL */}
            {view.type === 'accessibility' && (
              <div className="animate-fade-in">
                <div className="section-header">
                  <div>
                    <h1 className="page-title">Accessibility-tagged Export Tool</h1>
                    <div className="page-subtitle">Verify, remediate heading hierarchies, alt text, and export semantic documents</div>
                  </div>
                  <div>
                    <input
                      type="file"
                      id="accessibility-file-input"
                      style={{ display: 'none' }}
                      onChange={handleAccessibilityUpload}
                      accept=".txt,.md"
                    />
                    <button className="btn btn-primary" onClick={() => document.getElementById('accessibility-file-input')?.click()}>
                      Upload Document
                    </button>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '1.5rem' }}>
                  
                  {/* Left Column - Input Panel */}
                  <div className="detail-card">
                    <h3 style={{ margin: '0 0 1rem', fontSize: '1.15rem' }}>1. Document Content (Text or Markdown)</h3>
                    <textarea
                      className="form-input"
                      style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                      rows={14}
                      value={accessRawText}
                      onChange={(e) => setAccessRawText(e.target.value)}
                      placeholder="Paste your fictional document here, or upload a markdown/txt file above..."
                    />
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1rem', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {accessFile ? `Loaded file: ${accessFile.name}` : 'Pasted text mode'}
                      </span>
                      <button className="btn btn-secondary" onClick={handleAccessibilityCheckText}>
                        Analyze Text Structure
                      </button>
                    </div>
                  </div>

                  {/* Right Column - Audit & Remediation Panel */}
                  <div className="detail-card">
                    <h3 style={{ margin: '0 0 1rem', fontSize: '1.15rem' }}>2. Accessibility Issues & Alt-Text Inputs</h3>
                    
                    {!accessAudit ? (
                      <div style={{ padding: '3rem 1.5rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                        Upload or input document text and click "Analyze" to inspect accessibility flaws.
                      </div>
                    ) : (
                      <div>
                        {/* Heading flaws */}
                        <div style={{ marginBottom: '1.5rem' }}>
                          <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.25rem' }}>Heading Jumps & Structure</h4>
                          {accessAudit.issues.filter(i => i.issue_type === 'heading_hierarchy').length === 0 ? (
                            <p style={{ color: 'var(--color-success)', fontSize: '0.85rem' }}>✓ Heading hierarchy is sequential and correct.</p>
                          ) : (
                            <ul style={{ paddingLeft: '1.25rem', margin: 0, fontSize: '0.85rem' }}>
                              {accessAudit.issues.filter(i => i.issue_type === 'heading_hierarchy').map((issue) => (
                                <li key={issue.id} style={{ color: 'var(--color-warning)', marginBottom: '0.25rem' }}>
                                  <strong>{issue.location}:</strong> {issue.details} (Auto-fix will nest correctly)
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>

                        {/* List & Table formatting detection */}
                        <div style={{ marginBottom: '1.5rem' }}>
                          <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.25rem' }}>Lists & Tables Semantics</h4>
                          <ul style={{ paddingLeft: '1.25rem', margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            {accessAudit.issues.filter(i => i.issue_type === 'list_semantics' || i.issue_type === 'table_semantics').map((issue) => (
                              <li key={issue.id} style={{ marginBottom: '0.25rem' }}>
                                {issue.details}
                              </li>
                            ))}
                            {accessAudit.issues.filter(i => i.issue_type === 'list_semantics' || i.issue_type === 'table_semantics').length === 0 && (
                              <p style={{ fontSize: '0.85rem' }}>No plain lists or tabular grids detected in input.</p>
                            )}
                          </ul>
                        </div>

                        {/* Image alt fixes */}
                        <div style={{ marginBottom: '1.5rem' }}>
                          <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.25rem' }}>Image Alt-Text Overrides</h4>
                          {accessAudit.detected_images.length === 0 ? (
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No image tags (`![]()`) detected in this document.</p>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.5rem' }}>
                              {accessAudit.detected_images.map((img) => (
                                <div key={img.url} className="question-builder-item" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '0.5rem', padding: '0.75rem' }}>
                                  <div style={{ fontSize: '0.8rem', fontFamily: 'monospace', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }} title={img.url}>
                                    URL: {img.url}
                                  </div>
                                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                    <span style={{ fontSize: '0.8rem', color: !img.current_alt ? 'var(--color-warning)' : 'var(--color-success)' }}>
                                      {!img.current_alt ? '⚠ Missing Alt' : '✓ Current Alt:'}
                                    </span>
                                    <input
                                      type="text"
                                      className="form-input"
                                      style={{ flex: 1, fontSize: '0.85rem', padding: '0.25rem 0.5rem' }}
                                      value={accessAltOverrides[img.url] || ''}
                                      onChange={(e) => setAccessAltOverrides(prev => ({ ...prev, [img.url]: e.target.value }))}
                                      placeholder="Provide descriptive alt text for screen readers..."
                                    />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        <button className="btn btn-primary" style={{ width: '100%', marginTop: '1rem' }} onClick={handleAccessibilityRemediate}>
                          Apply Fixes & Remediate
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* Bottom Row - Export & Plain Report */}
                {(accessReport || accessRemediatedHtml) && (
                  <div className="animate-fade-in" style={{ marginTop: '2rem', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
                    
                    {/* Report Output */}
                    <div className="detail-card">
                      <h3 style={{ margin: '0 0 1rem', fontSize: '1.15rem' }}>3. Plain-Language Accessibility Report</h3>
                      <pre style={{ backgroundColor: 'var(--background-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '1rem', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.8rem', maxHeight: '350px', overflowY: 'auto' }}>
                        {accessReport}
                      </pre>
                      <button className="btn btn-secondary" style={{ marginTop: '1rem' }} onClick={downloadAccessibilityReport}>
                        Download Text Report
                      </button>
                    </div>

                    {/* Remediated HTML Preview */}
                    <div className="detail-card">
                      <h3 style={{ margin: '0 0 1rem', fontSize: '1.15rem' }}>4. Remediated Semantic HTML Output</h3>
                      <pre style={{ backgroundColor: 'var(--background-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '1rem', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.8rem', maxHeight: '350px', overflowY: 'auto' }}>
                        {accessRemediatedHtml}
                      </pre>
                      <button className="btn btn-primary" style={{ marginTop: '1rem' }} onClick={downloadRemediatedHtml}>
                        Export Structured HTML
                      </button>
                    </div>
                  </div>
                )}

                {/* Explicit Non-Compliance Disclaimer Footer */}
                <footer style={{ marginTop: '3rem', padding: '1.5rem', backgroundColor: 'rgba(245, 158, 11, 0.05)', border: '1px solid rgba(245, 158, 11, 0.15)', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', color: '#f59e0b', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  <div style={{ fontWeight: '600', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>⚠</span> DISCLAIMER AND LIMITATIONS
                  </div>
                  <div>
                    This Accessibility-tagged Export Tool produces clean, semantically correct HTML (utilizing proper h1/h2/h3 hierarchy, alt descriptions, lists, and tables) to optimize readability. However, it **does not claim or guarantee**:
                  </div>
                  <ul style={{ margin: '0 0 0.5rem', paddingLeft: '1.5rem' }}>
                    <li>PDF/UA compliance (Universal Accessibility for PDF files)</li>
                    <li>Tagged-PDF compliance (structural element nesting)</li>
                    <li>WCAG certification (Web Content Accessibility Guidelines conformance)</li>
                    <li>Complete accessibility or automated compliance certification</li>
                  </ul>
                  <div style={{ fontSize: '0.8rem', opacity: 0.9 }}>
                    All document checking is conducted locally. Reading order validation is bounded by format constraints.
                  </div>
                </footer>
              </div>
            )}
          </>
        )}
      </main>

      {/* REJECT MODAL */}
      {showRejectModal && (
        <div className="modal-overlay">
          <div className="modal-content animate-fade-in">
            <h3 className="modal-header">Reject Draft Answer</h3>
            <div className="modal-body">
              <p style={{ marginBottom: '1rem' }}>Provide a detailed rejection reason. This will be preserved in the audit trail of this question.</p>
              <textarea
                className="form-input"
                rows={4}
                placeholder="e.g. Verified revenues do not align with Q3 ARR records..."
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              />
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => { setShowRejectModal(false); setRejectReason(''); }}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={handleRejectFinding} disabled={submitting}>
                Reject Finding
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RETRY MODAL */}
      {showRetryModal && (
        <div className="modal-overlay">
          <div className="modal-content animate-fade-in">
            <h3 className="modal-header">Confirm Rerun Action</h3>
            <div className="modal-body">
              <p>Rerunning this finding archives the current state in the historical audit trail and spawns a fresh workflow execution thread.</p>
              <p style={{ marginTop: '0.5rem', fontWeight: '500' }}>Do you wish to proceed?</p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowRetryModal(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleRetryFinding} disabled={submitting}>
                Proceed & Rerun
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TOASTS CONTAINER */}
      <div className="toast-container">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.type} animate-fade-in`}>
            <span className="toast-message">{toast.message}</span>
            <button className="toast-close" onClick={() => removeToast(toast.id)}>
              &times;
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
