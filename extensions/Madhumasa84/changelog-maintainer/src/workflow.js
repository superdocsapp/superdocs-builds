import { readFile, stat } from 'node:fs/promises';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { sha256 } from './hash.js';
import { ChangelogError } from './errors.js';
import { parseCanonical, readCanonical, inferHouseStyle, buildReleaseBlock, itemKey } from './canonical.js';
import { validateRelease } from './schema.js';
import { defaultStateDir, makeRunId, loadManifest, saveManifest, checkpoint } from './state.js';
import { withCanonicalLock } from './lock.js';
import { exportArtifacts } from './export.js';
import { buildPublicationPlan } from './publication.js';

const MAX_RELEASES = 10;

async function readRelease(path) {
  let input;
  try { input = JSON.parse(await readFile(path, 'utf8')); } catch { throw new ChangelogError('release input is not valid JSON'); }
  const release = validateRelease(input);
  const resolved = resolve(path);
  if (resolved.endsWith('.docx') || resolved.endsWith('.pdf')) throw new ChangelogError('release input must be structured JSON');
  return release;
}

function safeGeneratedInput(releasePath, canonicalPath, release) {
  if (resolve(releasePath) === resolve(canonicalPath)) throw new ChangelogError('canonical output cannot be used as release input', 'SELF_TRIGGER', 11);
  if (release.metadata?.origin === 'superdocs-changelog-maintainer' || release.metadata?.generated_by === 'superdocs-changelog-maintainer') throw new ChangelogError('generated output cannot trigger another update', 'SELF_TRIGGER', 11);
}

function stemFor(canonicalPath, releaseId) {
  return `${basename(canonicalPath, extname(canonicalPath))}-${releaseId}`.replace(/[^A-Za-z0-9._-]+/g, '-');
}

