import { PDFParse } from 'pdf-parse';
import mammoth from 'mammoth';

export interface ParseDocumentResult {
  textContent: string;
  fileType: 'pdf' | 'docx' | 'txt' | 'doc';
  filename: string;
}

/**
 * Parses uploaded document buffer based on file extension and MIME type.
 * Supports PDF, DOCX, DOC (text fallback), and TXT.
 * Throws explicit error messages for unsupported file types, empty files, or corrupted data.
 */
export async function parseUploadedDocument(
  fileBuffer: Buffer,
  filename: string,
  mimetype?: string
): Promise<ParseDocumentResult> {
  if (!fileBuffer || fileBuffer.length === 0) {
    throw new Error('Uploaded file is empty (0 bytes). Please upload a valid document.');
  }

  const cleanFilename = filename.toLowerCase().trim();
  const mime = (mimetype || '').toLowerCase().trim();

  // Determine file type
  let detectedType: 'pdf' | 'docx' | 'doc' | 'txt' | null = null;

  if (cleanFilename.endsWith('.pdf') || mime.includes('pdf')) {
    detectedType = 'pdf';
  } else if (cleanFilename.endsWith('.docx') || mime.includes('officedocument.wordprocessingml')) {
    detectedType = 'docx';
  } else if (cleanFilename.endsWith('.doc') || mime.includes('msword')) {
    detectedType = 'doc';
  } else if (cleanFilename.endsWith('.txt') || mime.includes('text/plain') || mime.includes('text/')) {
    detectedType = 'txt';
  }

  if (!detectedType) {
    throw new Error(
      `Unsupported file type for "${filename}". Supported formats are PDF (.pdf), Word (.docx), and Plain Text (.txt).`
    );
  }

  let extractedText = '';

  try {
    if (detectedType === 'pdf') {
      // pdf-parse v2.x changed its API from v1.x: it's no longer a callable
      // function (`pdfParse(buffer)`). It now exports a class, PDFParse,
      // constructed with { data: <Buffer|Uint8Array> } and used via async
      // methods (getText(), getInfo(), etc.). Verified directly against the
      // installed v2.4.5 package -- this is the confirmed real shape, not a
      // guess: new PDFParse({data}).getText() -> { text, pages, total }.
      const parser = new PDFParse({ data: fileBuffer });
      try {
        const pdfResult = await parser.getText();
        extractedText = (pdfResult.text || '').trim();
      } finally {
        await parser.destroy();
      }
      if (!extractedText) {
        throw new Error('PDF file contains no readable text or is password protected.');
      }
    } else if (detectedType === 'docx') {
      // DOCX Parsing with mammoth
      const result = await mammoth.extractRawText({ buffer: fileBuffer });
      extractedText = (result.value || '').trim();
      if (!extractedText) {
        throw new Error('DOCX file contains no readable text.');
      }
    } else if (detectedType === 'doc') {
      // DOC text extraction attempt
      const result = await mammoth.extractRawText({ buffer: fileBuffer }).catch(() => null);
      extractedText = result ? (result.value || '').trim() : fileBuffer.toString('utf-8').trim();
      // Remove unprintable control characters if binary fallback was used
      extractedText = extractedText.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]/g, ' ').trim();
      if (!extractedText || extractedText.length < 10) {
        throw new Error('Legacy .doc file could not be parsed into readable text. Please convert to .docx or .pdf.');
      }
    } else {
      // TXT parsing
      extractedText = fileBuffer.toString('utf-8').trim();
      if (!extractedText) {
        throw new Error('Text file is empty.');
      }
    }
  } catch (err: any) {
    if (
      err.message.includes('Unsupported file type') ||
      err.message.includes('contains no readable text') ||
      err.message.includes('could not be parsed') ||
      err.message.includes('is empty')
    ) {
      throw err;
    }
    throw new Error(`Failed to parse ${detectedType.toUpperCase()} file "${filename}": ${err.message || 'Corrupted or unreadable format'}`);
  }

  if (!extractedText || extractedText.trim().length === 0) {
    throw new Error(`Extracted document content is empty for "${filename}".`);
  }

  return {
    textContent: extractedText,
    fileType: detectedType,
    filename
  };
}
