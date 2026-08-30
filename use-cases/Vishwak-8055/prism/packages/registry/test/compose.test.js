import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { compareFiles } from '@prism/delta';
import { createApprovalSet } from '@prism/gate';
import { Vault } from '@prism/vault';
import { runComposedWorkflow } from '../src/compose.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v1.docx');
const v2Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v2.docx');

function tmp(name) {
  return path.join(os.tmpdir(), `prism-compose-${name}-${Date.now()}.docx`);
}

async function decisionsFor(basePath, targetPath, decisionValue) {
  const report = await compareFiles(basePath, targetPath);
  const approvalSet = createApprovalSet(report);
  const decisions = {};
  for (const changeId of approvalSet.decisions.keys()) decisions[changeId] = decisionValue;
  return decisions;
}

test('full composed workflow: approve everything reaches EXPORTED with a vault version', async () => {
  const decisions = await decisionsFor(v1Path, v2Path, 'approved');
  const vault = new Vault();
  const outputPath = tmp('happy');

  const result = await runComposedWorkflow({ basePath: v1Path, targetPath: v2Path, decisions, outputPath, vault });

  assert.equal(result.workflow.state, 'EXPORTED');
  assert.equal(result.workflow.isTerminal(), true);
  assert.equal(vault.graph().length, 1);
  assert.equal(result.version.versionId, vault.current().versionId);

  const finalDiff = await compareFiles(outputPath, v2Path);
  assert.equal(finalDiff.summary.hasChanges, false, 'fully-approved workflow output must equal target exactly');

  const states = result.workflow.history.map((h) => h.state);
  assert.deepEqual(states, [
    'CREATED', 'INGESTING', 'UNDERSTANDING', 'PLANNING', 'PROPOSED',
    'AWAITING_REVIEW', 'PARTIALLY_APPROVED', 'APPLYING', 'VERIFYING', 'VERIFIED', 'EXPORTED',
  ]);
});

test('incomplete decisions land in NEEDS_REVIEW, not a silent default', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  const ids = [...approvalSet.decisions.keys()];
  const partialDecisions = {};
  partialDecisions[ids[0]] = 'approved'; // only decide 1 of 5

  await assert.rejects(
    () => runComposedWorkflow({ basePath: v1Path, targetPath: v2Path, decisions: partialDecisions, outputPath: tmp('incomplete') }),
    (err) => {
      assert.match(err.message, /not every change was decided/);
      assert.equal(err.workflow.state, 'NEEDS_REVIEW');
      return true;
    },
  );
});

test('a mixed approve/reject/edit run still reaches EXPORTED with a verified version', async () => {
  const report = await compareFiles(v1Path, v2Path);
  const approvalSet = createApprovalSet(report);
  const ids = [...approvalSet.decisions.keys()];
  const decisions = {};
  ids.forEach((id, i) => {
    decisions[id] = i === 0 ? 'approved' : 'rejected';
  });

  const outputPath = tmp('mixed');
  const result = await runComposedWorkflow({ basePath: v1Path, targetPath: v2Path, decisions, outputPath });
  assert.equal(result.workflow.state, 'EXPORTED');

  const diffFromBase = await compareFiles(outputPath, v1Path);
  assert.equal(diffFromBase.summary.totalChanges, 1, 'only the one approved change should differ from base');
});
