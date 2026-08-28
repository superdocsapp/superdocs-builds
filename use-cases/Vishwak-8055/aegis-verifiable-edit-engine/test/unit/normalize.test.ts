import { describe, it, expect } from 'vitest';
import { parsePseudoMarkdown, alignBlocks } from '../../src/verification/normalize.js';

describe('parsePseudoMarkdown', () => {
  it('parses headings, paragraphs, lists, and tables into typed blocks', () => {
    const doc = parsePseudoMarkdown(`# Title

## Section

A paragraph with [a link](https://example.com/page).

- item one
- item two

1. first
2. second

| a | b |
| --- | --- |
| 1 | 2 |
`);
    expect(doc.blocks.map((b) => b.type)).toEqual(['heading', 'heading', 'paragraph', 'list', 'list', 'table']);
    const [h1, h2, p, ul, ol, table] = doc.blocks;
    expect(h1).toMatchObject({ level: 1, text: 'Title' });
    expect(h2).toMatchObject({ level: 2, text: 'Section' });
    expect(p).toMatchObject({ links: [{ text: 'a link', href: 'https://example.com/page' }] });
    expect(ul).toMatchObject({ ordered: false, items: ['item one', 'item two'] });
    expect(ol).toMatchObject({ ordered: true, items: ['first', 'second'] });
    expect(table).toMatchObject({ rows: 2, cols: 2, cells: [['a', 'b'], ['1', '2']] });
  });

  it('assigns positional, type-scoped ids', () => {
    const doc = parsePseudoMarkdown('Para one.\n\nPara two.\n\nPara three.');
    expect(doc.blocks.map((b) => b.id)).toEqual(['paragraph:1', 'paragraph:2', 'paragraph:3']);
  });

  it('pads ragged table rows to a rectangular shape', () => {
    const doc = parsePseudoMarkdown('| a | b | c |\n| --- | --- |\n| 1 | 2 |\n');
    const table = doc.blocks[0];
    expect(table).toMatchObject({ cols: 3, cells: [['a', 'b', 'c'], ['1', '2', '']] });
  });
});

describe('alignBlocks', () => {
  it('marks identical blocks as unchanged', () => {
    const before = parsePseudoMarkdown('First.\n\nSecond.\n\nThird.').blocks;
    const after = parsePseudoMarkdown('First.\n\nSecond.\n\nThird.').blocks;
    const alignment = alignBlocks(before, after);
    expect(alignment.every((a) => a.kind === 'unchanged')).toBe(true);
    expect(alignment).toHaveLength(3);
  });

  it('pairs a single edited paragraph as modified, not delete+insert', () => {
    const before = parsePseudoMarkdown('First.\n\nSecond.\n\nThird.').blocks;
    const after = parsePseudoMarkdown('First.\n\nSecond, edited.\n\nThird.').blocks;
    const alignment = alignBlocks(before, after);
    expect(alignment.map((a) => a.kind)).toEqual(['unchanged', 'modified', 'unchanged']);
  });

  it('detects a pure insertion', () => {
    const before = parsePseudoMarkdown('First.\n\nThird.').blocks;
    const after = parsePseudoMarkdown('First.\n\nSecond.\n\nThird.').blocks;
    const alignment = alignBlocks(before, after);
    expect(alignment.map((a) => a.kind)).toEqual(['unchanged', 'inserted', 'unchanged']);
  });

  it('detects a pure deletion', () => {
    const before = parsePseudoMarkdown('First.\n\nSecond.\n\nThird.').blocks;
    const after = parsePseudoMarkdown('First.\n\nThird.').blocks;
    const alignment = alignBlocks(before, after);
    expect(alignment.map((a) => a.kind)).toEqual(['unchanged', 'deleted', 'unchanged']);
  });

  it('treats a list becoming a paragraph as a type change (still a modified pair, not delete+insert)', () => {
    const before = parsePseudoMarkdown('- one\n- two').blocks;
    const after = parsePseudoMarkdown('One and two, as a sentence.').blocks;
    const alignment = alignBlocks(before, after);
    expect(alignment).toHaveLength(1);
    expect(alignment[0].kind).toBe('modified');
  });
});
