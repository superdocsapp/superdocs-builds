import { readFile } from 'node:fs/promises';
import { basename, dirname, extname, join } from 'node:path';
import { sha256 } from './hash.js';
import { atomicWrite } from './io.js';
import { ChangelogError } from './errors.js';

function pdfEscape(value) {
  return value.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)').replace(/[^\x20-\x7e]/g, '?');
}

export function createPdf(text, metadata = {}) {
  const lines = text.split(/\r?\n/).filter((line) => line && !line.startsWith('<!--'));
  const content = ['BT', '/F1 10 Tf', '72 760 Td', ...lines.flatMap((line, index) => [index ? '0 -14 Td' : '', `(${pdfEscape(line)}) Tj`]), 'ET'].filter(Boolean).join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(content, 'latin1')} >>\nstream\n${content}\nendstream`,
  ];
  const header = '%PDF-1.4\n%\xE2\xE3\xCF\xD3\n';
  let body = header;
  const offsets = [0];
  objects.forEach((object, index) => { offsets[index + 1] = Buffer.byteLength(body, 'latin1'); body += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(body, 'latin1');
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n `).join('\n')}\n`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R /Info << /Title (${pdfEscape(metadata.title || 'Changelog')}) /Producer (superdocs-changelog-maintainer) /Subject (origin: ${pdfEscape(metadata.origin || 'superdocs-changelog-maintainer')}) >> >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

function xmlEscape(value) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & (-(crc & 1)));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function zipStore(entries) {
  const locals = []; const central = []; let offset = 0;
  for (const [name, data] of entries) {
    const nameBytes = Buffer.from(name); const payload = Buffer.from(data); const crc = crc32(payload);
    const local = Buffer.alloc(30 + nameBytes.length); local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 6); local.writeUInt16LE(0, 8); local.writeUInt16LE(0, 10); local.writeUInt16LE(0, 12); local.writeUInt32LE(crc, 14); local.writeUInt32LE(payload.length, 18); local.writeUInt32LE(payload.length, 22); local.writeUInt16LE(nameBytes.length, 26); local.writeUInt16LE(0, 28); nameBytes.copy(local, 30);
    locals.push(local, payload);
    const record = Buffer.alloc(46 + nameBytes.length); record.writeUInt32LE(0x02014b50, 0); record.writeUInt16LE(20, 4); record.writeUInt16LE(20, 6); record.writeUInt16LE(0, 8); record.writeUInt16LE(0, 10); record.writeUInt16LE(0, 12); record.writeUInt16LE(0, 14); record.writeUInt32LE(crc, 16); record.writeUInt32LE(payload.length, 20); record.writeUInt32LE(payload.length, 24); record.writeUInt16LE(nameBytes.length, 28); record.writeUInt16LE(0, 30); record.writeUInt16LE(0, 32); record.writeUInt16LE(0, 34); record.writeUInt16LE(0, 36); record.writeUInt32LE(0, 38); record.writeUInt32LE(offset, 42); nameBytes.copy(record, 46); central.push(record); offset += local.length + payload.length;
  }
  const centralBuffer = Buffer.concat(central); const localBuffer = Buffer.concat(locals); const end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(0, 4); end.writeUInt16LE(0, 6); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(centralBuffer.length, 12); end.writeUInt32LE(localBuffer.length, 16); end.writeUInt16LE(0, 20);
  return Buffer.concat([localBuffer, centralBuffer, end]);
}

export function createDocx(text, metadata = {}) {
  const paragraphs = text.split(/\r?\n/).filter((line) => line && !line.startsWith('<!--')).map((line) => `<w:p><w:r><w:t xml:space="preserve">${xmlEscape(line)}</w:t></w:r></w:p>`).join('');
  const document = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${paragraphs}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`;
  const entries = [
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/></Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/></Relationships>'],
    ['word/document.xml', document],
    ['word/styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos"/></w:rPr></w:style></w:styles>'],
    ['docProps/custom.xml', `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property name="Origin" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2"><vt:lpwstr>superdocs-changelog-maintainer</vt:lpwstr></property><property name="ReleaseId" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="3"><vt:lpwstr>${xmlEscape(metadata.releaseId || '')}</vt:lpwstr></property><property name="RunId" fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="4"><vt:lpwstr>${xmlEscape(metadata.runId || '')}</vt:lpwstr></property></Properties>`],
  ];
  return zipStore(entries);
}

export function validatePdf(buffer) {
  if (!buffer.subarray(0, 5).equals(Buffer.from('%PDF-')) || !buffer.includes(Buffer.from('%%EOF')) || !buffer.includes(Buffer.from('/Type /Page')) || !buffer.includes(Buffer.from('/Font'))) throw new ChangelogError('PDF failed structural validation', 'EXPORT_INVALID', 22);
  return { format: 'pdf', bytes: buffer.length, sha256: sha256(buffer) };
}

function zipNames(buffer) {
  const names = []; let offset = buffer.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  if (offset < 0) throw new ChangelogError('DOCX missing ZIP end record', 'EXPORT_INVALID', 22);
  const count = buffer.readUInt16LE(offset + 10); const centralSize = buffer.readUInt32LE(offset + 12); const centralOffset = buffer.readUInt32LE(offset + 16); offset = centralOffset;
  for (let i = 0; i < count; i += 1) { if (buffer.readUInt32LE(offset) !== 0x02014b50) throw new ChangelogError('DOCX malformed central directory', 'EXPORT_INVALID', 22); const nameLength = buffer.readUInt16LE(offset + 28); const extraLength = buffer.readUInt16LE(offset + 30); const commentLength = buffer.readUInt16LE(offset + 32); names.push(buffer.subarray(offset + 46, offset + 46 + nameLength).toString()); offset += 46 + nameLength + extraLength + commentLength; }
  if (centralSize <= 0 || !['[Content_Types].xml', 'word/document.xml', 'word/styles.xml'].every((name) => names.includes(name))) throw new ChangelogError('DOCX failed OOXML structural validation', 'EXPORT_INVALID', 22);
  return names;
}

export function validateDocx(buffer) {
  if (!buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04]))) throw new ChangelogError('DOCX missing ZIP header', 'EXPORT_INVALID', 22);
  zipNames(buffer);
  return { format: 'docx', bytes: buffer.length, sha256: sha256(buffer) };
}

export async function exportArtifacts({ canonicalText, outputDir, stem, releaseId, runId, overwrite = false, failAt }) {
  const pdfPath = join(outputDir, `${stem}.pdf`); const docxPath = join(outputDir, `${stem}.docx`);
  const pdf = createPdf(canonicalText, { title: stem, origin: 'superdocs-changelog-maintainer', releaseId, runId }); const docx = createDocx(canonicalText, { releaseId, runId });
  const pdfCheck = validatePdf(pdf); const docxCheck = validateDocx(docx);
  if (failAt === 'export') throw new ChangelogError('deterministic interruption before export finalization', 'INJECTED_INTERRUPTION', 12);
  await atomicWrite(pdfPath, pdf, { mode: 0o600, overwrite });
  try { await atomicWrite(docxPath, docx, { mode: 0o600, overwrite }); } catch (error) { if (!overwrite) await import('node:fs/promises').then(({ rm }) => rm(pdfPath, { force: true })); throw error; }
  return { pdf: { path: pdfPath, ...pdfCheck }, docx: { path: docxPath, ...docxCheck } };
}
