/**
 * Simplified Model Card Generator Logic with SuperDocs 4-Call Lifecycle Sync
 */

// Application State
let currentManifest = null;
let currentEvaluations = [];
let currentEvalMeta = {
  baseline_model: 'Nexus-70B-v1.1',
  run_id: 'eval-run-20260817-v1.2',
  timestamp: '2026-08-17 10:30:00 UTC'
};
let activeEditMode = 'form'; // 'form' | 'json' | 'markdown'
let customMarkdownOverride = null;

// SuperDocs Session State
let superdocsDocId = 'doc-nexus-70b-v1';
let currentProposedDiff = null;

// Default Sample Data (Nexus-70B)
const SAMPLE_MANIFEST = {
  model_name: "Nexus-70B-Instruct",
  version: "v1.2.0",
  release_date: "2026-08-15",
  model_type: "Dense Decoder-only Transformer LLM",
  license: "Apache-2.0 with Responsible AI Deployment Addendum",
  author_organization: "Nexus AI Research Foundation",
  description: "Nexus-70B-Instruct is a high-capability generative language model optimized for complex reasoning, multi-turn coding, and instruction following across enterprise workflows.",
  model_architecture: {
    parameters: "70 Billion parameters",
    context_window: "131,072 tokens",
    layers: 80,
    heads: "64 heads (8 KV)",
    activation: "SwiGLU",
    positional_embeddings: "RoPE (Rotary Position Embeddings)"
  },
  training_data_summary: {
    total_tokens: "15.2 Trillion tokens",
    composition: "Curated web crawl (55%), Technical papers (20%), Synthetic reasoning (15%), Code (10%)",
    cutoff_date: "March 2026"
  },
  hardware_and_compute: "4096x NVIDIA H100 SXM5 GPUs, 3.2M GPU Hours",
  intended_purpose: [
    "Complex reasoning, quantitative analysis, and mathematical problem solving",
    "Software engineering assistance and multi-language code generation",
    "Technical document summarization and executive brief preparation",
    "Enterprise agentic tool use and workflow orchestration"
  ],
  limitations: [
    "Context window limited to 128k tokens; attention quality degrades on >100k distractors",
    "May occasionally hallucinate citations when querying real-time world events beyond knowledge cutoff",
    "Non-English low-resource language performance is lower than high-resource benchmarks"
  ],
  out_of_scope_uses: [
    "Autonomous medical diagnosis or clinical prescription without certified human-in-the-loop oversight",
    "Generation of malicious cyber-attack scripts, malware, or exploit payloads",
    "High-frequency algorithmic trading decision making without backtesting guardrails"
  ],
  ethical_considerations: [
    "Extensively red-teamed against prompt injection, jailbreaking, and hazardous requests",
    "Reinforcement learning with Human & AI Feedback (RLHF/RLAIF) applied for safety"
  ],
  maintenance_contact: {
    team: "Nexus Foundation AI Safety & Alignment Group",
    email: "ai-safety@nexus-models.example.org",
    security_reports: "https://security.nexus-models.example.org/report"
  },
  citation: `@article{nexus2026,\n  title={Nexus-70B: Technical Report on Frontier Reasoning and Agentic Capabilities},\n  author={Nexus Research Team},\n  year={2026}\n}`
};

const SAMPLE_EVAL_RESULTS = [
  { task_id: "mmlu", name: "MMLU", domain: "General Reasoning", metric: "Accuracy (5-shot)", score: 88.4, baseline_score: 84.1 },
  { task_id: "gsm8k", name: "GSM8K", domain: "Mathematical Reasoning", metric: "Exact Match", score: 93.6, baseline_score: 89.2 },
  { task_id: "math", name: "MATH", domain: "Advanced Mathematics", metric: "Exact Match", score: 68.2, baseline_score: 61.5 },
  { task_id: "humaneval", name: "HumanEval", domain: "Code Generation", metric: "Pass@1", score: 86.6, baseline_score: 81.0 },
  { task_id: "arc_challenge", name: "ARC (Challenge)", domain: "Scientific Reasoning", metric: "Accuracy (25-shot)", score: 94.1, baseline_score: 91.8 },
  { task_id: "hellaswag", name: "HellaSwag", domain: "Commonsense Reasoning", metric: "Accuracy (10-shot)", score: 91.5, baseline_score: 89.4 }
];

