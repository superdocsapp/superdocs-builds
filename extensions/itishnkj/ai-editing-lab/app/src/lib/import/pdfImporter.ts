import { normalizeImportedHtml, textToParagraphHtml } from './normalizeHtml';
import { DocumentImportError } from './types';

const PDF_LAYOUT_WARNING =
  'PDF import uses best-effort text extraction. Complex layout may not be preserved.';

export async function importPdf(file: Pick<File, 'arrayBuffer'>): Promise<{
  html: string;
  plainText: string;
  warnings: string[];
}> {
  const pdfjs = await import('pdfjs-dist');
  if (typeof window !== 'undefined') {
    const worker = await import('pdfjs-dist/build/pdf.worker.mjs?url');
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  }
  const loadingTask = pdfjs.getDocument({ data: await file.arrayBuffer() });
  const pdf = await loadingTask.promise;
  const pages: string[] = [];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const text = content.items
      .map((item) => ('str' in item ? item.str : ''))
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (text) pages.push(text);
  }
  const plainText = pages.join('\n\n').trim();
  if (plainText.length < 20) {
    throw new DocumentImportError(
      'insufficient_pdf_text',
      'This PDF does not contain enough extractable text for reliable editing.',
    );
  }
  const normalized = normalizeImportedHtml(textToParagraphHtml(plainText));
  return {
    ...normalized,
    warnings: [PDF_LAYOUT_WARNING],
  };
}