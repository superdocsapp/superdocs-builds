import type { ProposedChange } from '../core/changes.js';

const ANSI_PATTERN = /(?:\u001B\][^\u0007]*(?:\u0007|\u001B\\))|(?:\u001B\[[0-?]*[ -/]*[@-~])|(?:\u009B[0-?]*[ -/]*[@-~])/gu;
const CONTROL_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/gu;

export function sanitizeTerminalText(value: string): string {
  return value.replace(ANSI_PATTERN, '').replace(CONTROL_PATTERN, '');
}
function decodeCodePoint(value: string, radix: number): string {
  const point = Number.parseInt(value, radix);
  return Number.isInteger(point) && point >= 0 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff)
    ? String.fromCodePoint(point)
    : '�';
}


function decodeEntities(value: string): string {
  return value
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, (_match, digits: string) => decodeCodePoint(digits, 10))
    .replace(/&#x([0-9a-f]+);/gi, (_match, digits: string) => decodeCodePoint(digits, 16));
}

export function htmlToTerminalText(value: string | null): string | null {
  if (value === null) return null;
  const withoutExecutable = value
    .replace(/<(script|style|template)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
    .replace(/<!--([\s\S]*?)-->/g, '');
  const structured = withoutExecutable
    .replace(/<\s*br\s*\/?\s*>/gi, '\n')
    .replace(/<\s*li\b[^>]*>/gi, '\n• ')
    .replace(/<\s*\/li\s*>/gi, '')
    .replace(/<\s*\/(?:p|div|ul|ol|blockquote|pre|table|tr)\s*>/gi, '\n')
    .replace(/<\s*h[1-6]\b[^>]*>/gi, '\n')
    .replace(/<\s*\/h[1-6]\s*>/gi, '\n')
    .replace(/<[^>]*>/g, '');
  return sanitizeTerminalText(decodeEntities(structured))
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function sectionFromChange(change: ProposedChange): string | null {
  for (const value of [change.newContent, change.oldContent]) {
    if (value === null) continue;
    const heading = /<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/i.exec(value)?.[1];
    if (heading) return htmlToTerminalText(heading);
  }
  return change.chunkId;
}

export interface DiffRenderOptions {
  readonly color: boolean;
  readonly maxCharacters: number;
}

function truncatedLines(value: string | null, limit: number): readonly string[] {
  const normalized = value === null || value.length === 0 ? '(none)' : value;
  if (normalized.length <= limit) return normalized.split('\n');
  const visible = normalized.slice(0, limit);
  const hidden = normalized.slice(limit);
  const hiddenLines = hidden.split('\n').length - 1;
  return [
    ...visible.split('\n'),
    `[truncated: ${hidden.length} hidden characters across ${hiddenLines} hidden lines; increase --diff-limit to view more]`,
  ];
}

const RED = '\u001b[31m';
const GREEN = '\u001b[32m';
const BOLD = '\u001b[1m';
const RESET = '\u001b[0m';

function styled(value: string, code: string, enabled: boolean): string {
  return enabled ? `${code}${value}${RESET}` : value;
}

function block(label: string, prefix: string, value: string | null, color: string, options: DiffRenderOptions): string[] {
  const terminal = htmlToTerminalText(value);
  return [
    `${label}:`,
    ...truncatedLines(terminal, options.maxCharacters).map((line) =>
      line.startsWith('[truncated:') ? line : styled(`${prefix}${line}`, color, options.color),
    ),
  ];
}

export function renderProposedChange(change: ProposedChange, index: number, total: number, options: DiffRenderOptions): string {
  const lines = [
    styled(`Change ${index} of ${total}`, BOLD, options.color),
    `Section: ${sectionFromChange(change) ?? '(not provided)'}`,
    `Change ID: ${sanitizeTerminalText(change.id)}`,
    `Operation: ${change.operation}`,
    `AI explanation: ${sanitizeTerminalText(change.explanation ?? '(none)')}`,
  ];
  if (change.documentId !== null) lines.push(`Document ID: ${sanitizeTerminalText(change.documentId)}`);
  lines.push(
    ...block('Old text', '- ', change.oldContent, RED, options),
    ...block('New text', '+ ', change.newContent, GREEN, options),
  );

  return lines.join('\n');
}