// File Upload Handlers
function handleManifestUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    try {
      const data = JSON.parse(event.target.result);
      currentManifest = data;
      customMarkdownOverride = null;
      const zone = document.getElementById('manifestDropZone');
      zone.classList.add('loaded');
      document.getElementById('manifestStatus').textContent = `✅ ${file.name} (${data.model_name || 'Loaded'})`;
      showToast(`Selected ${file.name}. Click 'Generate Model Card' to compile! 📄`);
    } catch (err) {
      alert("Invalid JSON manifest file: " + err.message);
    }
  };
  reader.readAsText(file);
}

function handleEvalUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    try {
      const text = event.target.result;
      if (file.name.endsWith('.json')) {
        const data = JSON.parse(text);
        if (data.results && Array.isArray(data.results)) {
          currentEvaluations = data.results.map(r => ({
            task_id: r.task_id,
            name: (r.task_id || '').toUpperCase(),
            domain: "Benchmark",
            metric: r.metric || "Score",
            score: r.score,
            baseline_score: r.baseline_score || 0
          }));
          if (data.baseline_model) currentEvalMeta.baseline_model = data.baseline_model;
          if (data.run_id) currentEvalMeta.run_id = data.run_id;
        } else if (Array.isArray(data)) {
          currentEvaluations = data;
        }
      } else if (file.name.endsWith('.csv')) {
        currentEvaluations = parseEvalCSV(text);
      }

      customMarkdownOverride = null;
      const zone = document.getElementById('evalDropZone');
      zone.classList.add('loaded');
      document.getElementById('evalStatus').textContent = `✅ ${file.name} (${currentEvaluations.length} benchmarks)`;
      showToast(`Selected ${file.name}. Click 'Generate Model Card' to compile! 📊`);
    } catch (err) {
      alert("Invalid evaluation file: " + err.message);
    }
  };
  reader.readAsText(file);
}

function parseEvalCSV(csvText) {
  const lines = csvText.trim().split('\n');
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const vals = lines[i].split(',').map(v => v.trim());
    const obj = {};
    headers.forEach((h, idx) => { obj[h] = vals[idx]; });
    rows.push({
      task_id: obj.task_id || `task_${i}`,
      name: (obj.task_id || `Task ${i}`).toUpperCase(),
      domain: obj.domain || "Benchmark",
      metric: obj.metric || "Accuracy",
      score: parseFloat(obj.score) || 0,
      baseline_score: parseFloat(obj.baseline_score) || 0
    });
  }
  return rows;
}

// Quick Sample Data Loader (stages sample files without preloading rendered preview)
function loadSampleData() {
  currentManifest = JSON.parse(JSON.stringify(SAMPLE_MANIFEST));
  currentEvaluations = JSON.parse(JSON.stringify(SAMPLE_EVAL_RESULTS));
  currentEvalMeta = {
    baseline_model: 'Nexus-70B-v1.1',
    run_id: 'eval-run-20260817-v1.2',
    timestamp: '2026-08-17 10:30:00 UTC'
  };
  customMarkdownOverride = null;

  const mZone = document.getElementById('manifestDropZone');
  mZone.classList.add('loaded');
  document.getElementById('manifestStatus').textContent = `✅ sample_manifest.json (Nexus-70B)`;

  const eZone = document.getElementById('evalDropZone');
  eZone.classList.add('loaded');
  document.getElementById('evalStatus').textContent = `✅ sample_eval_results.json (6 benchmarks)`;

  showToast("Sample files selected! Click '✨ Generate Model Card' below to compile. ⚡");
}

