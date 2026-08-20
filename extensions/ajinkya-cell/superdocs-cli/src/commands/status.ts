import { createCommand } from '@commander-js/extra-typings';
import chalk from 'chalk';
import { getConfig, getSession } from '../utils/state.js';
import { logger } from '../utils/logger.js';
import { formatDiffStats, createDiff } from '../utils/diff.js';

export const statusCommand = createCommand('status')
  .description('Display current SuperDocs configuration, credentials, and active document session')
  .action(async () => {
    logger.banner();

    const config = getConfig();
    const session = getSession();

    logger.box(
      'SuperDocs Configuration',
      `Base URL:       ${config.baseUrl}\n` +
      `API Key:        ${config.apiKey ? `${chalk.green('Configured')} (${config.apiKey.slice(0, 10)}...)` : chalk.yellow('Not Set (Mock or Unset)')}\n` +
      `Mock Mode:      ${config.mockMode ? chalk.green('ENABLED (Offline simulation)') : chalk.dim('DISABLED (Live API)')}\n` +
      `Default Format: ${config.defaultExportFormat}`
    );

    if (session.activeDocumentId && session.currentContent) {
      let pendingStatus = chalk.dim('None');
      if (session.pendingVersion) {
        const diff = createDiff(
          session.currentContent,
          session.pendingVersion.content,
          session.documentName
        );
        pendingStatus = `${chalk.yellow('Pending Approval')} (${formatDiffStats(diff)})`;
      }

      logger.box(
        'Active Document Session',
        `Document ID:    ${chalk.bold.cyan(session.activeDocumentId)}\n` +
        `Document Name:  ${session.documentName || 'Unnamed'}\n` +
        `Source Path:    ${session.originalPath || 'In-Memory'}\n` +
        `Length:         ${session.currentContent.length} chars (${session.currentContent.split('\n').length} lines)\n` +
        `Applied Edits:  ${session.history.length}\n` +
        `Pending Edit:   ${pendingStatus}`
      );

      if (session.history.length > 0) {
        console.log(chalk.bold('\nRecent Edit History:'));
        session.history.slice(-5).forEach((h, i) => {
          console.log(`  ${chalk.cyan(`${i + 1}.`)} [${chalk.dim(new Date(h.timestamp).toLocaleTimeString())}] "${chalk.bold(h.prompt)}" (${h.versionId})`);
        });
      }
    } else {
      logger.info(chalk.dim('No active document session. Run `superdocs upload <file>` to ingest a document.'));
    }
  });
