import { createCommand } from '@commander-js/extra-typings';
import { input } from '@inquirer/prompts';
import ora from 'ora';
import chalk from 'chalk';
import { superdocsClient } from '../client/superdocs.js';
import { getSession, saveSession, hasActiveDocument } from '../utils/state.js';
import { createDiff, formatDiffStats } from '../utils/diff.js';
import { logger } from '../utils/logger.js';

export const editCommand = createCommand('edit')
  .description('Edit active document using natural language prompts via SuperDocs streaming AI')
  .option('-p, --prompt <instruction>', 'Instruction prompt for SuperDocs AI')
  .action(async (options) => {
    const session = getSession();

    if (!session.activeDocumentId || !session.currentContent) {
      logger.error('No active document set in session.');
      logger.info(`Run ${chalk.bold.cyan('superdocs upload <path>')} first to ingest a document.`);
      process.exit(1);
    }

    let promptText = options.prompt;
    if (!promptText) {
      promptText = await input({
        message: 'What edits would you like SuperDocs AI to make?',
        validate: (val) => val.trim().length > 0 ? true : 'Please enter an instruction prompt.'
      });
    }

    const spinner = ora({
      text: chalk.cyan(`SuperDocs AI analyzing document (${session.documentName || 'Active'})...`),
      spinner: 'dots'
    }).start();

    try {
      const proposedVersion = await superdocsClient.streamEdit({
        documentId: session.activeDocumentId,
        prompt: promptText,
        currentContent: session.currentContent,
        currentHtml: session.currentHtml,
        documentName: session.documentName,
        onProgress: (chunk) => {
          if (chunk.reasoning) {
            spinner.text = chalk.dim(chunk.reasoning);
          }
        }
      });

      // Compute visual diff stats
      const diffResult = createDiff(
        session.currentContent,
        proposedVersion.content,
        session.documentName
      );

      proposedVersion.additions = diffResult.additions;
      proposedVersion.deletions = diffResult.deletions;

      saveSession({
        pendingVersion: proposedVersion
      });

      spinner.succeed(chalk.green(`AI edits generated successfully! [Version ID: ${proposedVersion.id}]`));

      console.log('');
      logger.box(
        'Proposed Edits Summary',
        `Prompt:        ${chalk.bold(promptText)}\n` +
        `Changes:       ${formatDiffStats(diffResult)}\n` +
        `Status:        ${chalk.yellow('Pending Approval')}`
      );

      console.log('');
      logger.info(`Run ${chalk.bold.cyan('superdocs approve')} to visually inspect the diff and commit changes.`);
      logger.info(`Or pass ${chalk.bold.cyan('superdocs approve --ci')} to generate a GitHub PR Markdown comment.`);
    } catch (err: any) {
      spinner.fail(chalk.red(`Edit failed: ${err.message}`));
      process.exit(1);
    }
  });
