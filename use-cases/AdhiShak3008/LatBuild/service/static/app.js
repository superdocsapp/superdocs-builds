/* app.js — LatBuild SuperDocs PDF Companion */

// ---------------------------------------------------------------------------
// Upload page
// ---------------------------------------------------------------------------

function initUploadPage() {
  const formEl    = document.getElementById('upload-form-el');
  const fileInput = document.getElementById('file-input');
  const statusEl  = document.getElementById('upload-status');
  const replaceBtn = document.getElementById('replace-btn');
  const uploadFormWrap = document.getElementById('upload-form');
  const dropZone  = document.getElementById('drop-zone');

  if (replaceBtn && uploadFormWrap) {
    replaceBtn.addEventListener('click', () => {
      uploadFormWrap.style.display = 'block';
    });
  }

  if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) {
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
      }
    });
  }

  if (formEl) {
    formEl.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!fileInput.files.length) return;

      const formData = new FormData();
      formData.append('file', fileInput.files[0]);

      const btn = formEl.querySelector('#upload-btn');
      btn.disabled = true;
      statusEl.innerHTML = '<span class="spinner"></span> Analyzing PDF…';

      try {
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!resp.ok || data.error) {
          statusEl.textContent = 'Error: ' + (data.error || 'Upload failed');
          btn.disabled = false;
          return;
        }
        statusEl.textContent =
          `✓ ${data.filename} — ${data.page_count} pages, ${data.sections.length} sections detected`;
        setTimeout(() => window.location.href = '/sections', 900);
      } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        btn.disabled = false;
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Sections page
// ---------------------------------------------------------------------------

function initSectionsPage() {
  const checkboxes   = document.querySelectorAll('.section-checkbox');
  const countLabel   = document.getElementById('selection-count');
  const continueBtn  = document.getElementById('continue-btn');
  const selectAllBtn = document.getElementById('select-all-btn');
  const deselectBtn  = document.getElementById('deselect-all-btn');

  function updateCount() {
    const checked = [...checkboxes].filter(c => c.checked);
    countLabel.textContent = `${checked.length} section(s) selected`;
    continueBtn.disabled = checked.length === 0;

    checkboxes.forEach(c => {
      c.closest('.section-item').classList.toggle('selected', c.checked);
    });
  }

  checkboxes.forEach(c => c.addEventListener('change', updateCount));

  selectAllBtn?.addEventListener('click', () => {
    checkboxes.forEach(c => { c.checked = true; });
    updateCount();
  });
  deselectBtn?.addEventListener('click', () => {
    checkboxes.forEach(c => { c.checked = false; });
    updateCount();
  });

  continueBtn?.addEventListener('click', () => {
    const selected = [...checkboxes]
      .filter(c => c.checked)
      .map(c => c.value);
    // Store in sessionStorage for edit page
    sessionStorage.setItem('selectedSections', JSON.stringify(selected));
    window.location.href = '/edit?' + new URLSearchParams({ sections: selected.join(',') });
  });

  updateCount();
}

// ---------------------------------------------------------------------------
// Edit page
// ---------------------------------------------------------------------------

function initEditPage() {
  const form    = document.getElementById('edit-form');
  const statusEl = document.getElementById('transform-status');
  const startBtn = document.getElementById('start-btn');
  const applyAllBtn = document.getElementById('apply-all-btn');

  // Recover selected sections from URL params or state
  const params = new URLSearchParams(window.location.search);
  const sectionsParam = params.get('sections') || '';
  const selectedSections = window.EDIT_STATE?.selectedSections
    || sectionsParam.split(',').filter(Boolean);

  // "Apply to All" button
  applyAllBtn?.addEventListener('click', () => {
    const bulkText = document.getElementById('bulk-instruction')?.value || '';
    if (!bulkText.trim()) return;
    document.querySelectorAll('.section-instruction-input').forEach(ta => {
      ta.value = bulkText;
    });
  });

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // Collect per-section instructions
      const instructions = {};
      let allFilled = true;
      document.querySelectorAll('.section-instruction-input').forEach(ta => {
        const section = ta.dataset.section;
        const text = ta.value.trim();
        if (!text) allFilled = false;
        instructions[section] = text;
      });

      if (!allFilled) {
        statusEl.textContent = 'Please enter an instruction for every section.';
        return;
      }

      startBtn.disabled = true;
      statusEl.innerHTML = '<span class="spinner"></span> Starting SuperDocs jobs…';

      try {
        const resp = await fetch('/api/transform', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sections: selectedSections,
            instructions,
          }),
        });
        const data = await resp.json();
        if (!resp.ok || data.error) {
          statusEl.textContent = 'Error: ' + (data.error || 'Failed to start');
          startBtn.disabled = false;
          return;
        }
        statusEl.textContent = `✓ ${Object.keys(data.jobs).length} job(s) started`;
        setTimeout(() => window.location.href = '/review', 600);
      } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        startBtn.disabled = false;
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Review page
// ---------------------------------------------------------------------------