async function assertOutputPathsAvailable(canonicalPath, releaseId, outputDir, overwrite) {
  if (overwrite) return;
  const targetDir = outputDir || join(dirname(canonicalPath), 'artifacts');
  const stem = stemFor(canonicalPath, releaseId);
  for (const extension of ['pdf', 'docx']) {
    const path = join(targetDir, `${stem}.${extension}`);
    try {
      await stat(path);
      throw new ChangelogError(`output already exists: ${path}`, 'OUTPUT_EXISTS', 21);
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
}

function expectedItems(manifest) {
  return manifest.release.items.map((item) => itemKey(manifest.release_id, item.id));
}

function decisionMap(manifest, accept, reject) {
  const known = new Set(expectedItems(manifest)); const next = { ...(manifest.decisions || {}) }; const seen = new Set();
  const values = [];
  for (const [state, ids] of [['approved', accept], ['rejected', reject]]) {
    for (const id of ids) {
      if (seen.has(id)) throw new ChangelogError(`duplicate or conflicting decision: ${id}`);
      seen.add(id);
      if (!known.has(id)) throw new ChangelogError(`unknown decision item: ${id}`);
      if (next[id]) throw new ChangelogError(`duplicate or conflicting decision: ${id}`);
      values.push([id, state]);
    }
  }
  for (const [id, state] of values) next[id] = state;
  return next;
}

function pendingItems(manifest) {
  return expectedItems(manifest).filter((id) => !manifest.decisions?.[id]);
}

function acceptedRelease(manifest) {
  const accepted = new Set(expectedItems(manifest).filter((id) => manifest.decisions[id] === 'approved'));
  return manifest.release.items.filter((item) => accepted.has(itemKey(manifest.release_id, item.id)));
}

function ensureManifestCandidate(manifest) {
  if (sha256(Buffer.from(manifest.candidate_block, 'utf8')) !== manifest.candidate_block_sha256) throw new ChangelogError('candidate block hash does not match durable state', 'STALE_APPROVAL', 11);
  if (manifest.approved_block !== undefined && (!manifest.approved_block_sha256 || sha256(Buffer.from(manifest.approved_block, 'utf8')) !== manifest.approved_block_sha256)) throw new ChangelogError('approved block hash does not match durable state', 'STALE_APPROVAL', 11);
}

export async function preview({ canonicalPath, releasePath, stateDir, failAt } = {}) {
  if (!canonicalPath || !releasePath) throw new ChangelogError('canonicalPath and releasePath are required');
  const canonical = await readCanonical(canonicalPath); const release = await readRelease(releasePath); safeGeneratedInput(releasePath, canonicalPath, release);
  if (canonical.releases.some((item) => item.id === release.release_id)) throw new ChangelogError(`duplicate release id: ${release.release_id}`, 'DUPLICATE_RELEASE', 10);
  // A canonical file may contain one pre-existing baseline release. The limit
  // applies to new maintainer updates, so allow that baseline plus ten
  // appended releases and stop before an eleventh update.
  if (canonical.releases.length > MAX_RELEASES) throw new ChangelogError(`stopping rule reached: at most ${MAX_RELEASES} sequential releases`, 'STOP_RULE', 10);
  const style = inferHouseStyle(canonical); const candidate = buildReleaseBlock(release, style); const runId = makeRunId(); const resolvedStateDir = stateDir || await defaultStateDir(canonicalPath);
  const manifest = { version: 1, run_id: runId, status: 'awaiting_decisions', canonical_path: resolve(canonicalPath), release_path: resolve(releasePath), state_dir: resolve(resolvedStateDir), release_id: release.release_id, release, style, input_sha256: sha256(await readFile(releasePath)), historical_prefix_sha256: sha256(canonical.bytes), expected_canonical_sha256: sha256(canonical.bytes), candidate_block_sha256: sha256(Buffer.from(candidate, 'utf8')), candidate_block: candidate, decisions: {}, feedback: {}, checkpoints: [], stop_rule: { max_sequential_releases: MAX_RELEASES, no_spend_preview: true, reject_self_generated_outputs: true }, output_hashes: {}, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
  const next = await checkpoint(resolvedStateDir, manifest, 'previewed', {}, failAt);
  return previewResult(next);
}

function previewResult(manifest) {
  return { status: manifest.status, run_id: manifest.run_id, release_id: manifest.release_id, candidate_block_sha256: manifest.candidate_block_sha256, historical_prefix_sha256: manifest.historical_prefix_sha256, decisions: manifest.decisions, pending_items: expectedItems(manifest), candidate_block: manifest.candidate_block, no_spend: true };
}

async function recoverOrAppend(manifest, { accept = [], reject = [], feedback = {}, outputDir, overwrite = false, failAt, resume = false } = {}) {
  ensureManifestCandidate(manifest);
  const stateDir = manifest.state_dir; const canonicalPath = manifest.canonical_path;
  return withCanonicalLock(canonicalPath, async () => {
    let current = await readCanonical(canonicalPath); const currentHash = sha256(current.bytes);
    if (manifest.status === 'append_started' && currentHash === manifest.output_hashes.canonical_sha256) {
      current = await readCanonical(canonicalPath); manifest = await checkpoint(stateDir, manifest, 'appended', { status: 'appended' }, failAt);
    } else if (manifest.status === 'append_started' && currentHash === manifest.expected_canonical_sha256) {
      const approvedBlock = manifest.approved_block || '';
      if (approvedBlock) {
        const after = Buffer.concat([current.bytes, current.bytes.length && !current.bytes.toString().endsWith('\n') ? Buffer.from('\n') : Buffer.alloc(0), Buffer.from(approvedBlock)]);
        const { atomicWrite } = await import('./io.js');
        await atomicWrite(canonicalPath, after, { mode: 0o600, overwrite: true });
        manifest = await checkpoint(stateDir, manifest, 'appended', { status: 'appended', output_hashes: { ...(manifest.output_hashes || {}), canonical_sha256: sha256(after) } }, failAt);
      } else {
        manifest = await checkpoint(stateDir, manifest, 'completed_no_change', { status: 'completed_no_change', output_hashes: { ...(manifest.output_hashes || {}), canonical_sha256: currentHash } }, failAt);
      }
    } else if (manifest.status === 'append_started') {
      throw new ChangelogError('canonical changelog changed after append started; recovery is ambiguous', 'STALE_CANONICAL', 11);
    }
    if (manifest.status === 'awaiting_decisions' || manifest.status === 'previewed') {
      if (!resume) manifest.decisions = decisionMap(manifest, accept, reject);
      const pending = pendingItems(manifest);
      manifest.feedback = { ...(manifest.feedback || {}), ...feedback };
      manifest = await checkpoint(stateDir, manifest, 'decisions_recorded', { decisions: manifest.decisions, feedback: manifest.feedback }, failAt);
      if (pending.length > 0) return { ...previewResult(manifest), pending_items: pending, decisions: manifest.decisions };
      ensureManifestCandidate(manifest);
      current = await readCanonical(canonicalPath);
      if (sha256(current.bytes) !== manifest.expected_canonical_sha256) throw new ChangelogError('canonical changelog changed since preview; create a new preview', 'STALE_CANONICAL', 11);
      const approvedItems = acceptedRelease(manifest); const approvedBlock = approvedItems.length ? buildReleaseBlock(manifest.release, manifest.style, approvedItems) : '';
      if (approvedBlock) await assertOutputPathsAvailable(canonicalPath, manifest.release_id, outputDir, overwrite);
      manifest = await checkpoint(stateDir, manifest, 'append_started', { status: 'append_started', approved_block_sha256: sha256(Buffer.from(approvedBlock, 'utf8')), approved_block: approvedBlock }, failAt);
      if (approvedBlock) {
        const after = Buffer.concat([current.bytes, current.bytes.length && !current.bytes.toString().endsWith('\n') ? Buffer.from('\n') : Buffer.alloc(0), Buffer.from(approvedBlock)]);
        const { atomicWrite } = await import('./io.js'); await atomicWrite(canonicalPath, after, { mode: 0o600, overwrite: true });
        manifest = await checkpoint(stateDir, manifest, 'appended', { status: 'appended', output_hashes: { ...(manifest.output_hashes || {}), canonical_sha256: sha256(after) } }, failAt);
      } else {
        manifest = await checkpoint(stateDir, manifest, 'appended', { status: 'completed_no_change', output_hashes: { ...(manifest.output_hashes || {}), canonical_sha256: sha256(current.bytes) } }, failAt);
      }
    }
    if (manifest.status === 'appended' || manifest.status === 'export_started') {
      const now = await readFile(canonicalPath, 'utf8'); const targetDir = outputDir || join(dirname(canonicalPath), 'artifacts');
      manifest = await checkpoint(stateDir, manifest, 'export_started', { status: 'export_started' }, failAt);
      const outputs = await exportArtifacts({ canonicalText: now, outputDir: targetDir, stem: stemFor(canonicalPath, manifest.release_id), releaseId: manifest.release_id, runId: manifest.run_id, overwrite, failAt });
      manifest = await checkpoint(stateDir, manifest, 'exported', { status: 'completed', output_hashes: { ...(manifest.output_hashes || {}), canonical_sha256: sha256(Buffer.from(now)), pdf_sha256: outputs.pdf.sha256, docx_sha256: outputs.docx.sha256 }, outputs }, failAt);
    }
    await saveManifest(stateDir, manifest);
    if (manifest.status === 'completed_no_change') return { status: manifest.status, run_id: manifest.run_id, release_id: manifest.release_id, decisions: manifest.decisions, output_hashes: manifest.output_hashes, rejected_items: expectedItems(manifest).filter((id) => manifest.decisions[id] === 'rejected') };
    return { status: manifest.status, run_id: manifest.run_id, release_id: manifest.release_id, decisions: manifest.decisions, output_hashes: manifest.output_hashes, outputs: manifest.outputs, rejected_items: expectedItems(manifest).filter((id) => manifest.decisions[id] === 'rejected') };
  });
}

export async function approve({ runId, accept = [], reject = [], feedback = {}, stateDir, outputDir, overwrite = false, failAt } = {}) {
  if (!runId) throw new ChangelogError('runId is required');
  const manifest = await loadManifest(stateDir, runId);
  if (manifest.status === 'completed' || manifest.status === 'completed_no_change') return { status: manifest.status, run_id: runId, output_hashes: manifest.output_hashes, outputs: manifest.outputs };
  return recoverOrAppend(manifest, { accept, reject, feedback, outputDir, overwrite, failAt });
}

export async function resume({ runId, stateDir, outputDir, overwrite = false, failAt } = {}) {
  const manifest = await loadManifest(stateDir, runId);
  if (manifest.status === 'awaiting_decisions' || manifest.status === 'previewed') return recoverOrAppend(manifest, { outputDir, overwrite, failAt, resume: true });
  return recoverOrAppend(manifest, { outputDir, overwrite, failAt, resume: true });
}

export async function publicationDryRun({ runId, stateDir, repository, base }) {
  const manifest = await loadManifest(stateDir, runId);
  return buildPublicationPlan({ canonicalPath: manifest.canonical_path, releaseId: manifest.release_id, outputPaths: manifest.outputs ? [manifest.outputs.pdf.path, manifest.outputs.docx.path] : [], outputHashes: manifest.output_hashes, repository, base });
}

export async function status({ runId, stateDir }) {
  const manifest = await loadManifest(stateDir, runId);
  return { status: manifest.status, run_id: manifest.run_id, release_id: manifest.release_id, decisions: manifest.decisions, checkpoints: manifest.checkpoints, output_hashes: manifest.output_hashes, pending_items: pendingItems(manifest) };
}
