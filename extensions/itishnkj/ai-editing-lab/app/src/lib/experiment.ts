import type {
  EditResult,
  EditInputEngine,
} from '@workspace/api-client-react';
import type {
  BenchmarkCase,
  BenchmarkInvariant,
} from './constants';

export type FormattingCounts = {
  headings: number;
  bold: number;
  italic: number;
  links: number;
  lists: number;
  listItems: number;
  blockquotes: number;
  tables: number;
  chunkIds: number;
};

export type FormattingResult = {
  status: 'PASS' | 'PARTIAL' | 'FAIL' | 'N/A';
  detail: string;
  before: FormattingCounts;
  after: FormattingCounts;
  tablePreservation: TablePreservation;
};

export type TableStructure = {
  id: string;
  rows: number;
  headers: number;
  cells: number;
  chunkIds: string[];
};

export type TablePreservation = {
  preserved: boolean;
  before: TableStructure[];
  after: TableStructure[];
};

export type BenchmarkObservation = {
  id: string;
  benchmarkRunId: string;
  testCaseId: string;
  testLabel: string;
  runIndex: number;
  engine: EditInputEngine;
  startingDocumentHash: string;
  instruction: string;
  scope: 'selection' | 'document';
  success: boolean;
  latencyMs: number | null;
  reviewWaitMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  hostedUsage: string | null;
  retryCount: number | null;
  formatting: FormattingResult;
  error: string | null;
  result: EditResult | null;
};

export function stableDocumentHash(input: string): string {
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `fnv1a-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function count(html: string, pattern: RegExp): number {
  return html.match(pattern)?.length ?? 0;
}

function chunkIds(html: string): string[] {
  return [
    ...html.matchAll(
      /\bdata-chunk-id\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi,
    ),
  ]
    .map((match) => match[1] ?? match[2] ?? match[3])
    .filter((value): value is string => Boolean(value))
    .sort();
}

export function analyzeTableStructure(html: string): TableStructure[] {
  const tables: TableStructure[] = [];
  const tablePattern = /<table\b([^>]*)>([\s\S]*?)<\/table\s*>/gi;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = tablePattern.exec(html))) {
    const tableHtml = match[0];
    const tableId = chunkIds(match[1])[0] ?? `table-${index + 1}`;
    tables.push({
      id: tableId,
      rows: count(tableHtml, /<tr\b/gi),
      headers: count(tableHtml, /<th\b/gi),
      cells: count(tableHtml, /<td\b/gi),
      chunkIds: chunkIds(tableHtml),
    });
    index += 1;
  }
  return tables;
}

function tableStructureSummary(tables: TableStructure[]): string {
  if (!tables.length) return 'no tables';
  return tables
    .map(
      (table) =>
        `${table.id} (${table.rows} rows, ${table.headers} headers, ${table.cells} cells)`,
    )
    .join('; ');
}

export function analyzeFormatting(html: string): FormattingCounts {
  return {
    headings: count(html, /<h[1-3]\b/gi),
    bold: count(html, /<(?:strong|b)\b/gi),
    italic: count(html, /<(?:em|i)\b/gi),
    links: count(html, /<a\b/gi),
    lists: count(html, /<(?:ul|ol)\b/gi),
    listItems: count(html, /<li\b/gi),
    blockquotes: count(html, /<blockquote\b/gi),
    tables: count(html, /<table\b/gi),
    chunkIds: count(html, /\bdata-chunk-id=/gi),
  };
}

export function evaluateFormatting(
  beforeHtml: string,
  afterHtml: string | null,
  invariants: BenchmarkInvariant[],
): FormattingResult {
  const before = analyzeFormatting(beforeHtml);
  const after = analyzeFormatting(afterHtml ?? '');
  const beforeTables = analyzeTableStructure(beforeHtml);
  const afterTables = analyzeTableStructure(afterHtml ?? '');
  const tablePreservation = {
    preserved: JSON.stringify(beforeTables) === JSON.stringify(afterTables),
    before: beforeTables,
    after: afterTables,
  };
  if (!afterHtml) {
    return {
      status: 'N/A',
      detail: 'No complete candidate document was available for structural comparison.',
      before,
      after,
      tablePreservation,
    };
  }

  const checks = invariants.map((key) => ({
    key,
    passed:
      key === 'tables'
        ? tablePreservation.preserved
        : before[key] === after[key],
    before:
      key === 'tables' ? tableStructureSummary(beforeTables) : before[key],
    after: key === 'tables' ? tableStructureSummary(afterTables) : after[key],
  }));
  const passed = checks.filter((item) => item.passed).length;
  const failures = checks
    .filter((item) => !item.passed)
    .map((item) => `${item.key} ${item.before}→${item.after}`);

  return {
    status:
      passed === checks.length ? 'PASS' : passed === 0 ? 'FAIL' : 'PARTIAL',
    detail:
      failures.length === 0
        ? 'All declared structural invariants were preserved.'
        : `Changed: ${failures.join(', ')}.`,
    before,
    after,
    tablePreservation,
  };
}

export function getChunkOuterHtml(
  documentHtml: string,
  chunkId: string,
): { html: string; text: string } | null {
  const template = document.createElement('template');
  template.innerHTML = documentHtml;
  const escaped = CSS.escape(chunkId);
  const element = template.content.querySelector<HTMLElement>(
    `[data-chunk-id="${escaped}"]`,
  );
  if (!element) return null;
  return { html: element.outerHTML, text: element.textContent ?? '' };
}

export function candidateDocumentForResult(
  startingHtml: string,
  testCase: BenchmarkCase,
  result: EditResult,
): string | null {
  if (result.review) return null;
  if (result.candidateDocumentHtml) return result.candidateDocumentHtml;
  const proposed = result.proposedChanges[0]?.newHtml;
  if (!proposed || !testCase.targetChunkId) return null;
  const target = getChunkOuterHtml(startingHtml, testCase.targetChunkId);
  if (!target) return null;
  return startingHtml.replace(target.html, proposed);
}

export function downloadText(
  filename: string,
  content: string,
  type = 'text/plain',
) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}