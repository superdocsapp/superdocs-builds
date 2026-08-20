import { createCommand } from '@commander-js/extra-typings';
import { input, confirm, select } from '@inquirer/prompts';
import chalk from 'chalk';
import ora from 'ora';
import fs from 'fs';
import { superdocsClient } from '../client/superdocs.js';
import { getSession, saveSession, getConfig } from '../utils/state.js';
import { createDiff, formatDiffStats } from '../utils/diff.js';
import { logger } from '../utils/logger.js';

export const chatCommand = createCommand('chat')
  .description('Interactive REPL chat session for continuous document editing and refinement')
  .action(async () => {
    logger.banner();
    const session = getSession();

    if (!session.activeDocumentId || !session.currentContent) {
      logger.error('No active document set.');
      logger.info(`Run ${chalk.bold.cyan('superdocs upload <file>')} before launching chat mode.`);
      return;
    }

    console.log(chalk.bold.cyan(`💬 Interactive SuperDocs Chat Mode`));
    console.log(chalk.dim(`Active Document: ${chalk.white(session.documentName || session.activeDocumentId)}`));
    console.log(chalk.dim(`Type your editing instructions or commands (${chalk.yellow('/diff')}, ${chalk.yellow('/approve')}, ${chalk.yellow('/export')}, ${chalk.yellow('/exit')})\n`));

    let active = true;

    while (active) {
      const currentSession = getSession();
      const promptInput = await input({
        message: chalk.magenta('superdocs>'),
        validate: (val) => val.trim().length > 0 ? true : 'Please enter an instruction or command.'
      });

      const cleanInput = promptInput.trim();

      // Command checks
      if (['exit', 'quit', '/exit', '/quit'].includes(cleanInput.toLowerCase())) {
        logger.info('Exiting interactive chat session.');
        active = false;
        break;
      }

      if (cleanInput === '/status') {
        logger.box(
          'Chat Session State',
          `Document:      ${currentSession.documentName || currentSession.activeDocumentId}\n` +
          `Length:        ${currentSession.currentContent.length} chars\n` +
          `History Edits: ${currentSession.history.length}\n` +
          `Pending Edit:  ${currentSession.pendingVersion ? chalk.yellow('Yes (run /approve)') : chalk.green('None')}`
        );
        continue;
      }

      if (cleanInput === '/diff') {
        if (!currentSession.pendingVersion) {
          logger.info('No pending version to compare.');
        } else {
          const diffResult = createDiff(
            currentSession.currentContent,
            currentSession.pendingVersion.content,
            currentSession.documentName
          );
          console.log('\n' + diffResult.unifiedView + '\n');
        }
        continue;
      }

      if (cleanInput === '/approve') {
        if (!currentSession.pendingVersion) {
          logger.warn('No pending edits to approve.');
        } else {
          await superdocsClient.approveEdits(
            currentSession.activeDocumentId!,
            currentSession.pendingVersion.id
          );
          saveSession({
            currentContent: currentSession.pendingVersion.content,
            currentHtml: currentSession.pendingVersion.html || currentSession.currentHtml,
            pendingVersion: undefined,
            history: [
              ...currentSession.history,
              {
                versionId: currentSession.pendingVersion.id,
                prompt: currentSession.pendingVersion.prompt,
                timestamp: currentSession.pendingVersion.timestamp
              }
            ]
          });
          logger.success('✔ Pending edits officially approved and locked.');
        }
        continue;
      }

      if (cleanInput === '/export') {
        const fmt = await select({
          message: 'Choose export format:',
          choices: [
            { name: 'Markdown (.md)', value: 'md' },
            { name: 'PDF (.pdf)', value: 'pdf' },
            { name: 'Word (.docx)', value: 'docx' }
          ]
        });
        const buffer = await superdocsClient.exportDocument(
          currentSession.activeDocumentId!,
          fmt,
          currentSession.currentContent,
          currentSession.currentHtml
        );
        const outName = `chat-export-${Date.now()}.${fmt}`;
        fs.writeFileSync(outName, buffer);
        logger.success(`Exported to ${outName}`);
        continue;
      }

      // Natural language prompt: Stream AI edits
      const spinner = ora('SuperDocs AI streaming edits...').start();
      try {
        const proposed = await superdocsClient.streamEdit({
          documentId: currentSession.activeDocumentId!,
          prompt: cleanInput,
          currentContent: currentSession.currentContent,
          currentHtml: currentSession.currentHtml,
          documentName: currentSession.documentName,
          onProgress: (chunk) => {
            if (chunk.reasoning) {
              spinner.text = chalk.dim(chunk.reasoning);
            }
          }
        });

        const diffResult = createDiff(
          currentSession.currentContent,
          proposed.content,
          currentSession.documentName
        );

        proposed.additions = diffResult.additions;
        proposed.deletions = diffResult.deletions;

        saveSession({ pendingVersion: proposed });
        spinner.succeed(chalk.green(`Edits generated: ${formatDiffStats(diffResult)}`));

        // Prompt user for immediate approval or review
        const choice = await select({
          message: 'What would you like to do with these proposed changes?',
          choices: [
            { name: '✔ Approve & Apply Immediately', value: 'approve' },
            { name: '🔍 View Full Terminal Diff', value: 'diff' },
            { name: '⏳ Keep Pending (Continue Prompting)', value: 'keep' },
            { name: '✖ Discard / Reject', value: 'reject' }
          ]
        });

        if (choice === 'approve') {
          await superdocsClient.approveEdits(
            currentSession.activeDocumentId!,
            proposed.id
          );
          saveSession({
            currentContent: proposed.content,
            currentHtml: proposed.html || currentSession.currentHtml,
            pendingVersion: undefined,
            history: [
              ...currentSession.history,
              {
                versionId: proposed.id,
                prompt: cleanInput,
                timestamp: proposed.timestamp
              }
            ]
          });
          logger.success('✔ Changes approved and applied.');
        } else if (choice === 'diff') {
          console.log('\n' + diffResult.unifiedView + '\n');
        } else if (choice === 'reject') {
          saveSession({ pendingVersion: undefined });
          logger.warn('✖ Proposed changes discarded.');
        }
      } catch (err: any) {
        spinner.fail(chalk.red(`Edit failed: ${err.message}`));
      }
    }
  });