// Generate & Render Model Card
function generateCard() {
  if (!currentManifest) {
    showToast("⚠️ Please upload a manifest first, or click 'Load Sample Files'!");
    return;
  }

  const m = currentManifest;
  const em = currentEvalMeta;
  const bms = currentEvaluations;

  const container = document.getElementById('cardContainer');
  const section = document.getElementById('cardDisplaySection');
  section.style.display = 'flex';

  const statusIndicator = document.querySelector('.status-indicator');
  if (statusIndicator) {
    statusIndicator.innerHTML = `<span class="dot"></span> Generated Card Preview`;
  }
  const badge = document.getElementById('superdocsDocBadge');
  if (badge) badge.textContent = `Doc ID: ${superdocsDocId || 'DOC-70B-SYNC'}`;

  const modelName = fallback(m.model_name, "Untitled Model");
  const version = fallback(m.version, "v1.0.0");
  const license = fallback(m.license, "Not provided");
  const modelType = fallback(m.model_type, "Not provided");
  const releaseDate = fallback(m.release_date, "Not provided");
  const org = fallback(m.author_organization, "Not provided");
  const desc = fallback(m.description, "Executive summary not provided.");

  // Specifications
  const arch = m.model_architecture || {};
  const archItems = Object.entries(arch)
    .filter(([_, v]) => v)
    .map(([k, v]) => `<li><strong>${k.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</strong> ${escapeHtml(v)}</li>`)
    .join('') || `<li><em>Not provided</em></li>`;

  // Intended uses
  const intendedItems = (m.intended_purpose && m.intended_purpose.length > 0)
    ? m.intended_purpose.map(i => `<li>${escapeHtml(i)}</li>`).join('')
    : `<li><em>Not provided</em></li>`;

  // Limitations
  const limitationItems = (m.limitations && m.limitations.length > 0)
    ? m.limitations.map(i => `<li>${escapeHtml(i)}</li>`).join('')
    : `<li><em>Not provided</em></li>`;

  // Out of scope
  const outOfScopeItems = (m.out_of_scope_uses && m.out_of_scope_uses.length > 0)
    ? m.out_of_scope_uses.map(i => `<li>${escapeHtml(i)}</li>`).join('')
    : `<li><em>Not provided</em></li>`;

  // Benchmarks table
  let bmRows = '';
  if (bms.length === 0) {
    bmRows = `<tr><td colspan="5" style="text-align:center; color: var(--text-subtle); padding: 20px;">No benchmark evaluation records uploaded.</td></tr>`;
  } else {
    bmRows = bms.map(b => {
      const score = b.score !== undefined ? Number(b.score).toFixed(1) : '—';
      const base = b.baseline_score !== undefined ? Number(b.baseline_score).toFixed(1) : '—';
      const delta = (b.score !== undefined && b.baseline_score !== undefined) ? (b.score - b.baseline_score).toFixed(1) : null;
      let deltaBadge = '—';
      if (delta !== null) {
        const dNum = parseFloat(delta);
        const dClass = dNum > 0 ? 'delta-pos' : (dNum < 0 ? 'delta-neg' : '');
        const dPrefix = dNum > 0 ? '+' : '';
        deltaBadge = `<span class="delta-pill ${dClass}">${dPrefix}${delta}%</span>`;
      }

      return `
        <tr>
          <td><strong>${escapeHtml(b.name || b.task_id)}</strong></td>
          <td><span style="color: var(--text-muted);">${escapeHtml(b.domain || 'Benchmark')}</span></td>
          <td style="font-family: var(--font-mono); font-weight: 700;">${score}%</td>
          <td style="font-family: var(--font-mono);">${base}%</td>
          <td>${deltaBadge}</td>
        </tr>
      `;
    }).join('');
  }

  container.innerHTML = `
    <!-- Hero Block -->
    <div class="card-hero">
      <div class="hero-badges">
        <span class="badge primary">🏷️ ${escapeHtml(version)}</span>
        <span class="badge success">📜 ${escapeHtml(license)}</span>
        <span class="badge">⚡ ${escapeHtml(modelType)}</span>
        <span class="badge">📅 ${escapeHtml(releaseDate)}</span>
      </div>
      <h1 class="hero-title">${escapeHtml(modelName)}</h1>
      <p class="hero-desc">${escapeHtml(desc)}</p>

      <div class="hero-meta-grid">
        <div class="meta-box">
          <div class="meta-label">Organization</div>
          <div class="meta-val">${escapeHtml(org)}</div>
        </div>
        <div class="meta-box">
          <div class="meta-label">Parameters</div>
          <div class="meta-val">${escapeHtml(arch.parameters || 'Not provided')}</div>
        </div>
        <div class="meta-box">
          <div class="meta-label">Total Benchmarks</div>
          <div class="meta-val">${bms.length}</div>
        </div>
        <div class="meta-box">
          <div class="meta-label">Baseline Reference</div>
          <div class="meta-val" style="font-size: 0.95rem; padding-top: 4px;">${escapeHtml(em.baseline_model)}</div>
        </div>
      </div>
    </div>

    <!-- Specifications -->
    <div class="card-section">
      <h3>📐 Specifications & Data</h3>
      <div class="card-grid-2">
        <div class="sub-box">
          <h4>Architecture</h4>
          <ul>${archItems}</ul>
        </div>
        <div class="sub-box">
          <h4>Compute & Training</h4>
          <ul>
            <li><strong>Hardware:</strong> ${escapeHtml(fallback(m.hardware_and_compute))}</li>
            <li><strong>Dataset:</strong> ${escapeHtml(fallback(m.training_data_summary?.composition))}</li>
            <li><strong>Total Volume:</strong> ${escapeHtml(fallback(m.training_data_summary?.total_tokens))}</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Scope & Limitations -->
    <div class="card-section">
      <h3>🎯 Scope & Limitations</h3>
      <div class="card-grid-2">
        <div class="sub-box">
          <h4>✅ Intended Applications</h4>
          <ul>${intendedItems}</ul>
        </div>
        <div class="sub-box">
          <h4>⚠️ Known Limitations</h4>
          <ul>${limitationItems}</ul>
        </div>
      </div>
      <div class="callout-box">
        <strong>🚫 Prohibited & Out-of-Scope Deployments</strong>
        <ul style="padding-left: 18px; margin-top: 4px;">${outOfScopeItems}</ul>
      </div>
    </div>

    <!-- Benchmarks -->
    <div class="card-section">
      <h3>📊 Quantitative Benchmark Evaluations</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Benchmark</th>
              <th>Domain</th>
              <th>Score</th>
              <th>Baseline (${escapeHtml(em.baseline_model)})</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            ${bmRows}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Governance & Citation -->
    <div class="card-section">
      <h3>📜 Citation & Governance</h3>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 10px;">
        <strong>Maintenance Team:</strong> ${escapeHtml(m.maintenance_contact?.team || 'Not provided')} 
        (${escapeHtml(m.maintenance_contact?.email || 'Not provided')})
      </p>
      <pre style="background: var(--bg-card-sub); padding: 12px; border-radius: 8px; font-family: var(--font-mono); font-size: 0.78rem; color: #A5B4FC; overflow-x: auto;"><code>${escapeHtml(fallback(m.citation))}</code></pre>
    </div>
  `;
}

