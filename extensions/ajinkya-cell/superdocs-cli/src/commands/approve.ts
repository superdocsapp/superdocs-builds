import { createCommand } from '@commander-js/extra-typings';
import { confirm } from '@inquirer/prompts';
import chalk from 'chalk';
import fs from 'fs';
import ora from 'ora';
import { superdocsClient } from '../client/superdocs.js';
import { getSession, saveSession } from '../utils/state.js';
import { createDiff, formatDiffStats } from '../utils/diff.js';
import { logger } from '../utils/logger.js';

export const approveCommand = createCommand('approve')
  .description('Review visual diff and approve/reject proposed document edits')
  .option('--ci', 'Output diff in GitHub PR-compatible Markdown format (non-interactive)')
  .option('--write-file', 'Automatically sync approved content back to original source file on disk')
  .action(async (options) => {
    const session = getSession();

    if (!session.activeDocumentId || !session.pendingVersion) {
      logger.warn('No pending edits found to approve.');
      logger.info(`Run ${chalk.bold.cyan('superdocs edit --prompt "<instruction>"')} to generate edits first.`);
      return;
    }

    const diffResult = createDiff(
      session.currentContent,
      session.pendingVersion.content,
      session.documentName || 'document.md'
    );

    // CI / GitHub PR comment output mode
    if (options.ci) {
      console.log(diffResult.markdownDiff);
      return;
    }

    // Terminal Visual Diff Display
    console.log('\n' + chalk.bold.underline('SuperDocs Proposed Diff Inspection:'));
    console.log(formatDiffStats(diffResult));
    console.log('─'.repeat(70));
    console.log(diffResult.unifiedView);
    console.log('─'.repeat(70) + '\n');

    const shouldApprove = await confirm({
      message: chalk.bold('Approve and lock these edits on SuperDocs server?'),
      default: true
    });

    if (shouldApprove) {
      const spinner = ora('Committing edits to SuperDocs server...').start();
      try {
        await superdocsClient.approveEdits(
          session.activeDocumentId,
          session.pendingVersion.id
        );

        const newContent = session.pendingVersion.content;
        const newHtml = session.pendingVersion.html || session.currentHtml;
        const newHistory = [
          ...session.history,
          {
            versionId: session.pendingVersion.id,
            prompt: session.pendingVersion.prompt,
            timestamp: session.pendingVersion.timestamp
          }
        ];

        saveSession({
          currentContent: newContent,
          currentHtml: newHtml,
          pendingVersion: undefined,
          history: newHistory
        });

        // Optionally write back to original file if requested
        if (options.writeFile && session.originalPath && fs.existsSync(session.originalPath)) {
          fs.writeFileSync(session.originalPath, newContent, 'utf-8');
          spinner.succeed(chalk.green(`Edits approved and synced to source file: ${session.originalPath}`));
        } else {
          spinner.succeed(chalk.green('✔ Edits officially approved and locked in SuperDocs session.'));
        }

        logger.info(`Next: Run ${chalk.bold.cyan('superdocs export --format <pdf|docx|md>')} or ${chalk.bold.cyan('superdocs edit')} for further refinements.`);
      } catch (err: any) {
        spinner.fail(chalk.red(`Failed to commit approval: ${err.message}`));
      }
    } else {
      saveSession({
        pendingVersion: undefined
      });
      logger.warn('✖ Proposed edits rejected. Document reverted to previous state.');
    }
  });
