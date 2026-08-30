import { test } from 'node:test';
import assert from 'node:assert/strict';
import { listTasks, getTask, implementedTasks } from '../src/task-registry.js';
import { Workflow } from '../src/workflow-engine.js';

test('registry lists all 30 capabilities with no silent gaps', () => {
  const all = listTasks();
  assert.equal(all.length, 30);
  for (const t of all) {
    assert.ok(t.status === 'implemented' || t.status === 'not_implemented', `${t.task_id} must have an explicit status`);
    if (t.status === 'not_implemented') {
      assert.ok(t.reason_not_implemented && t.reason_not_implemented.length > 10, `${t.task_id} must state why, not just that`);
    }
  }
  assert.equal(implementedTasks().length, 4);
  assert.deepEqual(implementedTasks().map((t) => t.task_id).sort(), ['prism-delta', 'prism-gate', 'prism-grid', 'prism-vault']);
});

test('getTask throws on an unknown id rather than returning undefined', () => {
  assert.throws(() => getTask('prism-does-not-exist'), /unknown task_id/);
});

test('Workflow enforces the transition graph — illegal jumps are refused', () => {
  const wf = new Workflow('t');
  assert.throws(() => wf.transition('VERIFIED'), /illegal transition/);
  wf.transition('INGESTING');
  wf.transition('UNDERSTANDING');
  assert.throws(() => wf.transition('EXPORTED'), /illegal transition/);
});

test('UNVERIFIED is a structural dead end toward EXPORTED, not just a convention', () => {
  const wf = new Workflow('t');
  wf.transition('INGESTING');
  wf.transition('UNDERSTANDING');
  wf.transition('PLANNING');
  wf.transition('PROPOSED');
  wf.transition('AWAITING_REVIEW');
  wf.transition('PARTIALLY_APPROVED');
  wf.transition('APPLYING');
  wf.transition('VERIFYING');
  wf.transition('UNVERIFIED');
  assert.throws(() => wf.transition('EXPORTED'), /illegal transition/, 'no transition graph path should allow UNVERIFIED -> EXPORTED');
});
