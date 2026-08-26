import { plainTextFromHtml, textToParagraphHtml } from './normalizeHtml';

export async function importText(file: Pick<File, 'text'>) {
  const text = await file.text();
  const html = textToParagraphHtml(text);
  return {
    html,
    plainText: plainTextFromHtml(html),
  };
}