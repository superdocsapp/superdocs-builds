import * as mammoth from 'mammoth';
import { normalizeImportedHtml } from './normalizeHtml';

export async function importDocx(file: Pick<File, 'arrayBuffer'>): Promise<{
  html: string;
  plainText: string;
  warnings: string[];
}> {
  const arrayBuffer = await file.arrayBuffer();
  const input =
    typeof window === 'undefined'
      ? { buffer: Buffer.from(arrayBuffer) }
      : { arrayBuffer };
  const result = await mammoth.convertToHtml(
    input,
    {
      includeDefaultStyleMap: true,
    },
  );
  const normalized = normalizeImportedHtml(result.value);
  const warnings = result.messages.map((message) => message.message);
  if (!warnings.length) {
    warnings.push(
      'DOCX import preserves common text formatting and editable tables. Advanced layout, comments, tracked changes, and embedded media are not imported.',
    );
  }
  return { ...normalized, warnings };
}