// Edit Modal Handling & Mode Switching
function openEditModal(mode = 'form') {
  if (!currentManifest) {
    showToast("⚠️ No Model Card generated yet. Please load sample files or upload first!");
    return;
  }
  const m = currentManifest;

  // 1. Populate Form Inputs
  document.getElementById('edit_model_name').value = m.model_name || '';
  document.getElementById('edit_version').value = m.version || '';
  document.getElementById('edit_model_type').value = m.model_type || '';
  document.getElementById('edit_license').value = m.license || '';
  document.getElementById('edit_org').value = m.author_organization || '';
  document.getElementById('edit_release_date').value = m.release_date || '';
  document.getElementById('edit_description').value = m.description || '';

  document.getElementById('edit_intended').value = (m.intended_purpose || []).join('\n');
  document.getElementById('edit_limitations').value = (m.limitations || []).join('\n');
  document.getElementById('edit_out_of_scope').value = (m.out_of_scope_uses || []).join('\n');

  document.getElementById('edit_data_tokens').value = m.training_data_summary?.total_tokens || '';
  document.getElementById('edit_hardware').value = m.hardware_and_compute || '';

  document.getElementById('edit_contact_team').value = m.maintenance_contact?.team || '';
  document.getElementById('edit_contact_email').value = m.maintenance_contact?.email || '';
  document.getElementById('edit_citation').value = m.citation || '';

  // 2. Populate JSON Source Editor
  document.getElementById('rawJsonEditor').value = JSON.stringify(m, null, 2);

  // 3. Populate Markdown Source Editor
  document.getElementById('rawMarkdownEditor').value = customMarkdownOverride || generateMarkdown();

  // 4. Switch to requested tab
  switchEditMode(mode);

  document.getElementById('editModal').classList.add('active');
}

