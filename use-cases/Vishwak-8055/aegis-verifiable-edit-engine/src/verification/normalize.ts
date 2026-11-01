import { contentFingerprint } from '../evidence/hash.js';
import type { AegisDocument, Block, LinkSpan } from '../types/document.js';

/**
 * Aegis's canonical document format is a small, constrained markdown dialect
 * (headings `#`.."####", `- `/`* `/`1. ` lists, `| a | b |` tables, blank-line
 * separated paragraphs). This is intentionally NOT trying to be "real"
 * SuperDoc DOCX-XML — see docs/ARCHITECTURE.md "Why a canonical document
 * model". A production adapter maps SuperDoc's real Document API content
 * (queried via `doc.query.match(...)`, see https://docs.superdoc.dev) into
 * this same `AegisDocument` shape; everything downstream of this file is
 * completely independent of which editor produced the source text.
 */

const LINK_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g;

export function parsePseudoMarkdown(raw: string): AegisDocument {
  const lines = raw.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  const counters: Record<Block['type'], number> = { heading: 0, paragraph: 0, list: 0, table: 0 };
  const nextId = (type: Block['type']): string => `${type}:${++counters[type]}`;

  let i = 0;
  let paragraphBuffer: string[] = [];

  const flushParagraph = () => {
    if (paragraphBuffer.length === 0) return;
    const text = paragraphBuffer.join(' ').trim();
    paragraphBuffer = [];
    if (!text) return;
    blocks.push({ id: nextId('paragraph'), type: 'paragraph', text, links: extractLinks(text) });
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed === '') {
      flushParagraph();
      i++;
      continue;
    }

    const headingMatch = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (headingMatch) {
      flushParagraph();
      blocks.push({
        id: nextId('heading'),
        type: 'heading',
        level: headingMatch[1].length as 1 | 2 | 3 | 4,
        text: headingMatch[2].trim(),
      });
      i++;
      continue;
    }

    if (isTableRow(trimmed)) {
      flushParagraph();
      const { block, linesConsumed } = parseTable(lines, i, nextId('table'));
      blocks.push(block);
      i += linesConsumed;
      continue;
    }

    const listMatch = /^(?:[-*]\s+|\d+\.\s+)/.exec(trimmed);
    if (listMatch) {
      flushParagraph();
      const ordered = /^\d+\.\s+/.test(trimmed);
      const { block, linesConsumed } = parseList(lines, i, ordered, nextId('list'));
      blocks.push(block);
      i += linesConsumed;
      continue;
    }

    paragraphBuffer.push(trimmed);
    i++;
  }
  flushParagraph();

  return { blocks, sourceLength: raw.length };
}

function extractLinks(text: string): LinkSpan[] {
  const links: LinkSpan[] = [];
  for (const match of text.matchAll(LINK_PATTERN)) {
    links.push({ text: match[1], href: match[2] });
  }
  return links;
}

function isTableRow(line: string): boolean {
  return line.startsWith('|') && line.endsWith('|') && line.length > 1;
}

function isTableSeparator(line: string): boolean {
  return /^\|[\s:-]+(\|[\s:-]+)*\|$/.test(line);
}

function splitRow(line: string): string[] {
  return line
    .slice(1, -1)
    .split('|')
    .map((cell) => cell.trim());
}

function parseTable(lines: string[], startIndex: number, id: string): { block: Block; linesConsumed: number } {
  const rows: string[][] = [];
  let i = startIndex;
  while (i < lines.length && isTableRow(lines[i].trim())) {
    const trimmed = lines[i].trim();
    if (!(rows.length === 1 && isTableSeparator(trimmed))) {
      rows.push(splitRow(trimmed));
    }
    i++;
  }
  const cols = rows.reduce((max, row) => Math.max(max, row.length), 0);
  const rectangular = rows.map((row) => {
    const padded = [...row];
    while (padded.length < cols) padded.push('');
    return padded;
  });
  return {
    block: { id, type: 'table', rows: rectangular.length, cols, cells: rectangular },
    linesConsumed: i - startIndex,
  };
}

