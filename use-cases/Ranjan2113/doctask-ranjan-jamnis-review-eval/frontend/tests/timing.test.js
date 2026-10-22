/**
 * Timer tests. `node --test`, no browser, no install.
 *
 * Decision time is a headline result of the study, so the clock's edge cases
 * are pinned here rather than trusted.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { DecisionClock } from '../src/timing.js';

/** A controllable clock so tests are exact rather than timing-dependent. */
function fakeClock(start = 1000) {
  let t = start;
  let wall = Date.parse('2026-08-14T10:00:00.000Z');
  return {
    now: () => t,
    iso: () => new Date(wall).toISOString(),
    advance: (ms) => {
      t += ms;
      wall += ms;
    },
  };
}

test('stop returns the elapsed interval and both timestamps', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(4200);
  const result = clock.stop('chg1');

  assert.equal(result.elapsedMs, 4200);
  assert.equal(result.shownAt, '2026-08-14T10:00:00.000Z');
  assert.equal(result.decidedAt, '2026-08-14T10:00:04.200Z');
});

test('a re-render must not reset a running clock', () => {
  // The failure this guards: start() called again on every render would make
  // every measured decision time collapse toward zero.
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(3000);
  clock.start('chg1');
  c.advance(1000);

  assert.equal(clock.stop('chg1').elapsedMs, 4000);
});

test('restart deliberately begins a fresh interval', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(5000);
  clock.restart('chg1');
  c.advance(800);

  assert.equal(clock.stop('chg1').elapsedMs, 800);
});

test('stopping an unstarted change returns null rather than inventing a time', () => {
  const clock = new DecisionClock(fakeClock());
  assert.equal(clock.stop('never_shown'), null);
});

test('stopping twice does not produce a second measurement', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(1500);

  assert.equal(clock.stop('chg1').elapsedMs, 1500);
  assert.equal(clock.stop('chg1'), null, 'a double-click must not log twice');
});

test('several changes are timed independently', () => {
  // The batch conditions render every change at once, so all their clocks run
  // concurrently and must not interfere.
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('a');
  c.advance(1000);
  clock.start('b');
  c.advance(2000);

  assert.equal(clock.stop('a').elapsedMs, 3000);
  assert.equal(clock.stop('b').elapsedMs, 2000);
});

test('elapsed reports progress without closing the interval', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(900);

  assert.equal(clock.elapsed('chg1'), 900);
  assert.ok(clock.isOpen('chg1'));
  assert.equal(clock.stop('chg1').elapsedMs, 900);
});

test('elapsed on an unknown change is zero, not NaN', () => {
  const clock = new DecisionClock(fakeClock());
  assert.equal(clock.elapsed('nope'), 0);
});

// -- engagement-based timing (the run-1 artefact, PROGRESS.md A18) ---------

test('batch rendering does not make later changes look slow', () => {
  // The exact failure from pilot run 1: seven changes render together, the
  // reviewer works through them, and render-to-click for the last one
  // included every earlier change's time.
  const c = fakeClock();
  const clock = new DecisionClock(c);
  const ids = ['a', 'b', 'c'];
  ids.forEach((id) => clock.start(id));

  clock.engage('a');
  c.advance(2000);
  const first = clock.stop('a');

  clock.engage('b');
  c.advance(3000);
  const second = clock.stop('b');

  clock.engage('c');
  c.advance(1000);
  const third = clock.stop('c');

  assert.equal(first.elapsedMs, 2000);
  assert.equal(second.elapsedMs, 3000, 'must not include time spent on a');
  assert.equal(third.elapsedMs, 1000, 'must not include time spent on a and b');

  // and the render-to-click measure still shows the cumulative view
  assert.equal(third.renderToDecisionMs, 6000);
});

test('engagement is recorded once, so deliberation is not truncated', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);
  clock.start('x');

  clock.engage('x');
  c.advance(4000);
  clock.engage('x'); // re-hover while thinking
  c.advance(2000);

  assert.equal(clock.stop('x').elapsedMs, 6000);
});

test('a decision with no engagement signal falls back to render time', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);
  clock.start('x');
  c.advance(1500);

  const result = clock.stop('x');
  assert.equal(result.elapsedMs, 1500);
  assert.equal(result.wasEngaged, false, 'the fallback must be visible in the data');
});

test('sequential conditions give identical engaged and render timings', () => {
  // The soundness check: where only one change is on screen, engagement and
  // render coincide and the fix changes nothing.
  const c = fakeClock();
  const clock = new DecisionClock(c);
  clock.start('only');
  clock.engage('only');
  c.advance(5000);

  const result = clock.stop('only');
  assert.equal(result.elapsedMs, result.renderToDecisionMs);
  assert.equal(result.wasEngaged, true);
});

test('engaging an unknown change does not throw', () => {
  const clock = new DecisionClock(fakeClock());
  assert.equal(clock.engage('nope'), null);
  assert.equal(clock.isEngaged('nope'), false);
});

test('elapsed reflects engagement once engaged', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);
  clock.start('x');
  c.advance(10000); // sat on screen unread
  clock.engage('x');
  c.advance(800);

  assert.equal(clock.elapsed('x'), 800);
});

test('a revisit after a decision is timed as a new interval', () => {
  const c = fakeClock();
  const clock = new DecisionClock(c);

  clock.start('chg1');
  c.advance(2000);
  const first = clock.stop('chg1');

  c.advance(10000);
  clock.start('chg1');
  c.advance(700);
  const second = clock.stop('chg1');

  assert.equal(first.elapsedMs, 2000);
  assert.equal(second.elapsedMs, 700);
  assert.notEqual(first.shownAt, second.shownAt);
});