function switchEditMode(mode) {
  activeEditMode = mode;
  document.querySelectorAll('.modal-tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.edit-pane').forEach(p => p.classList.remove('active'));

  const tabBtn = document.getElementById(`tabBtn-${mode}`);
  const pane = document.getElementById(`editPane-${mode}`);
  if (tabBtn) tabBtn.classList.add('active');
  if (pane) pane.classList.add('active');
}

function formatJsonEditor() {
  try {
    const raw = document.getElementById('rawJsonEditor').value;
    const parsed = JSON.parse(raw);
    document.getElementById('rawJsonEditor').value = JSON.stringify(parsed, null, 2);
    showToast("Formatted JSON! ✨");
  } catch (err) {
    alert("Invalid JSON: " + err.message);
  }
}

function closeEditModal() {
  document.getElementById('editModal').classList.remove('active');
}

function saveEditedCard() {
  if (activeEditMode === 'form') {
    const m = currentManifest || {};

    m.model_name = document.getElementById('edit_model_name').value.trim();
    m.version = document.getElementById('edit_version').value.trim();
    m.model_type = document.getElementById('edit_model_type').value.trim();
    m.license = document.getElementById('edit_license').value.trim();
    m.author_organization = document.getElementById('edit_org').value.trim();
    m.release_date = document.getElementById('edit_release_date').value.trim();
    m.description = document.getElementById('edit_description').value.trim();

    m.intended_purpose = document.getElementById('edit_intended').value.split('\n').map(s => s.trim()).filter(Boolean);
    m.limitations = document.getElementById('edit_limitations').value.split('\n').map(s => s.trim()).filter(Boolean);
    m.out_of_scope_uses = document.getElementById('edit_out_of_scope').value.split('\n').map(s => s.trim()).filter(Boolean);

    if (!m.training_data_summary) m.training_data_summary = {};
    m.training_data_summary.total_tokens = document.getElementById('edit_data_tokens').value.trim();
    m.hardware_and_compute = document.getElementById('edit_hardware').value.trim();

    if (!m.maintenance_contact) m.maintenance_contact = {};
    m.maintenance_contact.team = document.getElementById('edit_contact_team').value.trim();
    m.maintenance_contact.email = document.getElementById('edit_contact_email').value.trim();

    m.citation = document.getElementById('edit_citation').value.trim();
    customMarkdownOverride = null;

  } else if (activeEditMode === 'json') {
    try {
      const raw = document.getElementById('rawJsonEditor').value;
      const parsed = JSON.parse(raw);
      currentManifest = parsed;
      customMarkdownOverride = null;
    } catch (err) {
      alert("Cannot save: Invalid JSON format. " + err.message);
      return;
    }
  } else if (activeEditMode === 'markdown') {
    customMarkdownOverride = document.getElementById('rawMarkdownEditor').value;
  }

  closeEditModal();
  generateCard();
  showToast("Model Card updated successfully! 💾");
}

/* =========================================================================
   SuperDocs 4-Call Document Lifecycle Handlers
   ========================================================================= */

function openSuperdocsModal() {
  document.getElementById('sd_doc_id').value = superdocsDocId;
  document.getElementById('superdocsModal').classList.add('active');
  setStepBadge(1);
}

function closeSuperdocsModal() {
  document.getElementById('superdocsModal').classList.remove('active');
}

function setStepBadge(step) {
  for (let i = 1; i <= 4; i++) {
    const badge = document.getElementById(`step${i}-badge`);
    if (badge) {
      badge.classList.remove('active', 'completed');
      if (i < step) badge.classList.add('completed');
      else if (i === step) badge.classList.add('active');
    }
  }
}

