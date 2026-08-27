import { open } from 'node:fs/promises';

import { EXIT_CODES } from '../core/exit-codes.js';
import { SdxError } from './errors.js';
import type { ExportFormat } from './schemas.js';

const PDF_HEADER = Buffer.from('%PDF-');
const ZIP_LOCAL_HEADER = Buffer.from([0x50, 0x4b, 0x03, 0x04]);
const ZIP_EMPTY_HEADER = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
const ZIP_SPANNED_HEADER = Buffer.from([0x50, 0x4b, 0x07, 0x08]);
const ZIP_CENTRAL_HEADER = Buffer.from([0x50, 0x4b, 0x01, 0x02]);
const ZIP_END_HEADER = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
const MAX_ZIP_TAIL = 22 + 0xffff;
const MAX_CENTRAL_DIRECTORY = 16 * 1024 * 1024;

function invalidExport(format: ExportFormat, reason: string): SdxError {
  return new SdxError(
    'Downloaded ' + format.toUpperCase() + ' export failed structural verification: ' + reason,
    EXIT_CODES.exportWriteFailure,
  );
}

async function readAt(handle: Awaited<ReturnType<typeof open>>, position: number, length: number): Promise<Buffer> {
  const buffer = Buffer.alloc(length);
  let offset = 0;
  while (offset < length) {
    const result = await handle.read(buffer, offset, length - offset, position + offset);
    if (result.bytesRead === 0) break;
    offset += result.bytesRead;
  }
  return offset === length ? buffer : buffer.subarray(0, offset);
}

async function containsToken(handle: Awaited<ReturnType<typeof open>>, size: number, token: Buffer): Promise<boolean> {
  const chunkSize = 64 * 1024;
  let position = 0;
  let overlap = Buffer.alloc(0);
  while (position < size) {
    const chunk = await readAt(handle, position, Math.min(chunkSize, size - position));
    if (chunk.length === 0) break;
    const combined = Buffer.concat([overlap, chunk]);
    if (combined.includes(token)) return true;
    overlap = combined.subarray(Math.max(0, combined.length - token.length + 1));
    position += chunk.length;
  }
  return false;
}

async function verifyPdf(path: string): Promise<void> {
  const handle = await open(path, 'r');
  try {
    const information = await handle.stat();
    if (information.size < PDF_HEADER.length + 8) throw invalidExport('pdf', 'file is too small');
    const header = await readAt(handle, 0, PDF_HEADER.length);
    if (!header.equals(PDF_HEADER)) throw invalidExport('pdf', 'missing the %PDF header');
    const tailLength = Math.min(information.size, 64 * 1024);
    const tail = await readAt(handle, information.size - tailLength, tailLength);
    const text = tail.toString('latin1');
    if (!text.includes('%%EOF')) throw invalidExport('pdf', 'missing the %%EOF marker');
    if (!await containsToken(handle, information.size, Buffer.from('/Type /Page'))) throw invalidExport('pdf', 'contains no page object');
    if (!await containsToken(handle, information.size, Buffer.from('/Font'))) throw invalidExport('pdf', 'contains no font/style resource');
  } finally {
    await handle.close();
  }
}

async function verifyDocx(path: string): Promise<void> {
  const handle = await open(path, 'r');
  try {
    const information = await handle.stat();
    if (information.size < 4) throw invalidExport('docx', 'file is too small');
    const header = await readAt(handle, 0, 4);
    if (!header.equals(ZIP_LOCAL_HEADER) && !header.equals(ZIP_EMPTY_HEADER) && !header.equals(ZIP_SPANNED_HEADER)) {
      throw invalidExport('docx', 'missing the ZIP container header');
    }
    const tailLength = Math.min(information.size, MAX_ZIP_TAIL);
    const tail = await readAt(handle, information.size - tailLength, tailLength);
    const endOffset = tail.lastIndexOf(ZIP_END_HEADER);
    if (endOffset < 0 || endOffset + 22 > tail.length) throw invalidExport('docx', 'missing the ZIP end record');
    const entryCount = tail.readUInt16LE(endOffset + 10);
    const centralSize = tail.readUInt32LE(endOffset + 12);
    const centralOffset = tail.readUInt32LE(endOffset + 16);
    if (entryCount === 0 || centralSize === 0) throw invalidExport('docx', 'ZIP contains no entries');
    if (centralSize > MAX_CENTRAL_DIRECTORY || centralOffset + centralSize > information.size) {
      throw invalidExport('docx', 'ZIP central directory is invalid or too large');
    }
    const central = await readAt(handle, centralOffset, centralSize);
    const names = new Set<string>();
    let offset = 0;
    for (let index = 0; index < entryCount; index += 1) {
      if (offset + 46 > central.length || !central.subarray(offset, offset + 4).equals(ZIP_CENTRAL_HEADER)) {
        throw invalidExport('docx', 'ZIP central directory entry is malformed');
      }
      const nameLength = central.readUInt16LE(offset + 28);
      const extraLength = central.readUInt16LE(offset + 30);
      const commentLength = central.readUInt16LE(offset + 32);
      const end = offset + 46 + nameLength + extraLength + commentLength;
      if (end > central.length) throw invalidExport('docx', 'ZIP entry exceeds the central directory');
      names.add(central.subarray(offset + 46, offset + 46 + nameLength).toString('utf8'));
      offset = end;
    }
    for (const required of ['[Content_Types].xml', 'word/document.xml', 'word/styles.xml']) {
      if (!names.has(required)) throw invalidExport('docx', 'missing ' + required);
    }
  } finally {
    await handle.close();
  }
}

export async function verifyExportFile(path: string, format: ExportFormat): Promise<void> {
  if (format === 'pdf') await verifyPdf(path);
  else if (format === 'docx') await verifyDocx(path);
}
