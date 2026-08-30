// @ts-check
import {
  renderTaskList,
  renderChangeList,
  renderSummaryBar,
  renderVerificationCenter,
  renderTimeline,
  renderVaultGraph,
  renderError,
} from './render.js';

const state = {
  timeline: [],
  approvalSet: [],
  summary: null,
  verification: [],
  editingChangeId: null,
};

const mounts = {
  taskList: document.getElementById('task-list-mount'),
  summary: document.getElementById('summary-mount'),
  changeList: document.getElementById('change-list-mount'),
  verification: document.getElementById('verification-mount'),
  vault: document.getElementById('vault-mount'),
  timeline: document.getElementById('timeline-mount'),
  uploadError: document.getElementById('upload-error-mount'),
  workflowState: document.getElementById('workflow-state'),
};

const els = {
  baseFile: /** @type {HTMLInputElement} */ (document.getElementById('base-file')),
  targetFile: /** @type {HTMLInputElement} */ (document.getElementById('target-file')),
  compareBtn: document.getElementById('compare-btn'),
  useFixturesBtn: document.getElementById('use-fixtures-btn'),
  applyBtn: /** @type {HTMLButtonElement} */ (document.getElementById('apply-btn')),
  downloadLink: /** @type {HTMLAnchorElement} */ (document.getElementById('download-link')),
  undoBtn: document.getElementById('undo-btn'),
  redoBtn: document.getElementById('redo-btn'),
};

function log(msg, level = 'info') {
  state.timeline.unshift({ at: new Date().toISOString(), msg, level });
  state.timeline = state.timeline.slice(0, 50);
  mounts.timeline.innerHTML = renderTimeline(state.timeline);
}

function setWorkflowState(s) {
  mounts.workflowState.textContent = s;
}

