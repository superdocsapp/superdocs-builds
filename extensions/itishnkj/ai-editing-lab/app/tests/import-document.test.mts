import assert from 'node:assert/strict';
import test from 'node:test';
import { importDocument } from '../src/lib/import/importDocument.ts';
import {
  DEFAULT_MAX_IMPORT_BYTES,
  DocumentImportError,
} from '../src/lib/import/types.ts';
import { sanitizeImportedHtml } from '../src/lib/import/sanitizeHtml.ts';
import {
  analyzeFormatting,
  analyzeTableStructure,
  evaluateFormatting,
} from '../src/lib/experiment.ts';

function fakeFile(
  name: string,
  content: string,
  type = 'text/plain',
) {
  const bytes = new TextEncoder().encode(content);
  return {
    name,
    size: bytes.byteLength,
    type,
    text: async () => content,
    arrayBuffer: async () => bytes.buffer,
  };
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function fixtureDocx(
  documentBody =
    '<w:p><w:r><w:t>Intro</w:t></w:r></w:p><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold note</w:t></w:r></w:p>',
): ArrayBuffer {
  const encoder = new TextEncoder();
  const files = [
    [
      '[Content_Types].xml',
      '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    ],
    [
      '_rels/.rels',
      '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    ],
    [
      'word/document.xml',
      `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${documentBody}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>`,
    ],
    [
      'word/_rels/document.xml.rels',
      '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>',
    ],
  ].map(([name, content]) => ({
    name: encoder.encode(name),
    content: encoder.encode(content),
  }));
  const localSizes = files.map((file) => 30 + file.name.length + file.content.length);
  const centralSize = files.reduce((sum, file) => sum + 46 + file.name.length, 0);
  const out = new Uint8Array(
    localSizes.reduce((sum, size) => sum + size, 0) + centralSize + 22,
  );
  const view = new DataView(out.buffer);
  let offset = 0;
  const offsets: number[] = [];
  const write16 = (at: number, value: number) => view.setUint16(at, value, true);
  const write32 = (at: number, value: number) => view.setUint32(at, value, true);
  for (const file of files) {
    offsets.push(offset);
    write32(offset, 0x04034b50);
    write16(offset + 4, 20);
    write16(offset + 8, 0);
    write16(offset + 10, 0);
    write32(offset + 14, crc32(file.content));
    write32(offset + 18, file.content.length);
    write32(offset + 22, file.content.length);
    write16(offset + 26, file.name.length);
    write16(offset + 28, 0);
    out.set(file.name, offset + 30);
    out.set(file.content, offset + 30 + file.name.length);
    offset += 30 + file.name.length + file.content.length;
  }
  const centralOffset = offset;
  files.forEach((file, index) => {
    write32(offset, 0x02014b50);
    write16(offset + 4, 20);
    write16(offset + 6, 20);
    write16(offset + 8, 0);
    write16(offset + 10, 0);
    write32(offset + 16, crc32(file.content));
    write32(offset + 20, file.content.length);
    write32(offset + 24, file.content.length);
    write16(offset + 28, file.name.length);
    write16(offset + 30, 0);
    write16(offset + 32, 0);
    write32(offset + 42, offsets[index]);
    out.set(file.name, offset + 46);
    offset += 46 + file.name.length;
  });
  write32(offset, 0x06054b50);
  write16(offset + 8, files.length);
  write16(offset + 10, files.length);
  write32(offset + 12, offset - centralOffset);
  write32(offset + 16, centralOffset);
  return out.buffer;
}

test('imports TXT into normalized paragraph HTML with safe metadata', async () => {
  const imported = await importDocument(
    fakeFile('notes.txt', 'First paragraph.\n\nSecond paragraph.'),
  );
  assert.equal(imported.format, 'text');
  assert.equal(imported.sourceType, 'imported');
  assert.match(imported.html, /<p>First paragraph\.<\/p>/);
  assert.equal(imported.wordCount, 4);
  assert.equal(imported.characterCount, 'First paragraph. Second paragraph.'.length);
  assert.equal(imported.persistence, 'persistent');
});

test('imports HTML through the sanitizer and never returns executable markup', async () => {
  const imported = await importDocument(
    fakeFile(
      'unsafe.html',
      '<h1 data-chunk-id="section_1" onclick="alert(1)">Title</h1><script>alert(1)</script><p><a data-chunk-id="link_1" href="javascript:alert(1)">Bad link</a></p>',
      'text/html',
    ),
  );
  assert.doesNotMatch(imported.html, /<script|onclick|javascript:/i);
  assert.match(imported.html, /data-chunk-id="section_1"/);
  assert.match(imported.html, /data-chunk-id="link_1"/);
  assert.doesNotMatch(sanitizeImportedHtml('<svg><script>alert(1)</script></svg>'), /<script|<svg/i);
});

test('keeps safe editable HTML tables and chunk metadata on cells', async () => {
  const imported = await importDocument(
    fakeFile(
      'table.html',
      '<table data-chunk-id="delivery_table" onclick="alert(1)"><thead><tr><th scope="col" data-chunk-id="header_status">Status</th><th data-chunk-id="header_owner">Owner</th></tr></thead><tbody><tr><td data-chunk-id="status_row_1" colspan="2" rowspan="1" style="color:red">On track</td></tr></tbody></table>',
      'text/html',
    ),
  );
  assert.match(imported.html, /<table data-chunk-id="delivery_table">/);
  assert.match(
    imported.html,
    /<th(?=[^>]*data-chunk-id="header_status")(?=[^>]*scope="col")[^>]*>Status<\/th>/,
  );
  assert.match(
    imported.html,
    /<td(?=[^>]*data-chunk-id="status_row_1")(?=[^>]*colspan="2")(?=[^>]*rowspan="1")[^>]*>On track<\/td>/,
  );
  assert.doesNotMatch(imported.html, /onclick|style=/i);
});

test('rejects DOCM, unsupported extensions, and oversized input before parsing', async () => {
  await assert.rejects(
    () => importDocument(fakeFile('macros.docm', 'not a docx')),
    (error: unknown) =>
      error instanceof DocumentImportError && error.code === 'docm_not_supported',
  );
  await assert.rejects(
    () => importDocument(fakeFile('notes.rtf', 'not supported')),
    (error: unknown) =>
      error instanceof DocumentImportError && error.code === 'unsupported_format',
  );
  const large = fakeFile('large.txt', 'too much');
  Object.assign(large, { size: DEFAULT_MAX_IMPORT_BYTES + 1 });
  await assert.rejects(
    () => importDocument(large),
    (error: unknown) =>
      error instanceof DocumentImportError && error.code === 'file_too_large',
  );
});

test('surfaces malformed DOCX conversion as a safe parsing error', async () => {
  await assert.rejects(
    () => importDocument(fakeFile('broken.docx', 'not a ZIP document')),
    (error: unknown) =>
      error instanceof DocumentImportError && error.code === 'parse_failed',
  );
});

test('converts common DOCX formatting to normalized editable HTML', async () => {
  const bytes = fixtureDocx();
  const imported = await importDocument({
    name: 'formatted.docx',
    size: bytes.byteLength,
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    text: async () => '',
    arrayBuffer: async () => bytes,
  });
  assert.equal(imported.format, 'docx');
  assert.match(imported.html, /<p>Intro<\/p>/);
  assert.match(imported.html, /<strong>Bold note<\/strong>/);
  assert.match(imported.plainText, /Intro Bold note/);
});

test('converts DOCX tables to safe editable table HTML', async () => {
  const tableBody =
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Milestone</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Migration</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Jordan</w:t></w:r></w:p></w:tc></w:tr></w:tbl>';
  const bytes = fixtureDocx(tableBody);
  const imported = await importDocument({
    name: 'table.docx',
    size: bytes.byteLength,
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    text: async () => '',
    arrayBuffer: async () => bytes,
  });
  assert.match(imported.html, /<table>/);
  assert.match(imported.html, /Milestone/);
  assert.match(imported.html, /Migration/);
});

test('reports table preservation as a formatting invariant', () => {
  const before =
    '<table data-chunk-id="table_1"><tr><th data-chunk-id="header_1">Status</th></tr><tr><td data-chunk-id="cell_1">Before</td></tr></table>';
  const preserved =
    '<table data-chunk-id="table_1"><tr><th data-chunk-id="header_1">Status</th></tr><tr><td data-chunk-id="cell_1">After</td></tr></table>';
  const changedStructure =
    '<table data-chunk-id="table_1"><tr><td data-chunk-id="cell_1">After</td></tr></table>';
  assert.equal(analyzeFormatting(before).tables, 1);
  assert.deepEqual(analyzeTableStructure(before), [
    {
      id: 'table_1',
      rows: 2,
      headers: 1,
      cells: 1,
      chunkIds: ['cell_1', 'header_1', 'table_1'],
    },
  ]);
  assert.equal(
    evaluateFormatting(before, preserved, ['tables']).status,
    'PASS',
  );
  assert.equal(
    evaluateFormatting(before, preserved, ['tables']).tablePreservation.preserved,
    true,
  );
  assert.equal(
    evaluateFormatting(before, changedStructure, ['tables']).status,
    'FAIL',
  );
});