import React, { useState } from 'react';
import { FileSearch, CheckCircle2, XCircle } from 'lucide-react';
import { format } from 'date-fns';

function parseChangeContent(change) {
  const raw = change?.raw || {};
  let inner = raw;
  if (typeof change?.content === 'string') {
    try {
      inner = JSON.parse(change.content);
    } catch {
      inner = { description: change.content, original: '', modified: change.content };
    }
  }
  return {
    description: inner.description || inner.type || 'Proposed change',
    original: inner.original || '—',
    modified: inner.modified || inner.content || '—',
    section: raw.section || inner.section || 'document',
  };
}

export function JobViewer({ job, onApprove, onReject }) {
  const [actioning, setActioning] = useState(false);

  if (!job) {
    return (
      <div className="empty-state">
        <FileSearch size={48} />
        <h2>Select a document to review</h2>
        <p>Choose an item from the sidebar to view details.</p>
      </div>
    );
  }

  const handleAction = async (action) => {
    setActioning(true);
    try {
      if (action === 'approve') await onApprove(job.id);
      else await onReject(job.id);
    } finally {
      setActioning(false);
    }
  };

  const isReviewPending = job.status === 'REVIEW_PENDING';
  const fileName = job.source_path.split('/').pop() || 'document.pdf';
  const changes = (job.proposed_changes || []).map(parseChangeContent);

  return (
    <div className="content-area" style={{ marginBottom: '24px' }}>
      <div className="job-header">
        <h2 className="job-title">Document Review: {fileName}</h2>
        <div className="job-subtitle">
          Status: <strong style={{ color: isReviewPending ? 'var(--amber)' : 'inherit' }}>{job.status}</strong>
          {' • '}
          {job.preview ? 'Preview mode (no write-back)' : 'Live mode'}
          {' • '}
          Last Updated: {job.updated_at ? format(new Date(job.updated_at), 'PPpp') : 'N/A'}
        </div>
      </div>

      {changes.length === 0 ? (
        <div className="diff-card" style={{ padding: '20px', color: 'var(--ink-lo)' }}>
          {isReviewPending
            ? 'Waiting for proposed changes from SuperDocs…'
            : 'No proposed changes recorded for this job.'}
        </div>
      ) : (
        changes.map((change, idx) => (
          <div className="diff-card" key={idx} style={{ marginBottom: '12px' }}>
            <div className="diff-header">
              <div>{change.section.toUpperCase()} — {change.description}</div>
            </div>
            <div className="diff-body">
              <div className="diff-pane">
                <div className="diff-line removed">
                  <span className="line-num">−</span>
                  <span>{change.original}</span>
                </div>
              </div>
              <div className="diff-pane">
                <div className="diff-line added">
                  <span className="line-num">+</span>
                  <span>{change.modified}</span>
                </div>
              </div>
            </div>
          </div>
        ))
      )}

      {isReviewPending && (
        <div className="gate-card">
          <div className="gate-info">
            <h3>Human Approval Gate</h3>
            <p>
              {changes.length} change{changes.length === 1 ? '' : 's'} detected in {fileName}.
              Approve to export and write back to Dropbox, or reject to discard.
            </p>
          </div>
          <div className="gate-actions">
            <button
              className="btn btn-reject"
              onClick={() => handleAction('reject')}
              disabled={actioning}
            >
              {actioning ? 'Processing...' : 'Reject'}
            </button>
            <button
              className="btn btn-approve"
              onClick={() => handleAction('approve')}
              disabled={actioning}
            >
              {actioning ? 'Processing...' : 'Approve & Write Back'}
            </button>
          </div>
        </div>
      )}

      {!isReviewPending && job.status === 'COMPLETED' && (
        <div className="gate-card" style={{ borderColor: 'var(--green)' }}>
          <div className="gate-info">
            <h3 style={{ color: 'var(--green)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <CheckCircle2 size={20} /> Completed
            </h3>
            <p>Approved, exported, and written back beside the source file.</p>
          </div>
        </div>
      )}

      {!isReviewPending && job.status === 'APPROVED' && (
        <div className="gate-card" style={{ borderColor: 'var(--amber)' }}>
          <div className="gate-info">
            <h3>Approved — exporting…</h3>
            <p>Export and Dropbox write-back are in progress.</p>
          </div>
        </div>
      )}

      {!isReviewPending && job.status === 'REJECTED' && (
        <div className="gate-card" style={{ borderColor: 'var(--heavy)' }}>
          <div className="gate-info">
            <h3 style={{ color: 'var(--heavy)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <XCircle size={20} /> Rejected
            </h3>
            <p>This document was rejected. No changes were written back to Dropbox.</p>
          </div>
        </div>
      )}
    </div>
  );
}