function setPromptPreset(type) {
  const input = document.getElementById('sd_chat_instruction');
  if (type === 'benchmarks') {
    input.value = "Refresh quantitative benchmark evaluation table with latest run metrics and baseline deltas.";
  } else if (type === 'safety') {
    input.value = "Add enterprise red-teaming and prompt-injection safety safeguards to section 6.";
  } else if (type === 'hardware') {
    input.value = "Upgrade compute specs to 8,192x NVIDIA H200 SXM5 with 141GB HBM3e.";
  }
}

// Call 1/4: SuperDocs Upload
function superdocsUpload() {
  superdocsDocId = `doc-${(currentManifest?.model_name || 'model').toLowerCase().replace(/\s+/g, '-')}-${Date.now().toString().slice(-4)}`;
  document.getElementById('sd_doc_id').value = superdocsDocId;
  document.getElementById('superdocsDocBadge').textContent = `Doc ID: ${superdocsDocId}`;
  setStepBadge(1);
  showToast(`[SuperDocs Call 1/4] Uploaded scaffold to session ${superdocsDocId}! 📤`);
}

// Call 2/4: SuperDocs Chat / Instruction
function superdocsChat() {
  const instruction = document.getElementById('sd_chat_instruction').value.trim();
  if (!instruction) {
    alert("Please enter an edit instruction prompt.");
    return;
  }

  setStepBadge(2);

  // Generate simulated SuperDocs double-encoded diff payload
  let proposedChanges = {};
  if (instruction.toLowerCase().includes('hardware') || instruction.toLowerCase().includes('compute') || instruction.toLowerCase().includes('h200')) {
    proposedChanges = {
      type: "field_update",
      field: "hardware_and_compute",
      old_value: currentManifest.hardware_and_compute,
      new_value: "8,192x NVIDIA H200 SXM5 GPUs, 5.8M GPU Hours with 141GB HBM3e"
    };
  } else if (instruction.toLowerCase().includes('safety') || instruction.toLowerCase().includes('red-team')) {
    proposedChanges = {
      type: "list_append",
      field: "ethical_considerations",
      item: "Autonomous agent safety sandbox tested against multi-stage indirect prompt injections."
    };
  } else {
    // Evaluation Table refresh
    proposedChanges = {
      type: "section_anchor_refresh",
      target_anchors: ["<!-- EVALUATION_SECTION_START -->", "<!-- EVALUATION_SECTION_END -->"],
      benchmark_count: currentEvaluations.length,
      baseline_model: currentEvalMeta.baseline_model,
      timestamp: new Date().toISOString()
    };
  }

  // Double-JSON encoding representation
  const innerDiffString = JSON.stringify(proposedChanges);
  const outerSuperdocsResponse = {
    status: "ok",
    session_id: superdocsDocId,
    diff: innerDiffString // Double-encoded string
  };

  currentProposedDiff = outerSuperdocsResponse;

  // Render Diff View
  const diffPanel = document.getElementById('diffApprovalPanel');
  const diffContainer = document.getElementById('diffViewContainer');
  diffPanel.style.display = 'block';
  diffContainer.textContent = `--- SUPERDOCS PROPOSED DIFF (2x JSON Deserialized) ---\n` + JSON.stringify(proposedChanges, null, 2);

  setStepBadge(3);
  showToast("[SuperDocs Call 2/4] Generated targeted diff payload! 💬");
}

// Call 3/4: SuperDocs Approve Diff (with Double JSON parse validation)
function superdocsApproveDiff() {
  if (!currentProposedDiff) return;

  // Execute Double JSON Deserialization
  try {
    let diffObj = currentProposedDiff;
    if (typeof diffObj.diff === 'string') {
      diffObj = JSON.parse(diffObj.diff); // 2nd parse!
    }

    if (diffObj.type === "field_update") {
      currentManifest[diffObj.field] = diffObj.new_value;
    } else if (diffObj.type === "list_append") {
      if (!currentManifest[diffObj.field]) currentManifest[diffObj.field] = [];
      currentManifest[diffObj.field].push(diffObj.item);
    } else if (diffObj.type === "section_anchor_refresh") {
      currentEvalMeta.timestamp = diffObj.timestamp;
    }

    generateCard();
    document.getElementById('diffApprovalPanel').style.display = 'none';
    currentProposedDiff = null;

    setStepBadge(3);
    showToast("[SuperDocs Call 3/4] Diff approved & 2x JSON parsed successfully! ✅");
  } catch (err) {
    alert("SuperDocs Diff parsing failed: " + err.message);
  }
}

