import { sanitizeImportedHtml } from './sanitizeHtml';

export function escapeText(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function plainTextFromHtml(html: string): string {
  if (typeof document === 'undefined') {
    return html
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  const template = document.createElement('template');
  template.innerHTML = html;
  return (template.content.textContent ?? '').replace(/\s+/g, ' ').trim();
}

export function textToParagraphHtml(text: string): string {
  const paragraphs = text
    .replace(/\r\n?/g, '\n')
    .split(/\n\s*\n/g)
    .map((paragraph) => paragraph.replace(/\n+/g, ' ').trim())
    .filter(Boolean);
  return paragraphs.map((paragraph) => `<p>${escapeText(paragraph)}</p>`).join('');
}

export function normalizeImportedHtml(input: string): {
  html: string;
  plainText: string;
} {
  const sanitized = sanitizeImportedHtml(input);
  const plainText = plainTextFromHtml(sanitized);
  return {
    html: sanitized || textToParagraphHtml(plainText),
    plainText,
  };
}