const _sectionDecisions = {};  // section_name -> { approved: bool, text: str }
let _allJobsComplete = false;

function getSectionCard(sectionName) {
  const cards = document.querySelectorAll('.section-review-card');
  for (const card of cards) {
    if (card.dataset.section === sectionName) {
      return card;
    }
  }
  return null;
}

function initReviewPage() {
  const state = window.REVIEW_STATE;
  if (!state || !state.jobs) return;

  // Poll all in-progress jobs by exact section name
  Object.entries(state.jobs).forEach(([sectionName, job]) => {
    if (job.status === 'completed' && job.proposed_text) {
      showDiff(sectionName, job.proposed_text);
    } else if (job.status === 'failed') {
      showError(sectionName, job.error || 'Unknown error');
    } else if (job.job_id) {
      pollJob(sectionName, job.job_id);
    }
  });

  // Batch controls
  document.getElementById('approve-all-btn')?.addEventListener('click', () => {
    document.querySelectorAll('.approve-section-btn').forEach(btn => btn.click());
  });
  document.getElementById('reject-all-btn')?.addEventListener('click', () => {
    document.querySelectorAll('.reject-section-btn').forEach(btn => btn.click());
  });
  document.getElementById('apply-btn')?.addEventListener('click', applyChanges);
}

async function pollJob(sectionName, jobId) {
  try {
    const resp = await fetch(`/api/poll/${jobId}`);
    const data = await resp.json();

    if (!resp.ok || data.error) {
      showError(sectionName, data.error || 'Poll failed');
      return;
    }

    if (data.status === 'awaiting_approval') {
      // Auto-approve SuperDocs internal changes and keep polling
      const pendingChanges = data.pending_changes || [];
      const decisions = pendingChanges.map(c => ({
        change_id: c.change_id || String(Math.random()),
        approved: true,
        feedback: '',
      }));
      const job = window.REVIEW_STATE?.jobs?.[sectionName];
      if (job?.session_id) {
        await fetch('/api/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            job_id: jobId,
            session_id: job.session_id,
            decisions: decisions.length > 0 ? decisions : [{ change_id: 'auto', approved: true }],
          }),
        });
      }
      setTimeout(() => pollJob(sectionName, jobId), 2500);
      return;
    }

    if (data.status === 'completed') {
      showDiff(sectionName, data.proposed_text || '');
      checkAllComplete();
      return;
    }

    if (data.status === 'failed') {
      showError(sectionName, data.error || 'Job failed');
      return;
    }

    // Still in progress
    setTimeout(() => pollJob(sectionName, jobId), 2500);
  } catch (err) {
    setTimeout(() => pollJob(sectionName, jobId), 4000);
  }
}

