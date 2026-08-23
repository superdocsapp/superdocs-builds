/* app.js — Preprint to Journal Converter frontend */

// ---------------------------------------------------------------------------
// Upload flow
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const uploadFormEl = document.getElementById('upload-form-el');
  const uploadStatus = document.getElementById('upload-status');
  const replaceBtn = document.getElementById('replace-btn');
  const uploadFormWrap = document.getElementById('upload-form');

  if (replaceBtn && uploadFormWrap) {
    replaceBtn.addEventListener('click', () => {
      uploadFormWrap.style.display = 'block';
    });
  }

  if (uploadFormEl) {
    uploadFormEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById('file-input');
      if (!fileInput.files.length) return;

      const formData = new FormData();
      formData.append('file', fileInput.files[0]);

      uploadStatus.textContent = 'Uploading…';
      const submitBtn = uploadFormEl.querySelector('button[type="submit"]');
      submitBtn.disabled = true;

      try {
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!resp.ok || data.error) {
          uploadStatus.textContent = 'Error: ' + (data.error || 'Upload failed');
          submitBtn.disabled = false;
          return;
        }
        uploadStatus.textContent = `✓ Uploaded: ${data.filename} (${data.chunks_count} sections)`;
        // Reload page to reflect new state
        setTimeout(() => window.location.reload(), 800);
      } catch (err) {
        uploadStatus.textContent = 'Upload failed: ' + err.message;
        submitBtn.disabled = false;
      }
    });
  }

  // Journal selection buttons
  document.querySelectorAll('.select-journal-btn').forEach(btn => {
    btn.addEventListener('click', () => startTransform(btn.dataset.journalId));
  });
});

async function startTransform(journalId) {
  const authorNames = (document.getElementById('author-names')?.value || '')
    .split('\n').map(s => s.trim()).filter(Boolean);
  const authorAffiliations = (document.getElementById('author-affiliations')?.value || '')
    .split('\n').map(s => s.trim()).filter(Boolean);

  // Show progress section
  const progressSection = document.getElementById('progress-section');
  const progressMsg = document.getElementById('progress-msg');
  const progressBar = document.getElementById('progress-bar');
  if (progressSection) {
    progressSection.classList.remove('hidden');
    progressMsg.textContent = 'Starting transformation…';
    progressBar.style.width = '10%';
  }

  try {
    const resp = await fetch('/api/transform', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        journal_id: journalId,
        author_names: authorNames,
        author_affiliations: authorAffiliations,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      if (progressMsg) progressMsg.textContent = 'Error: ' + (data.error || 'Failed to start');
      return;
    }

    if (progressMsg) progressMsg.textContent = 'Transformation started — waiting for proposed changes…';
    if (progressBar) progressBar.style.width = '30%';

    // Navigate to review page and poll there
    window.location.href = '/review';
  } catch (err) {
    if (progressMsg) progressMsg.textContent = 'Error: ' + err.message;
  }
}

// ---------------------------------------------------------------------------
// Review page
// ---------------------------------------------------------------------------

function initReviewPage() {
  const state = window.REVIEW_STATE;
  if (!state) return;

  if (state.initialStatus === 'completed') {
    showCompleted();
    return;
  }
  if (state.initialStatus === 'failed') return;

  // Start polling
  pollForChanges(state.jobId);
}

let _pollTimer = null;
let _pendingChanges = [];
let _decisions = {};

async function pollForChanges(jobId) {
  try {
    const resp = await fetch(`/api/poll/${jobId}`);
    const data = await resp.json();

    if (!resp.ok || data.error) {
      setPollingMsg('error', 'Error: ' + (data.error || 'Poll failed'));
      return;
    }

    if (data.status === 'awaiting_approval') {
      setPollingMsg('warning', 'Proposed changes are ready for review.');
      renderChanges(data.pending_changes || []);
      return; // stop polling — wait for user decisions
    }

    if (data.status === 'completed') {
      showCompleted();
      return;
    }

    if (data.status === 'failed') {
      setPollingMsg('error', 'Transformation failed. <a href="/">Try again</a>');
      return;
    }

    // Still in progress — keep polling
    _pollTimer = setTimeout(() => pollForChanges(jobId), 3000);
  } catch (err) {
    setPollingMsg('error', 'Poll error: ' + err.message);
    _pollTimer = setTimeout(() => pollForChanges(jobId), 5000);
  }
}

function setPollingMsg(type, html) {
  const el = document.getElementById('polling-msg');
  if (!el) return;
  el.className = `alert alert-${type}`;
  el.innerHTML = html;
}

