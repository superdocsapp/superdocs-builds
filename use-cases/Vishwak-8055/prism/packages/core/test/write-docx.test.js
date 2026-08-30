import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { Document, Paragraph, TextRun, Table, TableRow, TableCell, Packer } from 'docx';
import { readDocx } from '../src/docx/read-docx.js';
import { writeDocx } from '../src/docx/write-docx.js';

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const v1Path = path.join(__dirname, '..', '..', 'delta', 'fixtures', 'contract-v1.docx');

async function pandocMarkdown(docxPath) {
  const { stdout } = await execFileAsync('pandoc', ['-t', 'markdown', docxPath]);
  return stdout;
}

test('writeDocx round-trips an unmodified paragraph set byte-for-byte in content', async () => {
  const original = await readDocx(v1Path);
  const outPath = path.join(os.tmpdir(), `prism-roundtrip-${Date.now()}.docx`);
  await writeDocx(original, original.paragraphs, outPath);

  const reread = await readDocx(outPath);
  assert.equal(reread.paragraphs.length, original.paragraphs.length);
  for (let i = 0; i < original.paragraphs.length; i++) {
    assert.equal(reread.paragraphs[i].text, original.paragraphs[i].text, `paragraph ${i} text`);
    assert.equal(reread.paragraphs[i].styleId, original.paragraphs[i].styleId, `paragraph ${i} styleId`);
  }

  // Independent check, not just my own reader confirming my own writer.
  const originalMd = await pandocMarkdown(v1Path);
  const rewrittenMd = await pandocMarkdown(outPath);
  assert.equal(rewrittenMd, originalMd, 'pandoc-rendered markdown must be identical after an unmodified round-trip');
});

test('writeDocx applies a real content change and independent tooling (pandoc) sees it', async () => {
  const original = await readDocx(v1Path);
  const outPath = path.join(os.tmpdir(), `prism-mutate-${Date.now()}.docx`);

  const mutated = original.paragraphs.map((p) =>
    p.text.includes('total contract price')
      ? { ...p, text: p.text.replace('$50,000', '$99,999'), runs: [{ text: p.text.replace('$50,000', '$99,999'), bold: false, italic: false, underline: false }] }
      : p,
  );
  await writeDocx(original, mutated, outPath);

  const md = await pandocMarkdown(outPath);
  assert.match(md, /\$99,999/);
  assert.doesNotMatch(md, /\$50,000/);
  // and everything else must still be there, untouched. Single words, not
  // multi-word phrases — pandoc line-wraps at ~80 columns, so a two-word
  // regex can straddle a wrap point where the space became a newline.
  assert.match(md, /Acme/);
  assert.match(md, /Confidentiality/);
});

test('writeDocx preserves bold formatting through a round-trip', async () => {
  const original = await readDocx(v1Path);
  const outPath = path.join(os.tmpdir(), `prism-bold-${Date.now()}.docx`);

  const mutated = original.paragraphs.map((p) =>
    p.text.includes('All notices')
      ? { ...p, runs: p.runs.map((r) => ({ ...r, bold: true })) }
      : p,
  );
  await writeDocx(original, mutated, outPath);

  const reread = await readDocx(outPath);
  const notices = reread.paragraphs.find((p) => p.text.includes('All notices'));
  assert.equal(notices.runs[0].bold, true);

  const md = await pandocMarkdown(outPath);
  assert.match(md, /\*\*All notices/, 'pandoc should render the now-bold paragraph with ** markers');
});

