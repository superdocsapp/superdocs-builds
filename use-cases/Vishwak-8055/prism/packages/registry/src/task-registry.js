// @ts-check
/**
 * Every PRISM capability the master directive names, as data. Selecting a
 * task is supposed to compose shared capabilities — this registry is what
 * makes that composition inspectable rather than implicit in code.
 *
 * IMPLEMENTED (3): delta, gate, vault — real code in @prism/delta,
 * @prism/gate, @prism/vault, wired together in workflow-engine.js.
 *
 * NOT_IMPLEMENTED (27): listed with an honest reason, not silently
 * omitted. A registry entry existing is not the same as the capability
 * being built — see the directive's own "FINAL TASK COMPLETION RULE."
 * Most of the reasons fall into one of three buckets, stated once here
 * rather than repeated 27 times:
 *   (a) needs a semantic-reasoning/model tier this offline package
 *       deliberately doesn't wire in (see docs/KNOWN_LIMITATIONS.md)
 *   (b) needs a live external integration (cloud storage, email, browser,
 *       Office, e-signature, MCP client) this sandbox has no credentials
 *       or runtime for
 *   (c) needs infrastructure (a real UI, a database, a benchmark corpus at
 *       scale, cross-browser/screen-reader tooling) not built this session
 */

const IMPLEMENTED = {
  'prism-delta': {
    task_id: 'prism-delta',
    name: 'PRISM DELTA',
    description: 'Material-change intelligence between two document versions.',
    status: 'implemented',
    inputs: ['basePath', 'targetPath'],
    required_capabilities: ['document_model', 'structural_diff', 'semantic_diff', 'numeric_diff', 'date_diff', 'formatting_diff'],
    optional_capabilities: ['impact_analysis (partial: materiality tiers only, no legal judgment)'],
    agents: [],
    tools: ['@prism/core#readDocx', '@prism/core#alignParagraphs'],
    permissions: ['read:document'],
    review_policy: 'every "semantic" and "structural" finding is review-required by construction — never auto-approved',
    verification_policy: 'true-negative tested (unchanged text never flagged)',
    export_policy: 'JSON report only; no document mutation',
    failure_policy: 'throws on missing/invalid file, never returns partial results silently',
    acceptance_tests: '@prism/delta test suite',
    package: '@prism/delta',
  },
  'prism-gate': {
    task_id: 'prism-gate',
    name: 'PRISM GATE',
    description: 'Approval fidelity: stable change IDs, approve/reject/edit, exact application.',
    status: 'implemented',
    inputs: ['deltaReport', 'decisions'],
    required_capabilities: ['document_model', 'change_identity', 'approval_tracking', 'edit_engine'],
    optional_capabilities: [],
    agents: [],
    tools: ['@prism/core#writeDocx'],
    permissions: ['read:document', 'write:document'],
    review_policy: 'applyApprovedChanges refuses to run while any decision is pending — no default-approve or default-reject',
    verification_policy: 'exactness independently checked by re-running PRISM DELTA against the applied output (see @prism/gate tests)',
    export_policy: 'writes a real .docx; refuses (does not silently corrupt) if the source document contains tables',
    failure_policy: 'throws with the specific pending change IDs; throws on unknown changeId or invalid decision value',
    acceptance_tests: '@prism/gate test suite',
    package: '@prism/gate',
  },
  'prism-vault': {
    task_id: 'prism-vault',
    name: 'PRISM VAULT',
    description: 'Exact version/revert engine with immutable version identity.',
    status: 'implemented',
    inputs: ['paragraphs'],
    required_capabilities: ['document_model', 'fingerprinting', 'version_graph'],
    optional_capabilities: [],
    agents: [],
    tools: ['@prism/core#fingerprintParagraphs'],
    permissions: ['read:version_state'],
    review_policy: 'not applicable — versioning is deterministic infrastructure, not a review surface',
    verification_policy: 'every undo/redo/revert re-hashes restored content and throws on mismatch rather than trusting the stored label',
    export_policy: 'in-memory version graph; no document export of its own (paired with @prism/core#writeDocx via the workflow engine for that)',
    failure_policy: 'throws on undo/redo past the timeline bounds, and on revertTo an unknown version id',
    acceptance_tests: '@prism/vault test suite',
    package: '@prism/vault',
  },
  'prism-grid': {
    task_id: 'prism-grid',
    name: 'PRISM GRID',
    description: 'Table structural fidelity: verbatim write-back plus structural comparison (merges, cell text, row/column shape).',
    status: 'implemented',
    inputs: ['docA', 'docB'],
    required_capabilities: ['document_model', 'table_model', 'structural_comparison'],
    optional_capabilities: [],
    agents: [],
    tools: ['@prism/core#readDocx (table extraction)', '@prism/core#writeDocx (table-aware path)'],
    permissions: ['read:document', 'write:document'],
    review_policy: 'not applicable — structural comparison is deterministic, not a judgment call',
    verification_policy: 'compareTableStructure/compareDocumentTables are the verification mechanism itself — a table is only reported PASS when genuinely structurally identical, tested against real merged-cell fixtures (gridSpan and vMerge)',
    export_policy: 'tables are never edited/regenerated — always passed through verbatim from the source, anchored to their original position',
    failure_policy: 'writeDocx refuses (does not silently corrupt) when a table-containing document also needs a paragraph-count change (structural add/remove) — that combination is not yet supported; everything else (content/formatting edits alongside tables) works',
    acceptance_tests: '@prism/grid test suite + @prism/core write-docx table tests',
    package: '@prism/grid',
  },
};

