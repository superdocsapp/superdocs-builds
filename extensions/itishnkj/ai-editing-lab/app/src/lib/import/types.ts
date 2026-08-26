export const DEFAULT_MAX_IMPORT_BYTES = 10 * 1024 * 1024;

export type ImportFormat = 'docx' | 'html' | 'text' | 'pdf';
export type DocumentSourceType = 'canonical' | 'imported';
export type ImportPersistence = 'persistent' | 'session-only';

export type ImportedDocument = {
  id: string;
  sourceType: 'imported';
  originalFileName: string;
  mimeType: string;
  format: ImportFormat;
  fileSize: number;
  html: string;
  plainText: string;
  wordCount: number;
  characterCount: number;
  importWarnings: string[];
  importDurationMs: number;
  importedAt: string;
  persistence: ImportPersistence;
};

export type ImportErrorCode =
  | 'empty_file'
  | 'file_too_large'
  | 'unsupported_format'
  | 'docm_not_supported'
  | 'parse_failed'
  | 'insufficient_pdf_text';

export class DocumentImportError extends Error {
  constructor(
    public readonly code: ImportErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'DocumentImportError';
  }
}

export type ImportOptions = {
  maxBytes?: number;
  persistentHtmlLimit?: number;
};

export type ImportableFile = Pick<File, 'name' | 'size' | 'type' | 'text' | 'arrayBuffer'>;