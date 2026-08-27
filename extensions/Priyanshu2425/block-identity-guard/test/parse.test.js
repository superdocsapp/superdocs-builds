import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseHtml, normaliseText, decodeEntities, createPositionLookup } from '../src/parse.js';

const ids = (html) => parseHtml(html).elements
  .map((node) => node.attr('data-chunk-id'))
  .filter(Boolean);

test('reads attributes in every quoting style editors emit', () => {
  const { elements } = parseHtml('<p data-chunk-id="a" class=lead data-part-type=\'header\'>x</p>');
  const [node] = elements;
  assert.equal(node.attr('data-chunk-id'), 'a');
  assert.equal(node.attr('class'), 'lead');
  assert.equal(node.attr('data-part-type'), 'header');
});

test('closes an unclosed paragraph when a block element opens', () => {
  const { elements } = parseHtml('<p data-chunk-id="a">one<p data-chunk-id="b">two');
  assert.deepEqual(ids('<p data-chunk-id="a">one<p data-chunk-id="b">two'), ['a', 'b']);
  assert.equal(elements[1].parent.tag, '#document');
  assert.equal(elements[0].text(), 'one');
});

test('closes list items and table cells the way a browser would', () => {
  const html = '<ul><li data-chunk-id="a">one<li data-chunk-id="b">two</ul>'
    + '<table><tr><td data-chunk-id="c">x<td data-chunk-id="d">y</table>';
  const { elements } = parseHtml(html);
  const cells = elements.filter((node) => node.tag === 'td');
  assert.deepEqual(cells.map((node) => node.text()), ['x', 'y']);
  assert.deepEqual(ids(html), ['a', 'b', 'c', 'd']);
});

test('treats void elements as childless', () => {
  const { elements } = parseHtml('<p data-chunk-id="a">line<br>break<img src="x.png"></p><p data-chunk-id="b">next</p>');
  assert.equal(elements[0].text(), 'line break');
  assert.equal(elements.filter((node) => node.tag === 'p').length, 2);
});

test('does not let script or style content become document text', () => {
  const { elements } = parseHtml('<p data-chunk-id="a">real</p><script>var x = "<p>fake</p>";</script>');
  const paragraphs = elements.filter((node) => node.tag === 'p');
  assert.equal(paragraphs.length, 1);
  assert.equal(paragraphs[0].text(), 'real');
});

test('skips comments and doctypes without swallowing what follows', () => {
  const html = '<!DOCTYPE html><!-- <p data-chunk-id="ghost">hidden</p> --><p data-chunk-id="a">real</p>';
  assert.deepEqual(ids(html), ['a']);
});

test('a stray angle bracket is text, not a tag', () => {
  const { elements } = parseHtml('<p data-chunk-id="a">5 < 6 and 7 > 6</p>');
  assert.equal(elements[0].text(), '5 < 6 and 7 > 6');
});

test('element boundaries are word boundaries', () => {
  const { elements } = parseHtml('<tr data-chunk-id="a"><td>Direct losses</td><td>Recoverable</td></tr>');
  assert.equal(elements[0].text(), 'Direct losses Recoverable');
});

test('entity and whitespace differences are not text differences', () => {
  assert.equal(normaliseText('a &amp; b'), 'a & b');
  assert.equal(normaliseText('clause&nbsp;3'), 'clause 3');
  assert.equal(normaliseText('  spaced\n   out  '), 'spaced out');
  assert.equal(decodeEntities('&#8212;&#x2014;'), '——');
  assert.equal(decodeEntities('&notanentity;'), '&notanentity;');
});

test('unterminated markup does not throw', () => {
  assert.doesNotThrow(() => parseHtml('<p data-chunk-id="a">text<div class="x'));
  assert.doesNotThrow(() => parseHtml('<!-- never closed'));
  assert.doesNotThrow(() => parseHtml('</p></div>'));
  assert.doesNotThrow(() => parseHtml(''));
});

test('position lookup maps offsets to lines', () => {
  const source = 'one\ntwo\nthree';
  const at = createPositionLookup(source);
  assert.deepEqual(at(0), { line: 1, column: 1 });
  assert.deepEqual(at(4), { line: 2, column: 1 });
  assert.deepEqual(at(9), { line: 3, column: 2 });
});
