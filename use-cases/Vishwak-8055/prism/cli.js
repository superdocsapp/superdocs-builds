#!/usr/bin/env node
// @ts-check
/**
 * Flagship demo, scoped to what this session actually built. The master
 * directive's full flagship scenario (Nexus, Proof, Target, Revision,
 * Reference, Grid, AgentDesk, ...) is not this — see docs/DEMO.md for the
 * honest mapping of which parts run for real here and which don't exist
 * yet. What follows is real: two real .docx files, a real diff, a
 * realistic reviewer decision on each change, real application back into
 * a real .docx, real re-verification, and a real version commit — driven
 * through the actual state machine, not narrated around it.
 */
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { compareFiles } from '@prism/delta';
import { createApprovalSet, summarize } from '@prism/gate';
import { Vault } from '@prism/vault';
import { runComposedWorkflow } from '@prism/registry';
import { listTasks, implementedTasks } from '@prism/registry';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const basePath = path.join(__dirname, 'packages', 'delta', 'fixtures', 'contract-v1.docx');
const targetPath = path.join(__dirname, 'packages', 'delta', 'fixtures', 'contract-v2.docx');
const outputPath = path.join(os.tmpdir(), `prism-demo-${Date.now()}.docx`);

console.log('PRISM — composed demo (Delta -> Gate -> Vault)');
console.log('='.repeat(50));
console.log(`Registry: ${listTasks().length} capabilities defined, ${implementedTasks().length} implemented for real this session:`);
for (const t of implementedTasks()) console.log(`  - ${t.name}: ${t.description}`);
console.log('');

const report = await compareFiles(basePath, targetPath);
console.log(`PRISM DELTA: ${report.summary.totalChanges} changes found (${report.summary.materialChangeCount} material, ${report.summary.reviewRequiredCount} review-required, ${report.summary.cosmeticOnlyCount} cosmetic)`);

// A realistic reviewer: auto-approve clearly material/cosmetic findings,
// send everything genuinely ambiguous (review-required) to... still a
// decision, because the demo must actually finish — but the POLICY here
// (approve material+cosmetic, reject review-required pending real human
// input) is exactly the kind of thing a real UI would ask a human for.
// This script states that plainly instead of hiding a canned choice.
const approvalSet = createApprovalSet(report);
const decisions = {};
for (const [changeId, entry] of approvalSet.decisions) {
  const materialities = entry.change.findings.map((f) => f.materiality);
  const policy = materialities.includes('material') || materialities.every((m) => m === 'cosmetic' || m === 'minor') ? 'approved' : 'rejected';
  decisions[changeId] = policy;
  console.log(`  ${changeId} [${entry.change.type}] materiality=${materialities.join(',')} -> ${policy} (auto-policy, not a human decision)`);
}
console.log('');

const result = await runComposedWorkflow({ basePath, targetPath, decisions, outputPath, vault: new Vault() });

console.log(`Workflow state history: ${result.workflow.history.map((h) => h.state).join(' -> ')}`);
console.log(`Decisions: ${JSON.stringify(summarize(result.approvalSet))}`);
console.log(`Applied output: ${outputPath}`);
console.log(`Vault version: ${result.version.versionId} (fingerprint ${result.version.fingerprint.slice(0, 12)}...)`);
console.log('');
console.log('Re-verification (independent of the workflow\'s own check): diffing output against base and target...');
const [vsBase, vsTarget] = await Promise.all([compareFiles(outputPath, basePath), compareFiles(outputPath, targetPath)]);
console.log(`  output vs base:   ${vsBase.summary.totalChanges} change(s) remain (the approved ones)`);
console.log(`  output vs target: ${vsTarget.summary.totalChanges} change(s) remain (the rejected ones)`);