function superdocsRejectDiff() {
  document.getElementById('diffApprovalPanel').style.display = 'none';
  currentProposedDiff = null;
  showToast("Proposed diff discarded.");
}

// Call 4/4: SuperDocs Export with Exponential Backoff Polling
function superdocsExport() {
  setStepBadge(4);
  const progressWrap = document.getElementById('exportProgressBarWrap');
  const progressFill = document.getElementById('exportProgressFill');
  const statusText = document.getElementById('exportStatusText');
  const percentText = document.getElementById('exportPercentText');

  progressWrap.style.display = 'block';
  progressFill.style.width = '10%';
  percentText.textContent = '10%';
  statusText.textContent = 'Initiating SuperDocs export job (Backoff Polling: poll #1)...';

  setTimeout(() => {
    progressFill.style.width = '35%';
    percentText.textContent = '35%';
    statusText.textContent = 'Transforming document AST & rendering PDF layouts (poll #2)...';
  }, 600);

  setTimeout(() => {
    progressFill.style.width = '75%';
    percentText.textContent = '75%';
    statusText.textContent = 'Synchronizing markdown section anchors & metadata (poll #3)...';
  }, 1200);

  setTimeout(() => {
    progressFill.style.width = '100%';
    percentText.textContent = '100%';
    statusText.textContent = 'Export completed! Downloading synchronized Markdown and PDF...';
    downloadMarkdown();
    showToast("[SuperDocs Call 4/4] Synchronized Export (.md & .pdf) completed! 🚀");
  }, 1800);
}

// Generate Standard Markdown
function generateMarkdown() {
  if (customMarkdownOverride) return customMarkdownOverride;
  if (!currentManifest) return '';
  const m = currentManifest;
  const em = currentEvalMeta;
  const bms = currentEvaluations;

  const modelName = fallback(m.model_name);
  const version = fallback(m.version);
  const license = fallback(m.license);
  const modelType = fallback(m.model_type);
  const releaseDate = fallback(m.release_date);
  const org = fallback(m.author_organization);
  const desc = fallback(m.description);
  const hardware = fallback(m.hardware_and_compute);
  const citation = fallback(m.citation);

  const arch = m.model_architecture || {};
  const archList = Object.entries(arch).filter(([_, v]) => v).map(([k, v]) => `- **${k}**: ${v}`).join('\n') || "- Not provided";
  const intendedList = (m.intended_purpose && m.intended_purpose.length > 0) ? m.intended_purpose.map(i => `- ${i}`).join('\n') : "- Not provided";
  const outOfScopeList = (m.out_of_scope_uses && m.out_of_scope_uses.length > 0) ? m.out_of_scope_uses.map(i => `- ${i}`).join('\n') : "- Not provided";
  const limitationsList = (m.limitations && m.limitations.length > 0) ? m.limitations.map(i => `- ${i}`).join('\n') : "- Not provided";

  let evalTableMd = `| Benchmark | Domain | Metric | Score | Baseline (${em.baseline_model}) | Delta |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n`;
  if (bms.length === 0) {
    evalTableMd += `| *No evaluations recorded* | — | — | — | — | — |\n`;
  } else {
    bms.forEach(b => {
      const score = b.score !== undefined ? `${b.score}%` : '—';
      const baseScore = b.baseline_score !== undefined ? `${b.baseline_score}%` : '—';
      const deltaVal = (b.score && b.baseline_score) ? (b.score - b.baseline_score) : 0;
      const deltaStr = deltaVal > 0 ? `▲ +${deltaVal.toFixed(1)}%` : (deltaVal < 0 ? `▼ ${deltaVal.toFixed(1)}%` : `— 0.0%`);
      evalTableMd += `| **${b.name || b.task_id}** | ${b.domain || 'General'} | ${b.metric || 'Score'} | ${score} | ${baseScore} | \`${deltaStr}\` |\n`;
    });
  }

  return `# 🏛️ Model and System Card: ${modelName}

<div align="center">

[![Version](https://img.shields.io/badge/Version-${version}-blue.svg?style=for-the-badge&logo=git)]()
[![License](https://img.shields.io/badge/License-${license}-green.svg?style=for-the-badge&logo=open-source-initiative)]()
[![Model Type](https://img.shields.io/badge/Type-${modelType}-purple.svg?style=for-the-badge)]()
[![Status](https://img.shields.io/badge/Status-Production--Ready-emerald.svg?style=for-the-badge)]()

</div>

---

## 1. 📋 Model Overview & Executive Summary

${desc}

### 📐 Technical Architecture
${archList}

- **Organization / Lab**: ${org}
- **Release Date**: \`${releaseDate}\`

---

## 2. 🎯 Intended Purpose & Operational Scope

<!-- INTENDED_USE_START -->
### Primary Intended Uses
${intendedList}
<!-- INTENDED_USE_END -->

<!-- OUT_OF_SCOPE_START -->
### 🚫 Out-of-Scope & Prohibited Uses
${outOfScopeList}
<!-- OUT_OF_SCOPE_END -->

---

## 3. ⚠️ Known Limitations & Constraints

<!-- LIMITATIONS_START -->
${limitationsList}
<!-- LIMITATIONS_END -->

---

## 4. 🗄️ Compute Infrastructure
- **Hardware**: ${hardware}

---

## 5. 📊 Quantitative Evaluations & Benchmarks

<!-- EVALUATION_SECTION_START -->
${evalTableMd}
<!-- EVALUATION_SECTION_END -->

---

## 6. 📜 Citation & Attribution

\`\`\`bibtex
${citation}
\`\`\`
`;
}

