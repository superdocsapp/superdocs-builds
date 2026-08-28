/**
 * Aegis never compares raw source strings or raw HTML/DOCX XML directly —
 * see docs/ARCHITECTURE.md "Why a canonical document model". Every adapter
 * (mock or real) is responsible for producing this shape; verifiers only
 * ever see `AegisDocument`.
 */

export interface LinkSpan {
  text: string;
  href: string;
}

export interface HeadingBlock {
  id: string;
  type: 'heading';
  level: 1 | 2 | 3 | 4;
  text: string;
}

export interface ParagraphBlock {
  id: string;
  type: 'paragraph';
  text: string;
  links: LinkSpan[];
}

export interface ListBlock {
  id: string;
  type: 'list';
  ordered: boolean;
  items: string[];
}

export interface TableBlock {
  id: string;
  type: 'table';
  rows: number;
  cols: number;
  cells: string[][];
}

export type Block = HeadingBlock | ParagraphBlock | ListBlock | TableBlock;

export interface AegisDocument {
  /** Positional ids, e.g. "paragraph:3", assigned at parse time. */
  blocks: Block[];
  /** Raw source this was parsed from, kept only for diagnostics — never used by verifiers for comparison. */
  sourceLength: number;
}

export function blockPlainText(block: Block): string {
  switch (block.type) {
    case 'heading':
      return block.text;
    case 'paragraph':
      return block.text;
    case 'list':
      return block.items.join('\n');
    case 'table':
      return block.cells.map((row) => row.join(' | ')).join('\n');
  }
}

/** 1-based ordinal among blocks of the same type, e.g. the 4th paragraph in the document. */
export function ordinalOfKind(doc: AegisDocument, blockId: string): number | null {
  const target = doc.blocks.find((b) => b.id === blockId);
  if (!target) return null;
  let count = 0;
  for (const block of doc.blocks) {
    if (block.type === target.type) {
      count++;
      if (block.id === blockId) return count;
    }
  }
  return null;
}

/** The Nth (1-based) block of a given type, or null if the document has fewer. */
export function nthOfKind<K extends Block['type']>(
  doc: AegisDocument,
  kind: K,
  n: number,
): Extract<Block, { type: K }> | null {
  let count = 0;
  for (const block of doc.blocks) {
    if (block.type === kind) {
      count++;
      if (count === n) return block as Extract<Block, { type: K }>;
    }
  }
  return null;
}
