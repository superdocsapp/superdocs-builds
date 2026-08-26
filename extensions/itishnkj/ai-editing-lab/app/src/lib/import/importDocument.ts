import { v4 as uuidv4 } from 'uuid';
import { importDocx } from './docxImporter';
import { importHtml } from './htmlImporter';
import { importPdf } from './pdfImporter';
import { importText } from './textImporter';
import {
  DEFAULT_MAX_IMPORT_BYTES,
  DocumentImportError,
  type ImportFormat,
  type ImportOptions,
  type ImportableFile,
  type ImportedDocument,
} from './types';

const DEFAULT_PERSISTENT_HTML_LIMIT = 250_000;

function formatForFile(file: Pick<File, 'name' | 'type'>): ImportFormat {
  const lowerName = file.name.toLowerCase();
  if (lowerName.endsWith('.docm')) {
    throw new DocumentImportError(
      'docm_not_supported',
      'Macro-enabled DOCM files are not supported. Export a macro-free DOCX first.',
    );
  }
  if (lowerName.endsWith('.docx')) return 'docx';
  if (lowerName.endsWith('.html') || lowerName.endsWith('.htm')) return 'html';
  if (lowerName.endsWith('.txt')) return 'text';
  if (lowerName.endsWith('.pdf')) return 'pdf';
  throw new DocumentImportError(
    'unsupported_format',
    'Choose a DOCX, HTML, TXT, or PDF file.',
  );
}

function words(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export async function importDocument(
  file: ImportableFile,
  options: ImportOptions = {},
): Promise<ImportedDocument> {
  if (!file.size) {
    throw new DocumentImportError('empty_file', 'Choose a non-empty document.');
  }
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_IMPORT_BYTES;
  if (file.size > maxBytes) {
    throw new DocumentImportError(
      'file_too_large',
      `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The current upload limit is ${(maxBytes / 1024 / 1024).toFixed(0)} MB.`,
    );
  }

  const startedAt = performance.now();
  const format = formatForFile(file);
  let parsed: { html: string; plainText: string; warnings: string[] };
  try {
    parsed =
      format === 'docx'
        ? await importDocx(file)
        : format === 'html'
          ? { ...(await importHtml(file)), warnings: [] }
          : format === 'text'
            ? { ...(await importText(file)), warnings: [] }
            : await importPdf(file);
  } catch (error) {
    if (error instanceof DocumentImportError) throw error;
    throw new DocumentImportError(
      'parse_failed',
      `This ${format.toUpperCase()} document could not be parsed for editing.`,
    );
  }

  if (!parsed.plainText.trim()) {
    throw new DocumentImportError(
      'parse_failed',
      'No editable text could be extracted from this document.',
    );
  }

  const persistence =
    parsed.html.length <= (options.persistentHtmlLimit ?? DEFAULT_PERSISTENT_HTML_LIMIT)
      ? 'persistent'
      : 'session-only';
  const warnings = [...parsed.warnings];
  if (persistence === 'session-only') {
    warnings.push(
      'This normalized document is too large for local persistence and will be available only for this browser session.',
    );
  }

  return {
    id: uuidv4(),
    sourceType: 'imported',
    originalFileName: file.name,
    mimeType: file.type || `application/${format}`,
    format,
    fileSize: file.size,
    html: parsed.html,
    plainText: parsed.plainText,
    wordCount: words(parsed.plainText),
    characterCount: parsed.plainText.length,
    importWarnings: warnings,
    importDurationMs: Math.round(performance.now() - startedAt),
    importedAt: new Date().toISOString(),
    persistence,
  };
}