const REASON_MODEL_TIER =
  'Requires a semantic-reasoning/model tier (retrieval, evidence interpretation, or natural-language judgment) that this offline, no-API-key package deliberately does not wire in — see docs/KNOWN_LIMITATIONS.md. Not started this session.';
const REASON_EXTERNAL_INTEGRATION =
  'Requires a live external integration (cloud storage, email, browser, Office, e-signature, or an MCP client/server) this sandbox has no credentials or runtime target for. Not started this session.';
const REASON_INFRASTRUCTURE =
  'Requires infrastructure not built this session (a real UI, a persistent database, a benchmark corpus run at scale, or cross-browser/screen-reader tooling this sandbox cannot drive). Not started this session.';

const NOT_IMPLEMENTED = [
  { task_id: 'prism-nexus', name: 'PRISM NEXUS', description: 'Multi-document reasoning.', required_capabilities: ['multi_document_retrieval', 'evidence_graph', 'reasoning'], reason_not_implemented: REASON_MODEL_TIER },
  { task_id: 'prism-proof', name: 'PRISM PROOF', description: 'Citation and claim verification.', required_capabilities: ['claim_extraction', 'citation_resolution', 'support_analysis'], reason_not_implemented: REASON_MODEL_TIER },
  { task_id: 'prism-target', name: 'PRISM TARGET', description: 'Precision section targeting.', required_capabilities: ['structural_targeting', 'semantic_targeting'], reason_not_implemented: REASON_MODEL_TIER },
  { task_id: 'prism-adapt', name: 'PRISM ADAPT', description: 'Adaptive model/cost routing.', required_capabilities: ['model_routing', 'cost_measurement'], reason_not_implemented: 'Requires calling multiple real model providers to measure quality/latency/cost trade-offs; nothing to route between without live model calls. ' + REASON_MODEL_TIER },
  { task_id: 'prism-revision', name: 'PRISM REVISION', description: 'Revision-preserving editing.', required_capabilities: ['tracked_changes_model'], reason_not_implemented: 'read-docx.js explicitly does not parse <w:ins>/<w:del> — see docs/KNOWN_LIMITATIONS.md. Not started this session.' },
  { task_id: 'prism-reference', name: 'PRISM REFERENCE', description: 'Notes/citation/cross-reference integrity.', required_capabilities: ['footnote_model', 'cross_ref_model'], reason_not_implemented: 'Out of scope for the current document model, which reads body paragraphs only. Not started this session.' },
  { task_id: 'prism-vis', name: 'PRISM VIS', description: 'Visual/math fidelity.', required_capabilities: ['image_model', 'equation_model'], reason_not_implemented: REASON_INFRASTRUCTURE },
  { task_id: 'prism-agentdesk', name: 'PRISM AGENTDESK', description: 'Agent document workspace.', required_capabilities: ['agent_identity', 'claimed_vs_actual_detection'], reason_not_implemented: 'Needs at least one real agent role acting with bounded permissions to compare claimed vs. actual — no agent runtime built this session. ' + REASON_MODEL_TIER },
  { task_id: 'prism-mesh', name: 'PRISM MESH', description: 'Concurrent editing/conflict handling.', required_capabilities: ['version_awareness', 'conflict_detection'], reason_not_implemented: 'Builds directly on @prism/vault\'s version graph (the prerequisite now exists) but the concurrent-writer simulation and conflict-resolution UI are not built. Not started this session.' },
  { task_id: 'prism-bridge', name: 'PRISM BRIDGE', description: 'Cloud document synchronization/write-back.', required_capabilities: ['cloud_read', 'cloud_write'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-scale', name: 'PRISM SCALE', description: 'Long-document performance laboratory.', required_capabilities: ['benchmark_harness'], reason_not_implemented: REASON_INFRASTRUCTURE },
  { task_id: 'prism-protocol', name: 'PRISM PROTOCOL', description: 'MCP/client conformance.', required_capabilities: ['mcp_client'], reason_not_implemented: 'The real @superdoc/mcp package is not built/runnable outside its monorepo (see prism-delta README from the prior session). ' + REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-flight', name: 'PRISM FLIGHT', description: 'Agent/document observability.', required_capabilities: ['telemetry_schema', 'trace_store'], reason_not_implemented: REASON_INFRASTRUCTURE },
  { task_id: 'prism-runtime', name: 'PRISM RUNTIME', description: 'Framework/runtime adapter architecture.', required_capabilities: ['adapter_contract_tests'], reason_not_implemented: 'No second framework/runtime target exists yet to write an adapter contract against. Not started this session.' },
  { task_id: 'prism-inbox', name: 'PRISM INBOX', description: 'Mailbox document workflow.', required_capabilities: ['email_ingestion'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-sign', name: 'PRISM SIGN', description: 'External signing handoff.', required_capabilities: ['signing_boundary'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-truthset', name: 'PRISM TRUTHSET', description: 'Golden document corpus.', required_capabilities: ['fixture_provenance_tracking'], reason_not_implemented: 'Only 2 fixtures exist (the contract pair); a real corpus needs many more documents across types with tracked provenance/license metadata. ' + REASON_INFRASTRUCTURE },
  { task_id: 'prism-judge', name: 'PRISM JUDGE', description: 'Evaluation/judging laboratory.', required_capabilities: ['automated_eval', 'human_eval_comparison'], reason_not_implemented: REASON_MODEL_TIER },
  { task_id: 'prism-replay', name: 'PRISM REPLAY', description: 'Reproducibility.', required_capabilities: ['run_pinning'], reason_not_implemented: 'Partially covered informally (fixtures + package-lock.json pin the environment) but no formal run-pinning/replay harness exists. Not started this session.' },
  { task_id: 'prism-research', name: 'PRISM RESEARCH', description: 'Search → evidence → cited document.', required_capabilities: ['web_search', 'citation_repair'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-pulse', name: 'PRISM PULSE', description: 'Database → living report.', required_capabilities: ['database_connector'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-office', name: 'PRISM OFFICE', description: 'Office integration architecture.', required_capabilities: ['host_adapter'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-side', name: 'PRISM SIDE', description: 'Browser side-panel document copilot.', required_capabilities: ['browser_extension_runtime'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
  { task_id: 'prism-memory', name: 'PRISM MEMORY', description: 'Past-work/session browser.', required_capabilities: ['session_persistence', 'session_search'], reason_not_implemented: REASON_INFRASTRUCTURE },
  { task_id: 'prism-continuum', name: 'PRISM CONTINUUM', description: 'Living document/stateful agent.', required_capabilities: ['durable_state', 'stopping_rules'], reason_not_implemented: 'Builds on @prism/vault for durable state (prerequisite now exists) but the agent loop, stopping rules, and no-spend preview are not built. ' + REASON_MODEL_TIER },
  { task_id: 'prism-connect', name: 'PRISM CONNECT', description: 'Secure integration fabric.', required_capabilities: ['connector_contract'], reason_not_implemented: REASON_EXTERNAL_INTEGRATION },
];

export const TASK_REGISTRY = Object.freeze(
  Object.fromEntries([
    ...Object.entries(IMPLEMENTED),
    ...NOT_IMPLEMENTED.map((t) => [t.task_id, { ...t, status: 'not_implemented' }]),
  ]),
);

export function listTasks() {
  return Object.values(TASK_REGISTRY);
}

export function getTask(taskId) {
  const task = TASK_REGISTRY[taskId];
  if (!task) throw new Error(`Registry: unknown task_id "${taskId}"`);
  return task;
}

export function implementedTasks() {
  return listTasks().filter((t) => t.status === 'implemented');
}
