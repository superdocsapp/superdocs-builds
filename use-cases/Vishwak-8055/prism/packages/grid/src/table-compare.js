// @ts-check
/**
 * Structural table comparison — deterministic, no heuristics. Per the
 * directive: "Use structural verification. Visual screenshots are
 * supplementary." This never renders anything; it compares the actual
 * row/cell/merge/text structure @prism/core's reader extracted.
 *
 * Scope, stated plainly: this compares STRUCTURE (does table B have the
 * same shape and cell text as table A), not layout/visual rendering
 * (column widths, borders, shading are not compared — @prism/core's
 * reader doesn't currently extract them either). "Structurally identical"
 * is a real, narrower claim than "visually identical," and this module
 * never claims the latter.
 */

/**
 * @typedef {{ gridSpan: number, vMerge: string, text: string }} GridCell
 * @typedef {{ rowIndex: number, cells: GridCell[] }} GridRow
 * @typedef {{ index: number, precedingParagraphCount: number, rowCount: number, columnCount: number, rows: GridRow[] }} GridTable
 */

/**
 * @param {GridTable} a
 * @param {GridTable} b
 */
export function compareTableStructure(a, b) {
  const differences = [];
  if (a.rowCount !== b.rowCount) {
    differences.push({ kind: 'row-count', detail: `${a.rowCount} vs ${b.rowCount} rows` });
    return { identical: false, differences }; // row-count mismatch makes per-cell comparison meaningless
  }
  for (let r = 0; r < a.rowCount; r++) {
    const rowA = a.rows[r];
    const rowB = b.rows[r];
    if (rowA.cells.length !== rowB.cells.length) {
      differences.push({ kind: 'cell-count', row: r, detail: `row ${r}: ${rowA.cells.length} vs ${rowB.cells.length} cells` });
      continue;
    }
    for (let c = 0; c < rowA.cells.length; c++) {
      const cellA = rowA.cells[c];
      const cellB = rowB.cells[c];
      if (cellA.gridSpan !== cellB.gridSpan) {
        differences.push({ kind: 'merge-horizontal', row: r, col: c, detail: `gridSpan ${cellA.gridSpan} vs ${cellB.gridSpan}` });
      }
      if (cellA.vMerge !== cellB.vMerge) {
        differences.push({ kind: 'merge-vertical', row: r, col: c, detail: `vMerge "${cellA.vMerge}" vs "${cellB.vMerge}"` });
      }
      if (cellA.text !== cellB.text) {
        differences.push({ kind: 'cell-text', row: r, col: c, detail: `"${cellA.text}" vs "${cellB.text}"` });
      }
    }
  }
  return { identical: differences.length === 0, differences };
}

/**
 * Compares every table between two documents, matched positionally by
 * index (the order they appear in the document). Does not attempt to
 * match a reordered/inserted table to its "closest" counterpart —
 * documented limitation, consistent with @prism/core's own paragraph
 * alignment being adjacency-based rather than similarity-scored.
 */
export function compareDocumentTables(docA, docB) {
  if (docA.tables.length !== docB.tables.length) {
    return {
      identical: false,
      reason: `table count differs: ${docA.tables.length} vs ${docB.tables.length}`,
      perTable: [],
    };
  }
  const perTable = docA.tables.map((t, i) => ({ index: i, ...compareTableStructure(t, docB.tables[i]) }));
  return { identical: perTable.every((t) => t.identical), perTable };
}

/** Human-readable one-line summary, for logs/UI. */
export function describeTable(table) {
  const merges = table.rows.flatMap((r) => r.cells).filter((c) => c.gridSpan > 1 || c.vMerge !== 'none').length;
  return `${table.rowCount} row(s) x ${table.columnCount} col(s), ${merges} merged cell(s)`;
}