function showError(mount, whatHappened, why, nextActions) {
  mount.innerHTML = renderError({ whatHappened, why, nextActions });
  log(`${whatHappened}: ${why}`, 'error');
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const body = await res.json();
  if (!res.ok) {
    const err = new Error(body.error?.why || 'Request failed');
    err.whatHappened = body.error?.whatHappened || 'Request failed';
    throw err;
  }
  return body;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderChanges() {
  mounts.summary.innerHTML = renderSummaryBar(state.summary);
  mounts.changeList.innerHTML = renderChangeList(state.approvalSet, { editingChangeId: state.editingChangeId });
  const fullyDecided = state.summary && state.summary.pending === 0 && state.summary.total > 0;
  els.applyBtn.disabled = !fullyDecided;
}

async function loadTasks() {
  try {
    const { tasks } = await api('/api/tasks');
    mounts.taskList.innerHTML = renderTaskList(tasks);
  } catch (err) {
    showError(mounts.taskList, 'Could not load task registry', err.message);
  }
}

async function runCompare(baseBase64, baseName, targetBase64, targetName) {
  setWorkflowState('INGESTING');
  mounts.uploadError.innerHTML = '';
  els.compareBtn.setAttribute('aria-busy', 'true');
  try {
    setWorkflowState('UNDERSTANDING');
    const { report, approvalSet } = await api('/api/workspace/compare', {
      method: 'POST',
      body: JSON.stringify({ baseBase64, baseName, targetBase64, targetName }),
    });
    state.summary = { total: report.summary.totalChanges, approved: 0, rejected: 0, edited: 0, pending: report.summary.totalChanges };
    state.approvalSet = approvalSet;
    renderChanges();
    setWorkflowState('AWAITING_REVIEW');
    log(`Compared documents: ${report.summary.totalChanges} change(s) found`);
  } catch (err) {
    showError(mounts.uploadError, err.whatHappened || 'Compare failed', err.message, ['Retry']);
    setWorkflowState('FAILED');
  } finally {
    els.compareBtn.removeAttribute('aria-busy');
  }
}

els.compareBtn.addEventListener('click', async () => {
  const baseFile = els.baseFile.files?.[0];
  const targetFile = els.targetFile.files?.[0];
  if (!baseFile || !targetFile) {
    showError(mounts.uploadError, 'Missing document', 'Choose both a base and a target .docx file, or use the bundled sample.', []);
    return;
  }
  const [baseBase64, targetBase64] = await Promise.all([fileToBase64(baseFile), fileToBase64(targetFile)]);
  await runCompare(baseBase64, baseFile.name, targetBase64, targetFile.name);
});

els.useFixturesBtn.addEventListener('click', async () => {
  try {
    const [baseRes, targetRes] = await Promise.all([fetch('/sample/contract-v1.docx'), fetch('/sample/contract-v2.docx')]);
    const [baseBuf, targetBuf] = await Promise.all([baseRes.arrayBuffer(), targetRes.arrayBuffer()]);
    const toBase64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
    await runCompare(toBase64(baseBuf), 'contract-v1.docx', toBase64(targetBuf), 'contract-v2.docx');
  } catch (err) {
    showError(mounts.uploadError, 'Could not load sample contracts', err.message);
  }
});

mounts.changeList.addEventListener('click', async (e) => {
  const openBtn = e.target.closest('[data-edit-open]');
  if (openBtn) {
    state.editingChangeId = openBtn.dataset.editOpen;
    renderChanges();
    document.getElementById(`edit-textarea-${state.editingChangeId}`)?.focus();
    return;
  }

  const cancelBtn = e.target.closest('[data-edit-cancel]');
  if (cancelBtn) {
    state.editingChangeId = null;
    renderChanges();
    return;
  }

  const saveBtn = e.target.closest('[data-edit-save]');
  if (saveBtn) {
    const changeId = saveBtn.dataset.editSave;
    const textarea = document.getElementById(`edit-textarea-${changeId}`);
    const editedText = textarea?.value.trim();
    if (!editedText) {
      showError(mounts.uploadError, 'Empty replacement text', 'Enter text before saving, or Cancel to leave the change undecided.', []);
      return;
    }
    try {
      const { approvalSet, summary } = await api('/api/workspace/decide', {
        method: 'POST',
        body: JSON.stringify({ changeId, decision: 'edited', editedText }),
      });
      state.approvalSet = approvalSet;
      state.summary = summary;
      state.editingChangeId = null;
      renderChanges();
      log(`${changeId} -> edited`);
      setWorkflowState(summary.pending === 0 ? 'PARTIALLY_APPROVED' : 'AWAITING_REVIEW');
    } catch (err) {
      showError(mounts.uploadError, err.whatHappened || 'Edit failed', err.message);
    }
    return;
  }

  const btn = e.target.closest('.decide-btn[data-decision]');
  if (!btn) return;
  const changeId = btn.dataset.changeId;
  const decision = btn.dataset.decision;
  try {
    const { approvalSet, summary } = await api('/api/workspace/decide', {
      method: 'POST',
      body: JSON.stringify({ changeId, decision }),
    });
    state.approvalSet = approvalSet;
    state.summary = summary;
    renderChanges();
    log(`${changeId} -> ${decision}`);
    setWorkflowState(summary.pending === 0 ? 'PARTIALLY_APPROVED' : 'AWAITING_REVIEW');
  } catch (err) {
    showError(mounts.uploadError, err.whatHappened || 'Decision failed', err.message);
  }
});

els.applyBtn.addEventListener('click', async () => {
  setWorkflowState('APPLYING');
  els.applyBtn.setAttribute('aria-busy', 'true');
  try {
    const result = await api('/api/workspace/apply', { method: 'POST' });
    mounts.verification.innerHTML = renderVerificationCenter(result.verification);
    setWorkflowState(result.contentVerified ? 'VERIFIED' : 'UNVERIFIED');
    if (result.contentVerified) {
      log('Applied and verified — exported');
      els.downloadLink.hidden = false;
      setWorkflowState('EXPORTED');
      await loadVault();
    } else {
      log('Applied but verification found a mismatch — not marked verified', 'error');
    }
  } catch (err) {
    showError(mounts.uploadError, err.whatHappened || 'Apply failed', err.message, ['Review pending decisions', 'Retry']);
    setWorkflowState('FAILED');
  } finally {
    els.applyBtn.removeAttribute('aria-busy');
  }
});

async function loadVault() {
  try {
    const { graph, current } = await api('/api/vault/graph');
    mounts.vault.innerHTML = renderVaultGraph(graph, current?.versionId);
  } catch (err) {
    showError(mounts.vault, 'Could not load version history', err.message);
  }
}

mounts.vault.addEventListener('click', async (e) => {
  const revertBtn = e.target.closest('[data-revert-to]');
  if (!revertBtn) return;
  const versionId = revertBtn.dataset.revertTo;
  try {
    await api('/api/vault/revert', { method: 'POST', body: JSON.stringify({ versionId }) });
    log(`Vault: revert to ${versionId.slice(0, 8)}`);
    await loadVault();
  } catch (err) {
    showError(mounts.vault, err.whatHappened || 'Cannot revert', err.message);
  }
});

els.undoBtn.addEventListener('click', async () => {
  try {
    await api('/api/vault/undo', { method: 'POST' });
    log('Vault: undo');
    await loadVault();
  } catch (err) {
    showError(mounts.vault, 'Cannot undo', err.message);
  }
});

els.redoBtn.addEventListener('click', async () => {
  try {
    await api('/api/vault/redo', { method: 'POST' });
    log('Vault: redo');
    await loadVault();
  } catch (err) {
    showError(mounts.vault, 'Cannot redo', err.message);
  }
});

loadTasks();
loadVault();
log('Workspace ready');
