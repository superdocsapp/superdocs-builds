const test = require('node:test');
const assert = require('node:assert/strict');
const { buildContentLossWarning } = require('./buildContentLossWarning');

test('returns no warning when output length is close to input length', () => {
  assert.equal(buildContentLossWarning(1000, 950), '');
});

test('returns no warning when output is even longer than input (template adds structure)', () => {
  assert.equal(buildContentLossWarning(1000, 1200), '');
});

test('warns when output has lost more than 30% of the original text', () => {
  const warning = buildContentLossWarning(1000, 600);
  assert.match(warning, /40% less text/);
});

test('stays silent (not wrong) when lengths are not usable numbers', () => {
  assert.equal(buildContentLossWarning(undefined, 500), '');
  assert.equal(buildContentLossWarning(0, 500), '');
  assert.equal(buildContentLossWarning('1000', 500), '');
});