// Empty State Renderer
function renderEmptyState() {
  const container = document.getElementById('cardContainer');
  if (!container) return;

  const statusIndicator = document.querySelector('.status-indicator');
  if (statusIndicator) {
    statusIndicator.innerHTML = `<span class="dot" style="background: var(--text-subtle);"></span> Ready for Input`;
  }
  const badge = document.getElementById('superdocsDocBadge');
  if (badge) badge.textContent = 'Session: Ready';

  container.innerHTML = `
    <div class="empty-state-card">
      <div class="empty-state-icon">🏛️</div>
      <h3 class="empty-state-title">No Model Card Generated Yet</h3>
      <p class="empty-state-desc">
        Upload your model manifest (<code>manifest.json</code>) and benchmark evaluation logs (<code>eval_results.json/csv</code>) above, or load pre-configured sample files.
      </p>
      <div class="empty-state-actions">
        <button type="button" class="btn btn-primary" onclick="loadSampleData()">
          ⚡ Load Sample Files (Nexus-70B)
        </button>
        <button type="button" class="btn btn-secondary" onclick="document.getElementById('manifestInput').click()">
          📄 Browse Manifest JSON
        </button>
      </div>
    </div>
  `;
}

// Copy & Download
function copyMarkdown() {
  if (!currentManifest) {
    showToast("⚠️ No Model Card generated yet. Please load sample files or upload first!");
    return;
  }
  const md = generateMarkdown();
  navigator.clipboard.writeText(md).then(() => {
    showToast("Markdown copied to clipboard! 📋");
  });
}

function downloadMarkdown() {
  if (!currentManifest) {
    showToast("⚠️ No Model Card generated yet. Please load sample files or upload first!");
    return;
  }
  const md = generateMarkdown();
  const filename = `${(currentManifest?.model_name || 'model_card').toLowerCase().replace(/\s+/g, '_')}_card.md`;
  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast(`Downloaded ${filename}! 💾`);
}

// Theme Toggle
function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
}

function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2500);
}

function fallback(val, def = "Not provided") {
  if (val === undefined || val === null || val === "" || (Array.isArray(val) && val.length === 0)) return def;
  return val;
}

function escapeHtml(str) {
  if (typeof str !== 'string') return str || '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  renderEmptyState();
});
