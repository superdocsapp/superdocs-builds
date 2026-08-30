import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { writeFile } from 'node:fs/promises';
import { Document, Paragraph, Table, TableRow, TableCell, VerticalMergeType, Packer } from 'docx';
import { readDocx } from '@prism/core';
import { compareTableStructure, compareDocumentTables, describeTable } from '../src/table-compare.js';

async function buildDocxWithTable(tableRows) {
  const doc = new Document({ sections: [{ children: [new Table({ rows: tableRows })] }] });
  const buf = await Packer.toBuffer(doc);
  const p = path.join(os.tmpdir(), `prism-grid-${Date.now()}-${Math.random().toString(36).slice(2)}.docx`);
  await writeFile(p, buf);
  return readDocx(p);
}

function simpleRow(cellTexts) {
  return new TableRow({ children: cellTexts.map((t) => new TableCell({ children: [new Paragraph(t)] })) });
}

test('compareTableStructure: identical tables report no differences', async () => {
  const rows = [simpleRow(['A1', 'B1']), simpleRow(['A2', 'B2'])];
  const docA = await buildDocxWithTable(rows);
  const docB = await buildDocxWithTable([simpleRow(['A1', 'B1']), simpleRow(['A2', 'B2'])]);
  const result = compareTableStructure(docA.tables[0], docB.tables[0]);
  assert.equal(result.identical, true);
  assert.equal(result.differences.length, 0);
});

test('compareTableStructure: detects a changed cell value', async () => {
  const docA = await buildDocxWithTable([simpleRow(['A1', 'B1'])]);
  const docB = await buildDocxWithTable([simpleRow(['A1', 'CHANGED'])]);
  const result = compareTableStructure(docA.tables[0], docB.tables[0]);
  assert.equal(result.identical, false);
  assert.equal(result.differences[0].kind, 'cell-text');
  assert.equal(result.differences[0].col, 1);
});

test('compareTableStructure: detects a row-count difference and skips per-cell noise', async () => {
  const docA = await buildDocxWithTable([simpleRow(['A1'])]);
  const docB = await buildDocxWithTable([simpleRow(['A1']), simpleRow(['A2'])]);
  const result = compareTableStructure(docA.tables[0], docB.tables[0]);
  assert.equal(result.identical, false);
  assert.equal(result.differences.length, 1, 'row-count mismatch alone, not one entry per now-meaningless cell pairing');
  assert.equal(result.differences[0].kind, 'row-count');
});

test('readDocx correctly extracts a horizontal merge (gridSpan)', async () => {
  const doc = await buildDocxWithTable([
    new TableRow({ children: [new TableCell({ columnSpan: 2, children: [new Paragraph('Spans two columns')] })] }),
  ]);
  const cell = doc.tables[0].rows[0].cells[0];
  assert.equal(cell.gridSpan, 2);
  assert.equal(cell.text, 'Spans two columns');
});

test('readDocx correctly extracts a vertical merge (vMerge restart/continue)', async () => {
  const doc = await buildDocxWithTable([
    new TableRow({ children: [new TableCell({ verticalMerge: VerticalMergeType.RESTART, children: [new Paragraph('Merged down')] })] }),
    new TableRow({ children: [new TableCell({ verticalMerge: VerticalMergeType.CONTINUE, children: [new Paragraph('')] })] }),
  ]);
  assert.equal(doc.tables[0].rows[0].cells[0].vMerge, 'restart');
  assert.equal(doc.tables[0].rows[1].cells[0].vMerge, 'continue');
});

test('compareTableStructure catches a merge pattern that changed even when cell text did not', async () => {
  const docA = await buildDocxWithTable([
    new TableRow({ children: [new TableCell({ columnSpan: 2, children: [new Paragraph('Header')] })] }),
  ]);
  const docB = await buildDocxWithTable([
    new TableRow({ children: [new TableCell({ children: [new Paragraph('Header')] })] }), // same text, no longer spans
  ]);
  const result = compareTableStructure(docA.tables[0], docB.tables[0]);
  assert.equal(result.identical, false);
  assert.equal(result.differences[0].kind, 'merge-horizontal');
});

test('compareDocumentTables matches multiple tables positionally', async () => {
  const doc = new Document({
    sections: [{ children: [
      new Table({ rows: [simpleRow(['1'])] }),
      new Paragraph('spacer'),
      new Table({ rows: [simpleRow(['2'])] }),
    ] }],
  });
  const buf = await Packer.toBuffer(doc);
  const p1 = path.join(os.tmpdir(), `prism-grid-multi-${Date.now()}.docx`);
  await writeFile(p1, buf);
  const docA = await readDocx(p1);
  const docB = await readDocx(p1); // compare to itself
  const result = compareDocumentTables(docA, docB);
  assert.equal(result.identical, true);
  assert.equal(result.perTable.length, 2);
});

test('compareDocumentTables reports a table-count mismatch without crashing', async () => {
  const docA = await buildDocxWithTable([simpleRow(['A'])]);
  const docB = { tables: [] };
  const result = compareDocumentTables(docA, docB);
  assert.equal(result.identical, false);
  assert.match(result.reason, /table count differs/);
});

test('describeTable produces a human-readable summary', async () => {
  const doc = await buildDocxWithTable([simpleRow(['A', 'B']), simpleRow(['C', 'D'])]);
  const summary = describeTable(doc.tables[0]);
  assert.match(summary, /2 row\(s\) x 2 col\(s\)/);
});
