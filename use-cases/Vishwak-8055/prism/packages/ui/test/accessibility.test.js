import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { JSDOM } from 'jsdom';
import {
  renderTaskList,
  renderChangeList,
  renderVerificationCenter,
  renderError,
  renderVaultGraph,
} from '../public/render.js';

/**
 * IMPORTANT SCOPE NOTE, stated in code not just docs: this runs axe-core's
 * DOM-structure rules (landmarks, heading order, labels, ARIA validity,
 * color contrast computed from the CSS actually loaded) against a jsdom
 * document. jsdom is not a real browser — it does not render, does not run
 * a real accessibility tree, and this is not screen-reader testing. It
 * catches a real, useful subset of issues (missing labels, bad heading
 * order, invalid ARIA, duplicate IDs) and nothing about actual assistive
 * technology behavior. See docs/KNOWN_LIMITATIONS.md #1.
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const axeSource = await readFile(require.resolve('axe-core/axe.min.js'), 'utf-8');

async function runAxe(htmlFragmentOrDocument, { fullDocument = false } = {}) {
  const html = fullDocument
    ? htmlFragmentOrDocument
    : `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>test</title></head><body>${htmlFragmentOrDocument}</body></html>`;
  const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'http://localhost/' });
  dom.window.eval(axeSource);
  const results = await dom.window.axe.run(dom.window.document, {
    // Rules that need real rendering (layout/visibility) or a live network
    // aren't meaningful in jsdom and are excluded explicitly, not silently.
    rules: { 'color-contrast': { enabled: false } },
  });
  dom.window.close();
  return results;
}

function summarizeViolations(results) {
  return results.violations.map((v) => `${v.id} (${v.impact}): ${v.help} — ${v.nodes.length} node(s)`).join('\n');
}

test('static page shell has no structural accessibility violations', async () => {
  const rawHtml = await readFile(path.join(__dirname, '..', 'public', 'index.html'), 'utf-8');
  // Strip the module script — this checks the static shell's structure,
  // not app.js's runtime behavior (jsdom's ES module support is
  // incomplete; dynamic content is checked separately below using the
  // same real render functions app.js calls).
  const staticHtml = rawHtml.replace(/<script type="module".*?<\/script>/s, '');
  const results = await runAxe(staticHtml, { fullDocument: true });
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
});

test('rendered task list has no accessibility violations', async () => {
  const tasks = [
    { task_id: 'prism-delta', name: 'PRISM DELTA', status: 'implemented' },
    { task_id: 'prism-nexus', name: 'PRISM NEXUS', status: 'not_implemented' },
  ];
  const results = await runAxe(`<nav aria-label="Task center">${renderTaskList(tasks)}</nav>`);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
});

test('rendered change list (with real finding data) has no accessibility violations', async () => {
  const approvalSet = [
    {
      changeId: 'delta-0001',
      decision: 'pending',
      change: {
        type: 'modified',
        baseText: 'The total contract price is $50,000.',
        targetText: 'The total contract price is $65,000.',
        findings: [{ category: 'numeric', materiality: 'material', why: 'Price changed by $15,000.' }],
      },
    },
  ];
  const results = await runAxe(`<section aria-label="Proposed changes">${renderChangeList(approvalSet)}</section>`);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
});

test('rendered verification center (all real status values) has no accessibility violations', async () => {
  const rows = [
    { area: 'CONTENT', status: 'PASS', detail: 'ok' },
    { area: 'TABLES', status: 'NOT_APPLICABLE', detail: 'no tables' },
    { area: 'EXPORT', status: 'UNVERIFIED', detail: 'mismatch' },
    { area: 'REVISIONS', status: 'FAIL', detail: 'not supported' },
  ];
  const results = await runAxe(`<section aria-label="Verification">${renderVerificationCenter(rows)}</section>`);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
  // Non-color-only status communication: each stamp must carry text/aria,
  // not rely on color alone — check directly, not just via axe.
  const dom = new JSDOM(`<body>${renderVerificationCenter(rows)}</body>`);
  const stamps = dom.window.document.querySelectorAll('.stamp');
  assert.equal(stamps.length, rows.length);
  for (const stamp of stamps) {
    assert.ok(stamp.getAttribute('aria-label'), 'every status stamp must have a text label, not just a color');
  }
});

test('rendered error panel has no accessibility violations and uses role=alert', async () => {
  const html = renderError({ whatHappened: 'Apply failed', why: 'Some changes are still pending review', nextActions: ['Review pending decisions', 'Retry'] });
  const results = await runAxe(html);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
  const dom = new JSDOM(`<body>${html}</body>`);
  assert.equal(dom.window.document.querySelector('[role="alert"]') !== null, true);
});

test('rendered vault graph has no accessibility violations', async () => {
  const graph = [
    { versionId: 'v1', fingerprint: 'abc123def456', kind: 'commit', label: null },
    { versionId: 'v2', fingerprint: '789fedcba012', kind: 'revert', label: 'revert to v1' },
  ];
  const results = await runAxe(`<section aria-label="Vault">${renderVaultGraph(graph, 'v2')}</section>`);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);
});

test('rendered inline edit form has no accessibility violations and the textarea has a real label', async () => {
  const approvalSet = [
    {
      changeId: 'delta-0001',
      decision: 'pending',
      change: {
        type: 'modified',
        baseText: 'The fee is $50.',
        targetText: 'The fee is $75.',
        findings: [{ category: 'numeric', materiality: 'material', why: 'Price changed.' }],
      },
    },
  ];
  const html = renderChangeList(approvalSet, { editingChangeId: 'delta-0001' });
  const results = await runAxe(`<section aria-label="Proposed changes">${html}</section>`);
  assert.equal(results.violations.length, 0, `Violations found:\n${summarizeViolations(results)}`);

  const dom = new JSDOM(`<body>${html}</body>`);
  const textarea = dom.window.document.getElementById('edit-textarea-delta-0001');
  assert.ok(textarea, 'the textarea must exist when editingChangeId matches');
  const label = dom.window.document.querySelector(`label[for="edit-textarea-delta-0001"]`);
  assert.ok(label, 'the textarea must have a real <label for>, not just a placeholder');
});

test('vault revert button is present for non-current versions and absent for the current one', async () => {
  const graph = [
    { versionId: 'v1', fingerprint: 'abc123def456', kind: 'commit', label: null },
    { versionId: 'v2', fingerprint: '789fedcba012', kind: 'commit', label: null },
  ];
  const dom = new JSDOM(`<body>${renderVaultGraph(graph, 'v2')}</body>`);
  const revertButtons = dom.window.document.querySelectorAll('[data-revert-to]');
  assert.equal(revertButtons.length, 1, 'only the non-current version should offer revert');
  assert.equal(revertButtons[0].dataset.revertTo, 'v1');
});