function parseList(
  lines: string[],
  startIndex: number,
  ordered: boolean,
  id: string,
): { block: Block; linesConsumed: number } {
  const items: string[] = [];
  let i = startIndex;
  const pattern = ordered ? /^\d+\.\s+(.*)$/ : /^[-*]\s+(.*)$/;
  while (i < lines.length) {
    const trimmed = lines[i].trim();
    if (trimmed === '') break;
    const match = pattern.exec(trimmed);
    if (!match) break;
    items.push(match[1].trim());
    i++;
  }
  return { block: { id, type: 'list', ordered, items }, linesConsumed: i - startIndex };
}

// ---------------------------------------------------------------------------
// Alignment: which block in `after` corresponds to which block in `before`.
// ---------------------------------------------------------------------------

export type BlockAlignment =
  | { kind: 'unchanged'; beforeId: string; afterId: string }
  | { kind: 'modified'; beforeId: string; afterId: string }
  | { kind: 'inserted'; afterId: string }
  | { kind: 'deleted'; beforeId: string };

/**
 * Aligns two block sequences with an LCS diff over per-block fingerprints,
 * then greedily pairs up the leftover blocks inside each gap (by position)
 * as "modified" rather than treating every edit as a delete+insert. This is
 * the same idea as a text diff, one level up: it is what lets Aegis say
 * "paragraph 3 was modified" instead of "paragraph 3 vanished and a new,
 * unrelated paragraph appeared in its place".
 */
export function alignBlocks(before: Block[], after: Block[]): BlockAlignment[] {
  const beforeFp = before.map(fingerprintBlock);
  const afterFp = after.map(fingerprintBlock);
  const n = before.length;
  const m = after.length;

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        beforeFp[i] === afterFp[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const alignment: BlockAlignment[] = [];
  let beforeGap: number[] = [];
  let afterGap: number[] = [];

  const flushGap = () => {
    const pairs = Math.min(beforeGap.length, afterGap.length);
    for (let k = 0; k < pairs; k++) {
      alignment.push({ kind: 'modified', beforeId: before[beforeGap[k]].id, afterId: after[afterGap[k]].id });
    }
    for (let k = pairs; k < beforeGap.length; k++) {
      alignment.push({ kind: 'deleted', beforeId: before[beforeGap[k]].id });
    }
    for (let k = pairs; k < afterGap.length; k++) {
      alignment.push({ kind: 'inserted', afterId: after[afterGap[k]].id });
    }
    beforeGap = [];
    afterGap = [];
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (beforeFp[i] === afterFp[j]) {
      flushGap();
      alignment.push({ kind: 'unchanged', beforeId: before[i].id, afterId: after[j].id });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      beforeGap.push(i);
      i++;
    } else {
      afterGap.push(j);
      j++;
    }
  }
  while (i < n) beforeGap.push(i++);
  while (j < m) afterGap.push(j++);
  flushGap();

  return alignment;
}

function fingerprintBlock(block: Block): string {
  const norm = (s: string) => s.trim().replace(/\s+/g, ' ');
  switch (block.type) {
    case 'heading':
      return contentFingerprint(`heading|${block.level}|${norm(block.text)}`);
    case 'paragraph':
      return contentFingerprint(`paragraph|${norm(block.text)}`);
    case 'list':
      return contentFingerprint(`list|${block.ordered}|${block.items.map(norm).join('\u241E')}`);
    case 'table':
      return contentFingerprint(
        `table|${block.rows}x${block.cols}|${block.cells.map((r) => r.map(norm).join('\u241F')).join('\u241E')}`,
      );
  }
}

export function findBlock(doc: AegisDocument, id: string): Block | undefined {
  return doc.blocks.find((b) => b.id === id);
}
