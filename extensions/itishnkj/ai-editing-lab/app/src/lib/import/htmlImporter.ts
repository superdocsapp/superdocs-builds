import { normalizeImportedHtml } from './normalizeHtml';

export async function importHtml(file: Pick<File, 'text'>) {
  return normalizeImportedHtml(await file.text());
}