test('writeDocx preserves a table verbatim when paragraph count is unchanged, independently confirmed via pandoc', async () => {
  const doc = new Document({
    sections: [
      {
        children: [
          new Paragraph({ children: [new TextRun('Before the table.')] }),
          new Table({
            rows: [
              new TableRow({
                children: [
                  new TableCell({ children: [new Paragraph('A1')] }),
                  new TableCell({ children: [new Paragraph('B1')] }),
                ],
              }),
              new TableRow({
                children: [
                  new TableCell({ children: [new Paragraph('A2')] }),
                  new TableCell({ children: [new Paragraph('B2')] }),
                ],
              }),
            ],
          }),
          new Paragraph({ children: [new TextRun('After the table.')] }),
        ],
      },
    ],
  });
  const buf = await Packer.toBuffer(doc);
  const tablePath = path.join(os.tmpdir(), `prism-table-verbatim-${Date.now()}.docx`);
  await import('node:fs/promises').then((fs) => fs.writeFile(tablePath, buf));

  const original = await readDocx(tablePath);
  assert.equal(original.tables.length, 1);
  assert.equal(original.tables[0].rowCount, 2);
  assert.equal(original.tables[0].precedingParagraphCount, 1, 'table comes after exactly 1 paragraph');

  // Mutate only the "Before"/"After" paragraph text — same count, table untouched.
  const mutated = original.paragraphs.map((p) => {
    const newText = p.text.replace('Before', 'BEFORE').replace('After', 'AFTER');
    return { ...p, text: newText, runs: [{ text: newText, bold: false, italic: false, underline: false }] };
  });
  const outPath = path.join(os.tmpdir(), `prism-table-verbatim-out-${Date.now()}.docx`);
  await writeDocx(original, mutated, outPath);

  const reread = await readDocx(outPath);
  assert.equal(reread.tables.length, 1, 'table must survive the write');
  assert.equal(reread.tables[0].rowCount, 2);
  assert.equal(reread.tables[0].rows[0].cells[0].text, 'A1');
  assert.equal(reread.tables[0].rows[1].cells[1].text, 'B2');
  assert.equal(reread.paragraphs.find((p) => p.text.includes('BEFORE')) !== undefined, true);

  const md = await pandocMarkdown(outPath);
  assert.match(md, /A1/);
  assert.match(md, /B2/);
  assert.match(md, /BEFORE the table/);
  assert.match(md, /AFTER the table/);
});

test('writeDocx correctly anchors multiple tables at different positions', async () => {
  const doc = new Document({
    sections: [
      {
        children: [
          new Paragraph({ children: [new TextRun('Intro.')] }),
          new Table({ rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('T1')] })] })] }),
          new Paragraph({ children: [new TextRun('Middle.')] }),
          new Table({ rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('T2')] })] })] }),
          new Paragraph({ children: [new TextRun('End.')] }),
        ],
      },
    ],
  });
  const buf = await Packer.toBuffer(doc);
  const p = path.join(os.tmpdir(), `prism-multi-table-${Date.now()}.docx`);
  await import('node:fs/promises').then((fs) => fs.writeFile(p, buf));

  const original = await readDocx(p);
  assert.equal(original.tables.length, 2);
  assert.equal(original.tables[0].precedingParagraphCount, 1);
  assert.equal(original.tables[1].precedingParagraphCount, 2);

  const outPath = path.join(os.tmpdir(), `prism-multi-table-out-${Date.now()}.docx`);
  await writeDocx(original, original.paragraphs, outPath); // unmodified round-trip

  const md = await pandocMarkdown(outPath);
  const introIdx = md.indexOf('Intro');
  const t1Idx = md.indexOf('T1');
  const middleIdx = md.indexOf('Middle');
  const t2Idx = md.indexOf('T2');
  const endIdx = md.indexOf('End');
  assert.ok(introIdx < t1Idx && t1Idx < middleIdx && middleIdx < t2Idx && t2Idx < endIdx, 'document order must be preserved: Intro, T1, Middle, T2, End');
});

test('writeDocx refuses only the genuinely ambiguous case: tables present AND paragraph count changed', async () => {
  const doc = new Document({
    sections: [
      {
        children: [
          new Paragraph({ children: [new TextRun('Only paragraph.')] }),
          new Table({ rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('X')] })] })] }),
        ],
      },
    ],
  });
  const buf = await Packer.toBuffer(doc);
  const p = path.join(os.tmpdir(), `prism-table-refuse-${Date.now()}.docx`);
  await import('node:fs/promises').then((fs) => fs.writeFile(p, buf));

  const original = await readDocx(p);
  const withExtraParagraph = [...original.paragraphs, { text: 'New paragraph.', styleId: null, runs: [{ text: 'New paragraph.', bold: false, italic: false, underline: false }] }];

  await assert.rejects(
    () => writeDocx(original, withExtraParagraph, path.join(os.tmpdir(), 'prism-table-refuse-out.docx')),
    /paragraph count changed/,
    'must refuse with the specific new reason, not the old blanket one',
  );
});