function renderChanges(changes) {
  _pendingChanges = changes;
  _decisions = {};

  const container = document.getElementById('changes-container');
  const batchBar = document.getElementById('batch-controls');
  const countLabel = document.getElementById('change-count-label');

  if (!container) return;
  container.innerHTML = '';

  if (!changes.length) {
    container.innerHTML = '<p class="muted">No proposed changes to review at this stage — waiting for more…</p>';
    // Resume polling to check for more changes
    _pollTimer = setTimeout(() => pollForChanges(window.REVIEW_STATE.jobId), 2000);
    return;
  }

  if (batchBar) batchBar.classList.remove('hidden');
  if (countLabel) countLabel.textContent = `${changes.length} proposed change(s) — review each below`;

  changes.forEach((change, idx) => {
    const card = buildChangeCard(change, idx);
    container.appendChild(card);
  });

  // Batch controls
  document.getElementById('approve-all-btn')?.addEventListener('click', () => {
    changes.forEach((c, i) => setDecision(c.change_id || String(i), true, '', i));
  });
  document.getElementById('deny-all-btn')?.addEventListener('click', () => {
    changes.forEach((c, i) => setDecision(c.change_id || String(i), false, '', i));
  });
  document.getElementById('submit-decisions-btn')?.addEventListener('click', submitDecisions);
}

function buildChangeCard(change, idx) {
  const card = document.createElement('div');
  card.className = 'change-card';
  card.id = `change-card-${idx}`;

  const op = change.operation || 'update';
  const explanation = change.ai_explanation || '';

  // Determine before/after labels and content based on operation type
  const isMove   = op === 'move';
  const isDelete = op === 'delete';
  const isInsert = op === 'insert';

  const beforeLabel = isDelete ? 'Removing' : 'Before';
  const afterLabel  = isInsert ? 'Inserting' : (isMove ? 'Destination' : 'After');

  const oldHtml = change.old_html
    || (isInsert ? '<em style="color:#718096">New content — nothing here before.</em>' : '<em>(empty)</em>');

  const newHtml = (isMove && !change.new_html)
    ? '<em style="color:#718096">Content is being relocated to its new position in the document.</em>'
    : (isDelete && !change.new_html)
      ? '<em style="color:#9b2c2c">This content will be removed.</em>'
      : (change.new_html || '<em>(empty)</em>');

  card.innerHTML = `
    <div class="change-card-header">
      <span>Change ${idx + 1} of ${_pendingChanges.length}</span>
      <span class="operation-badge">${escHtml(op)}</span>
    </div>
    ${explanation ? `<div class="change-card-explanation">${escHtml(explanation)}</div>` : ''}
    <div class="change-card-diff">
      <div class="diff-before">
        <div class="diff-label">${beforeLabel}</div>
        <div class="diff-content">${oldHtml}</div>
      </div>
      <div class="diff-after">
        <div class="diff-label">${afterLabel}</div>
        <div class="diff-content">${newHtml}</div>
      </div>
    </div>
    <div class="change-card-actions">
      <button class="btn btn-success btn-sm approve-btn" data-idx="${idx}" data-id="${escHtml(change.change_id)}">Approve</button>
      <button class="btn btn-danger btn-sm deny-btn" data-idx="${idx}" data-id="${escHtml(change.change_id)}">Deny</button>
      <input type="text" class="feedback-input" data-idx="${idx}" placeholder="Feedback (optional, shown when denying)">
    </div>
  `;

  card.querySelector('.approve-btn').addEventListener('click', (e) => {
    const id = e.target.dataset.id || String(idx);
    const i = parseInt(e.target.dataset.idx);
    setDecision(id, true, '', i);
  });
  card.querySelector('.deny-btn').addEventListener('click', (e) => {
    const id = e.target.dataset.id || String(idx);
    const i = parseInt(e.target.dataset.idx);
    const feedback = card.querySelector('.feedback-input').value;
    setDecision(id, false, feedback, i);
  });

  return card;
}

function setDecision(changeId, approved, feedback, idx) {
  _decisions[changeId] = { change_id: changeId, approved, feedback };
  const card = document.getElementById(`change-card-${idx}`);
  if (card) {
    card.classList.remove('approved', 'denied');
    card.classList.add(approved ? 'approved' : 'denied');
  }
}

async function submitDecisions() {
  const state = window.REVIEW_STATE;
  const decisions = Object.values(_decisions);

  // Fill in any undecided changes as approved (default)
  _pendingChanges.forEach((c, i) => {
    const key = c.change_id || String(i);
    if (!_decisions[key]) {
      decisions.push({ change_id: c.change_id, approved: true, feedback: '' });
    }
  });

  setPollingMsg('info', '<span class="spinner"></span> Submitting decisions…');

  try {
    const resp = await fetch('/api/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: state.jobId,
        session_id: state.sessionId,
        decisions,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      setPollingMsg('error', 'Error submitting decisions: ' + (data.error || 'Unknown'));
      return;
    }
    setPollingMsg('info', '<span class="spinner"></span> Decisions submitted — waiting for completion…');
    document.getElementById('batch-controls')?.classList.add('hidden');
    // Resume polling
    _pollTimer = setTimeout(() => pollForChanges(state.jobId), 2000);
  } catch (err) {
    setPollingMsg('error', 'Submit error: ' + err.message);
  }
}

function showCompleted() {
  setPollingMsg('success', '✓ All changes processed. <a href="/report">View compliance report →</a>');
  document.getElementById('completed-panel')?.classList.remove('hidden');
  document.getElementById('batch-controls')?.classList.add('hidden');
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