function showDiff(sectionName, proposedText) {
  const card = getSectionCard(sectionName);
  if (!card) return;

  const diffEl      = card.querySelector('.diff-grid');
  const proposedEl  = card.querySelector('.proposed-content');
  const actionsEl   = card.querySelector('.section-actions');
  const statusBadge = card.querySelector('.section-status-badge');

  if (proposedEl) proposedEl.textContent = proposedText;
  diffEl?.classList.remove('hidden');
  actionsEl?.classList.remove('hidden');
  if (statusBadge) {
    statusBadge.innerHTML = 'Ready for review';
    statusBadge.className = 'section-status-badge';
  }

  // Approve button
  const approveBtn = card.querySelector('.approve-section-btn');
  if (approveBtn) {
    approveBtn.onclick = () => {
      _sectionDecisions[sectionName] = { approved: true, text: proposedText };
      markDecision(sectionName, true);
    };
  }

  // Reject button
  const rejectBtn = card.querySelector('.reject-section-btn');
  if (rejectBtn) {
    rejectBtn.onclick = () => {
      _sectionDecisions[sectionName] = { approved: false, text: null };
      markDecision(sectionName, false);
    };
  }

  updateApplyButton();
}

function markDecision(sectionName, approved) {
  const card = getSectionCard(sectionName);
  if (!card) return;

  const decisionEl  = card.querySelector('.section-decision');
  const statusBadge = card.querySelector('.section-status-badge');

  if (decisionEl) {
    decisionEl.textContent = approved
      ? '✓ Approved — click Reject to change'
      : '✗ Rejected — click Approve to change';
    decisionEl.className = `section-decision ${approved ? 'approved' : 'rejected'}`;
    decisionEl.classList.remove('hidden');
  }
  if (statusBadge) {
    statusBadge.textContent = approved ? '✓ Approved' : '✗ Rejected';
    statusBadge.className = `section-status-badge ${approved ? 'approved' : 'rejected'}`;
  }
  updateApplyButton();
}

function showError(sectionName, errorMsg) {
  const card = getSectionCard(sectionName);
  if (!card) return;
  const statusBadge = card.querySelector('.section-status-badge');
  if (statusBadge) {
    statusBadge.innerHTML = `<span style="color:#b91c1c">✗ Failed: ${errorMsg}</span>`;
  }
}

function checkAllComplete() {
  const state = window.REVIEW_STATE;
  if (!state?.jobs) return;
  const totalJobs = Object.keys(state.jobs).length;
  const decidedCount = Object.keys(_sectionDecisions).length;
  if (decidedCount >= totalJobs) {
    updateGlobalStatus('All sections reviewed.');
  }
  updateApplyButton();
}

function updateApplyButton() {
  const applyBtn = document.getElementById('apply-btn');
  const batchControls = document.getElementById('batch-controls');

  // Show batch controls once at least one job has a diff
  const hasDiff = Object.values(_sectionDecisions).length > 0 ||
    document.querySelectorAll('.diff-grid:not(.hidden)').length > 0;
  if (hasDiff) {
    batchControls?.classList.remove('hidden');
  }

  const hasApproved = Object.values(_sectionDecisions).some(d => d.approved);
  if (applyBtn) applyBtn.disabled = !hasApproved;
}

function updateGlobalStatus(msg, type = 'info') {
  const el = document.getElementById('global-status');
  if (el) {
    el.className = `alert alert-${type}`;
    el.textContent = msg;
  }
}

async function applyChanges() {
  const applyBtn    = document.getElementById('apply-btn');
  const statusEl    = document.getElementById('apply-status');

  applyBtn.disabled = true;
  statusEl.innerHTML = '<span class="spinner"></span> Applying changes and running fidelity check…';

  const approvedTexts = {};
  Object.entries(_sectionDecisions).forEach(([name, decision]) => {
    if (decision.approved && decision.text) {
      approvedTexts[name] = decision.text;
    }
  });

  try {
    const resp = await fetch('/api/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved_texts: approvedTexts }),
    });
    const data = await resp.json();

    if (!resp.ok || data.error) {
      statusEl.textContent = 'Error: ' + (data.error || 'Apply failed');
      if (data.warnings) statusEl.textContent += ' — ' + data.warnings.join('; ');
      applyBtn.disabled = false;
      return;
    }

    statusEl.textContent = '✓ Done — redirecting to fidelity report…';
    setTimeout(() => window.location.href = '/report', 800);
  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
    applyBtn.disabled = false;
  }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
