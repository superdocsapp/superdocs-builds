import assert from 'node:assert/strict';
import test from 'node:test';

import { htmlToTerminalText, renderProposedChange, sanitizeTerminalText } from '../../dist/presentation/diff.js';

const change = {
  id: 'ch-1', operation: 'edit', chunkId: 'chunk-1', documentId: 'doc-1',
  oldContent: '<h2>Risks</h2><p>First paragraph.</p><ul><li>Alpha</li><li>Beta</li></ul>',
  newContent: '<h2>Risks</h2><p>Shorter paragraph.</p>', explanation: 'Clearer wording',
};

test('HTML diff text preserves headings, paragraphs, and list boundaries', () => {
  const text = htmlToTerminalText(change.oldContent);
  assert.match(text, /^Risks\nFirst paragraph\.\n\n• Alpha\n• Beta$/);
  const rendered = renderProposedChange(change, 1, 2, { color: false, maxCharacters: 4000 });
  assert.match(rendered, /Change 1 of 2/);
  assert.match(rendered, /Section: Risks/);
  assert.match(rendered, /Document ID: doc-1/);
  assert.match(rendered, /- First paragraph/);
  assert.match(rendered, /\+ Shorter paragraph/);
});

test('ANSI, OSC, and terminal controls are neutralized', () => {
  const hostile = '\u001b[31mred\u001b[0m\u001b]0;owned\u0007safe\u0000';
  assert.equal(sanitizeTerminalText(hostile), 'redsafe');
  const rendered = renderProposedChange({ ...change, explanation: hostile }, 1, 1, { color: false, maxCharacters: 4000 });
  assert.doesNotMatch(rendered, /\u001b|\u0007|owned/);
});

test('colour is opt-in and uncoloured output remains readable', () => {
  assert.doesNotMatch(renderProposedChange(change, 1, 1, { color: false, maxCharacters: 4000 }), /\u001b\[/);
  assert.match(renderProposedChange(change, 1, 1, { color: true, maxCharacters: 4000 }), /\u001b\[31m/);
});

test('large changes report exact hidden character and line counts', () => {
  const rendered = renderProposedChange({ ...change, newContent: '<p>1234567890\nline</p>' }, 1, 1, { color: false, maxCharacters: 5 });
  assert.match(rendered, /truncated: 10 hidden characters across 1 hidden lines/);
});
