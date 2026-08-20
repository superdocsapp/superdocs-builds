import * as diff from 'diff';
import chalk from 'chalk';
import { DiffResult } from '../types.js';

export function createDiff(
  oldStr: string,
  newStr: string,
  fileName = 'document.md'
): DiffResult {
  const lineDiffs = diff.diffLines(oldStr || '', newStr || '');
  
  let additions = 0;
  let deletions = 0;
  let unchanged = 0;

  const terminalLines: string[] = [];
  const markdownLines: string[] = [];

  terminalLines.push(chalk.bold.cyan(`--- a/${fileName} (current)`));
  terminalLines.push(chalk.bold.cyan(`+++ b/${fileName} (proposed)`));
  
  markdownLines.push(`--- a/${fileName}`);
  markdownLines.push(`+++ b/${fileName}`);

  for (const part of lineDiffs) {
    const lines = part.value.split('\n');
    // Remove the trailing empty element if string ends in newline
    if (lines.length > 0 && lines[lines.length - 1] === '') {
      lines.pop();
    }

    if (part.added) {
      additions += lines.length;
      for (const line of lines) {
        terminalLines.push(chalk.green(`+ ${line}`));
        markdownLines.push(`+ ${line}`);
      }
    } else if (part.removed) {
      deletions += lines.length;
      for (const line of lines) {
        terminalLines.push(chalk.red(`- ${line}`));
        markdownLines.push(`- ${line}`);
      }
    } else {
      unchanged += lines.length;
      // Show up to 3 context lines for compact readability if long
      for (const line of lines) {
        terminalLines.push(chalk.dim(`  ${line}`));
        markdownLines.push(`  ${line}`);
      }
    }
  }

  const hasChanges = additions > 0 || deletions > 0;

  const markdownDiff = [
    '```diff',
    `# SuperDocs Proposed Diff: +${additions} / -${deletions}`,
    ...markdownLines,
    '```'
  ].join('\n');

  return {
    hasChanges,
    unifiedView: terminalLines.join('\n'),
    markdownDiff,
    additions,
    deletions,
    unchanged
  };
}

export function formatDiffStats(result: DiffResult): string {
  if (!result.hasChanges) {
    return chalk.dim('No changes detected.');
  }
  return `${chalk.green(`+${result.additions}`)} ${chalk.red(`-${result.deletions}`)} (unchanged: ${result.unchanged})`;
}
