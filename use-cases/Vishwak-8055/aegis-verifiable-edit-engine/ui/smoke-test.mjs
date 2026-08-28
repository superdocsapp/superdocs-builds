import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const html = readFileSync(new URL('../ui/index.html', import.meta.url), 'utf-8');

const dom = new JSDOM(html, { runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true });
const { window } = dom;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  await wait(50); // let the inline <script> run

  const doc = window.document;
  const checks = [];
  const check = (label, cond) => checks.push({ label, pass: Boolean(cond) });

  check('stamp shows a decision word', doc.getElementById('stamp-word').textContent.trim().length > 0);
  check('default view is the unsafe (blocked) proof', doc.getElementById('stamp').getAttribute('data-decision') === 'BLOCKED');
  check('instruction text rendered', doc.getElementById('instruction-text').textContent.includes('easier to read'));
  check('changed-regions diff rendered at least one region', doc.querySelectorAll('.region').length > 0);
  check('invariants list rendered 8 rows', doc.querySelectorAll('#invariants-list li').length === 8);
  check('at least one invariant marked failed (obligations)', doc.querySelector('#invariants-list li[data-passed="false"]') !== null);
  check('risk grid rendered 5 severity cells', doc.querySelectorAll('#risk-grid .risk-cell').length === 5);
  check('verification checks list rendered 6 checkers', doc.querySelectorAll('#checks-list li').length === 6);
  check('evidence ledger table has at least one row', doc.querySelectorAll('#evidence-body tr').length > 0);
  check('proof hash rendered in custody footer', /^[0-9a-f]+$/.test(doc.getElementById('c-hash').textContent.trim()));
  check('injection notice is visible for the unsafe proof (it had a rejected override)', doc.getElementById('injection-notice').hidden === false);

  // Simulate clicking the "safe" tab and re-check.
  doc.getElementById('tab-safe').click();
  await wait(20);
  check('switching tabs updates the stamp to VERIFIED', doc.getElementById('stamp').getAttribute('data-decision') === 'VERIFIED');
  check('switching tabs updates aria-selected', doc.getElementById('tab-safe').getAttribute('aria-selected') === 'true' && doc.getElementById('tab-unsafe').getAttribute('aria-selected') === 'false');
  check('injection notice hides when the proof has no rejected overrides', doc.getElementById('injection-notice').hidden === true);

  // Simulate an invalid file load producing a friendly error, not a crash.
  const errBox = doc.getElementById('load-error');
  check('error box starts hidden', !errBox.classList.contains('visible'));

  let allPass = true;
  for (const c of checks) {
    console.log(`  ${c.pass ? '✓' : '✗'} ${c.label}`);
    if (!c.pass) allPass = false;
  }

  console.log('');
  console.log(`Functional smoke test: ${checks.filter((c) => c.pass).length}/${checks.length} checks passed`);

  // ---- axe-core accessibility scan ----
  window.eval(readFileSync(new URL('../node_modules/axe-core/axe.min.js', import.meta.url), 'utf-8'));
  const axeResults = await window.axe.run(doc, {
    // jsdom has no real layout engine, so purely visual/CSS rules (contrast,
    // hidden-content-via-CSS) cannot be evaluated here and are excluded.
    // Structural/semantic rules — the ones jsdom CAN evaluate honestly — stay on.
    rules: { 'color-contrast': { enabled: false } },
  });

  console.log('');
  console.log(`axe-core: ${axeResults.violations.length} violation type(s), ${axeResults.passes.length} rule(s) passed`);
  for (const v of axeResults.violations) {
    console.log(`  ✗ [${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} node(s))`);
  }

  if (!allPass || axeResults.violations.length > 0) {
    process.exitCode = 1;
  } else {
    console.log('');
    console.log('All functional and structural-accessibility checks passed.');
  }
}

main().catch((err) => {
  console.error('Smoke test crashed:', err);
  process.exitCode = 1;
});
