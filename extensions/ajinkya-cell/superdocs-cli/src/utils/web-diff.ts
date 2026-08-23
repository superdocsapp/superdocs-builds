import fs from 'fs';
import path from 'path';
import os from 'os';
import { exec } from 'child_process';
import * as diff from 'diff';
import chalk from 'chalk';
import { logger } from './logger.js';

export interface WebDiffOptions {
  documentName?: string;
  documentId?: string;
  prompt?: string;
  additions?: number;
  deletions?: number;
}

/**
 * Counts words in a string.
 */
export function countWords(text: string): number {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Determines whether a diff is too large for comfortable terminal inspection
 * based on word count or total changed lines.
 */
export function isTooLargeForTerminal(
  oldContent: string,
  newContent: string,
  wordThreshold = 350,
  lineThreshold = 50
): { tooLarge: boolean; totalWords: number; totalLines: number; reason?: string } {
  const wordsOld = countWords(oldContent);
  const wordsNew = countWords(newContent);
  const totalWords = Math.max(wordsOld, wordsNew);

  const linesOld = (oldContent || '').split('\n').length;
  const linesNew = (newContent || '').split('\n').length;
  const totalLines = Math.max(linesOld, linesNew);

  if (totalWords > wordThreshold) {
    return {
      tooLarge: true,
      totalWords,
      totalLines,
      reason: `Document contains ${totalWords} words (exceeds terminal limit of ${wordThreshold} words / ~2-3 pages)`
    };
  }

  if (totalLines > lineThreshold) {
    return {
      tooLarge: true,
      totalWords,
      totalLines,
      reason: `Document spans ${totalLines} lines (exceeds terminal viewport threshold of ${lineThreshold} lines)`
    };
  }

  return { tooLarge: false, totalWords, totalLines };
}

/**
 * Generates a self-contained HTML page with a side-by-side and unified visual diff viewer.
 */
export function generateHtmlDiffReport(
  oldContent: string,
  newContent: string,
  options: WebDiffOptions = {}
): string {
  const lineDiffs = diff.diffLines(oldContent || '', newContent || '');
  const docName = options.documentName || 'Document';
  const prompt = options.prompt || 'AI Edit';

  let additions = 0;
  let deletions = 0;
  let unchanged = 0;

  interface DiffRow {
    type: 'add' | 'del' | 'eq';
    oldLine?: number;
    newLine?: number;
    oldText?: string;
    newText?: string;
    text: string;
  }

  const rows: DiffRow[] = [];
  let oldLineNum = 1;
  let newLineNum = 1;

  for (const part of lineDiffs) {
    const rawLines = part.value.split('\n');
    if (rawLines.length > 0 && rawLines[rawLines.length - 1] === '') {
      rawLines.pop();
    }

    if (part.added) {
      additions += rawLines.length;
      for (const line of rawLines) {
        rows.push({
          type: 'add',
          newLine: newLineNum++,
          newText: line,
          text: line
        });
      }
    } else if (part.removed) {
      deletions += rawLines.length;
      for (const line of rawLines) {
        rows.push({
          type: 'del',
          oldLine: oldLineNum++,
          oldText: line,
          text: line
        });
      }
    } else {
      unchanged += rawLines.length;
      for (const line of rawLines) {
        rows.push({
          type: 'eq',
          oldLine: oldLineNum++,
          newLine: newLineNum++,
          oldText: line,
          newText: line,
          text: line
        });
      }
    }
  }

  const escapeHtml = (str: string = ''): string => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const rowsHtml = rows.map((r) => {
    if (r.type === 'add') {
      return `<tr class="diff-line line-added">
        <td class="gutter line-num"></td>
        <td class="gutter line-num">${r.newLine}</td>
        <td class="prefix">+</td>
        <td class="content">${escapeHtml(r.text)}</td>
      </tr>`;
    } else if (r.type === 'del') {
      return `<tr class="diff-line line-deleted">
        <td class="gutter line-num">${r.oldLine}</td>
        <td class="gutter line-num"></td>
        <td class="prefix">-</td>
        <td class="content">${escapeHtml(r.text)}</td>
      </tr>`;
    } else {
      return `<tr class="diff-line line-equal">
        <td class="gutter line-num">${r.oldLine}</td>
        <td class="gutter line-num">${r.newLine}</td>
        <td class="prefix"> </td>
        <td class="content">${escapeHtml(r.text)}</td>
      </tr>`;
    }
  }).join('\n');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SuperDocs Diff Review - ${escapeHtml(docName)}</title>
  <style>
    :root {
      --bg: #0d1117;
      --panel-bg: #161b22;
      --border: #30363d;
      --text: #e6edf3;
      --text-muted: #8b949e;
      --cyan: #58a6ff;
      --green-bg: rgba(46, 160, 67, 0.15);
      --green-border: #2ea043;
      --green-text: #3fb950;
      --red-bg: rgba(248, 81, 73, 0.15);
      --red-border: #f85149;
      --red-text: #f85149;
      --accent: #238636;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding-bottom: 60px;
    }

    header {
      background: var(--panel-bg);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 100;
      padding: 16px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand h1 {
      font-size: 1.15rem;
      font-weight: 600;
      color: var(--cyan);
      letter-spacing: -0.5px;
    }

    .brand .filename {
      font-size: 0.95rem;
      color: var(--text);
      background: rgba(255,255,255,0.06);
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }

    .stats {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .stat-badge {
      font-size: 0.85rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 20px;
      font-family: monospace;
    }
    .badge-add { background: var(--green-bg); color: var(--green-text); border: 1px solid var(--green-border); }
    .badge-del { background: var(--red-bg); color: var(--red-text); border: 1px solid var(--red-border); }
    .badge-info { background: rgba(88, 166, 255, 0.1); color: var(--cyan); border: 1px solid rgba(88, 166, 255, 0.3); }

    .banner {
      background: linear-gradient(90deg, #1f2937, #111827);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.9rem;
    }
    .banner-text span {
      color: var(--cyan);
      font-weight: 600;
    }

    .container {
      max-width: 1400px;
      margin: 24px auto;
      padding: 0 20px;
    }

    .prompt-card {
      background: var(--panel-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 20px;
    }
    .prompt-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 4px;
      font-weight: 600;
    }
    .prompt-content {
      font-size: 0.95rem;
      color: #fff;
    }

    .diff-table-container {
      background: var(--panel-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }

    table.diff-table {
      width: 100%;
      border-collapse: collapse;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 13px;
    }

    .diff-table td {
      padding: 2px 8px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .gutter {
      width: 45px;
      text-align: right;
      user-select: none;
      color: var(--text-muted);
      border-right: 1px solid var(--border);
      font-size: 11px;
      vertical-align: top;
      background: rgba(0,0,0,0.15);
    }

    .prefix {
      width: 20px;
      text-align: center;
      user-select: none;
      font-weight: bold;
    }

    .content {
      width: 100%;
    }

    .line-added {
      background-color: var(--green-bg);
    }
    .line-added .prefix {
      color: var(--green-text);
    }

    .line-deleted {
      background-color: var(--red-bg);
    }
    .line-deleted .prefix {
      color: var(--red-text);
    }

    .line-equal {
      color: #c9d1d9;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>SuperDocs AI</h1>
      <span class="filename">${escapeHtml(docName)}</span>
    </div>
    <div class="stats">
      <span class="stat-badge badge-add">+${additions} additions</span>
      <span class="stat-badge badge-del">-${deletions} deletions</span>
      <span class="stat-badge badge-info">${unchanged} unchanged lines</span>
    </div>
  </header>

  <div class="banner">
    <div class="banner-text">
      ✨ <span>Visual Diff Inspection</span> &mdash; Review your multi-page changes below, then return to your terminal to confirm approval.
    </div>
  </div>

  <div class="container">
    <div class="prompt-card">
      <div class="prompt-label">Edit Instruction Prompt</div>
      <div class="prompt-content">${escapeHtml(prompt)}</div>
    </div>

    <div class="diff-table-container">
      <table class="diff-table">
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>`;
}

/**
 * Creates a temporary HTML file on disk with the visual diff and launches it in the default browser.
 */
export function openWebDiff(
  oldContent: string,
  newContent: string,
  options: WebDiffOptions = {}
): string {
  const html = generateHtmlDiffReport(oldContent, newContent, options);
  const tempDir = os.tmpdir();
  const safeDocName = (options.documentName || 'document').replace(/[^a-zA-Z0-9_-]/g, '_');
  const tempFilePath = path.join(tempDir, `superdocs-diff-${safeDocName}-${Date.now()}.html`);

  fs.writeFileSync(tempFilePath, html, 'utf-8');

  // Cross-platform browser launcher
  const platform = process.platform;
  let command = '';
  if (platform === 'win32') {
    command = `start "" "${tempFilePath}"`;
  } else if (platform === 'darwin') {
    command = `open "${tempFilePath}"`;
  } else {
    command = `xdg-open "${tempFilePath}"`;
  }

  exec(command, (err) => {
    if (err) {
      logger.warn(`Could not launch browser automatically (${err.message}). View manually: ${tempFilePath}`);
    }
  });

  return tempFilePath;
}
