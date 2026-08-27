import assert from 'node:assert/strict';

import {
  Document,
  Footer,
  Header,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from 'docx';
import JSZip from 'jszip';

function pdfText(value) {
  return String(value).replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
}

export function createFixturePdf() {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
    '<< /Length 122 >>\nstream\nBT\n/F2 20 Tf\n72 720 Td\n(' + pdfText('Q3 Review') + ') Tj\n/F1 12 Tf\n0 -34 Td\n(' + pdfText('Synthetic fixture export') + ') Tj\n0 -20 Td\n(' + pdfText('Styled PDF content') + ') Tj\nET\nendstream',
  ];
  const chunks = [Buffer.from('%PDF-1.4\n%\xff\xff\xff\xff\n')];
  const offsets = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(Buffer.concat(chunks).length);
    chunks.push(Buffer.from(String(index + 1) + ' 0 obj\n' + objects[index] + '\nendobj\n'));
  }
  const xrefOffset = Buffer.concat(chunks).length;
  let xref = 'xref\n0 ' + String(objects.length + 1) + '\n0000000000 65535 f \n';
  for (let index = 1; index < offsets.length; index += 1) xref += String(offsets[index]).padStart(10, '0') + ' 00000 n \n';
  xref += 'trailer\n<< /Size ' + String(objects.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + String(xrefOffset) + '\n%%EOF\n';
  chunks.push(Buffer.from(xref));
  return Buffer.concat(chunks);
}

export async function createFixtureDocx() {
  const document = new Document({
    title: 'Q3 Review',
    creator: 'sdx offline fixture',
    sections: [{
      headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: 'SuperDocs fixture header', bold: true })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ children: [new TextRun({ text: 'Page 1', italics: true })] })] }) },
      children: [
        new Paragraph({ text: 'Q3 Review', heading: HeadingLevel.TITLE }),
        new Paragraph({ text: 'Styled DOCX fixture', heading: HeadingLevel.HEADING_1 }),
        new Paragraph({ children: [new TextRun({ text: 'Important ', bold: true }), new TextRun({ text: 'offline export content.' })] }),
        new Paragraph({ text: 'First list item', bullet: { level: 0 } }),
        new Paragraph({ text: 'Second list item', bullet: { level: 0 } }),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: [new TableRow({ children: [new TableCell({ children: [new Paragraph('Metric')] }), new TableCell({ children: [new Paragraph('Value')] })] }), new TableRow({ children: [new TableCell({ children: [new Paragraph('Status')] }), new TableCell({ children: [new Paragraph('Verified')] })] })],
        }),
      ],
    }],
  });
  return Packer.toBuffer(document);
}

export async function createFixtureExport(format) {
  if (format === 'pdf') return createFixturePdf();
  if (format === 'docx') return createFixtureDocx();
  if (format === 'html') return Buffer.from('<!doctype html><html><body><h1>Q3 Review</h1><p>Styled fixture export.</p></body></html>');
  if (format === 'markdown') return Buffer.from('# Q3 Review\n\nStyled fixture export.\n');
  return Buffer.from('Q3 Review\n\nStyled fixture export.\n');
}

export async function assertValidFixtureExport(bytes, format) {
  if (format === 'pdf') {
    const text = bytes.toString('latin1');
    assert.equal(text.startsWith('%PDF-'), true);
    assert.ok(text.includes('/Type /Page'));
    assert.ok(text.includes('/Font'));
    assert.match(text.slice(-65536), /%%EOF/);
    return;
  }
  if (format === 'docx') {
    const zip = await JSZip.loadAsync(bytes);
    for (const entry of ['[Content_Types].xml', 'word/document.xml', 'word/styles.xml']) assert.ok(zip.file(entry), 'missing DOCX entry ' + entry);
    return;
  }
  assert.ok(bytes.length > 0);
}
