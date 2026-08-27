import JSZip from 'jszip';
import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';

import {
  AlignmentType, BorderStyle, Document, Footer, Header, HeadingLevel, ImageRun,
  PageBreak, PageNumber, Packer, Paragraph, ShadingType, Table, TableCell,
  TableRow, TextRun, WidthType,
} from 'docx';

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

function deterministicText(page, paragraph) {
  const tokens = [];
  for (let index = 0; index < 42; index += 1) {
    tokens.push(createHash('sha256').update(`sdx-${page}-${paragraph}-${index}`).digest('hex').slice(0, 14));
  }
  return `Page ${page} paragraph ${paragraph}: ${tokens.join(' ')}.`;
}

function pageChildren(page, edited) {
  const marker = `SDX_PAGE_${String(page).padStart(3, '0')}`;
  const children = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: `Resilience Proof Page ${page}`, bold: true, color: page % 2 ? '1F4E78' : '7030A0' })],
    }),
    new Paragraph({ children: [
      new TextRun({ text: marker, bold: true, color: 'C00000', highlight: 'yellow' }),
      new TextRun({ text: ' — deterministic unique page marker with styled content.', italics: true }),
    ] }),
  ];
  for (let paragraph = 1; paragraph <= 4; paragraph += 1) {
    children.push(new Paragraph({ children: [
      new TextRun({ text: deterministicText(page, paragraph), bold: paragraph === 1, italics: paragraph === 2, color: paragraph === 3 ? '008000' : '000000' }),
    ] }));
  }
  children.push(
    new Paragraph({ bullet: { level: 0 }, children: [new TextRun(`Page ${page} list item A`)] }),
    new Paragraph({ bullet: { level: 0 }, children: [new TextRun({ text: `Page ${page} list item B`, bold: true })] }),
  );
  if (page % 10 === 0) {
    children.push(new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      borders: {
        top: { style: BorderStyle.SINGLE, size: 1, color: '4472C4' }, bottom: { style: BorderStyle.SINGLE, size: 1, color: '4472C4' },
        left: { style: BorderStyle.SINGLE, size: 1, color: '4472C4' }, right: { style: BorderStyle.SINGLE, size: 1, color: '4472C4' },
        insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: 'D9E2F3' }, insideVertical: { style: BorderStyle.SINGLE, size: 1, color: 'D9E2F3' },
      },
      rows: [
        new TableRow({ children: [new TableCell({ shading: { type: ShadingType.CLEAR, fill: 'D9EAF7' }, children: [new Paragraph('Metric')] }), new TableCell({ children: [new Paragraph('Value')] })] }),
        new TableRow({ children: [new TableCell({ children: [new Paragraph(`Page ${page}`)] }), new TableCell({ children: [new Paragraph(marker)] })] }),
      ],
    }));
  }
  if (page === 1) children.push(new Paragraph({ children: [new ImageRun({ data: PNG, transformation: { width: 24, height: 24 }, type: 'png' })] }));
  if (page === 120) children.push(new Paragraph({ children: [new TextRun({
    text: edited ? 'SDX_TARGET_PAGE_120_EDITED' : 'SDX_TARGET_PAGE_120_ORIGINAL',
    bold: true, color: edited ? '008000' : 'C00000', underline: {},
  })] }));
  return children;
}

export async function generateStyledDocx(path, { edited = false } = {}) {
  const children = [];
  for (let page = 1; page <= 120; page += 1) {
    if (page > 1) children.push(new Paragraph({ children: [new PageBreak()] }));
    children.push(...pageChildren(page, edited));
  }
  const document = new Document({
    creator: 'sdx deterministic stress generator', title: 'sdx 120-page resilience proof',
    description: 'Generated test-only OOXML fixture with explicit page boundaries.',
    created: new Date('2026-08-06T00:00:00.000Z'), modified: new Date('2026-08-06T00:00:00.000Z'),
    styles: { paragraphStyles: [{ id: 'StressBody', name: 'Stress Body', basedOn: 'Normal', next: 'StressBody', run: { font: 'Aptos', size: 22 }, paragraph: { spacing: { after: 120 } } }] },
    sections: [{
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'sdx resilience proof', bold: true, color: '1F4E78' })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun('Page '), new TextRun({ children: [PageNumber.CURRENT] }), new TextRun(' of '), new TextRun({ children: [PageNumber.TOTAL_PAGES] })] })] }) },
      children,
    }],
  });
  const packed = await Packer.toBuffer(document);
  const zip = await JSZip.loadAsync(packed);
  const corePath = 'docProps/core.xml';
  const core = await zip.file(corePath).async('string');
  zip.file(corePath, core
    .replace(/<dcterms:created([^>]*)>[^<]+<\/dcterms:created>/, '<dcterms:created$1>2026-08-06T00:00:00.000Z</dcterms:created>')
    .replace(/<dcterms:modified([^>]*)>[^<]+<\/dcterms:modified>/, '<dcterms:modified$1>2026-08-06T00:00:00.000Z</dcterms:modified>'));
  const fixedDate = new Date('2026-08-06T00:00:00.000Z');
  for (const entry of Object.values(zip.files)) entry.date = fixedDate;
  const bytes = await zip.generateAsync({
    type: 'nodebuffer', compression: 'DEFLATE', compressionOptions: { level: 9 }, platform: 'UNIX',
  });
  await writeFile(path, bytes, { mode: 0o600 });
  return bytes;
}
