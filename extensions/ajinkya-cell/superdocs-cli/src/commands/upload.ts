import { createCommand } from '@commander-js/extra-typings';
import fs from 'fs';
import path from 'path';
import ora from 'ora';
import chalk from 'chalk';
import { superdocsClient } from '../client/superdocs.js';
import { saveSession } from '../utils/state.js';
import { logger } from '../utils/logger.js';

export const uploadCommand = createCommand('upload')
  .description('Upload a document to SuperDocs workspace and set active session')
  .argument('<path>', 'Path to local file (.md, .txt, .pdf, .docx)')
  .action(async (filePath) => {
    const resolvedPath = path.resolve(process.cwd(), filePath);

    if (!fs.existsSync(resolvedPath)) {
      logger.error(`File not found: ${resolvedPath}`);
      process.exit(1);
    }

    const stats = fs.statSync(resolvedPath);
    const fileName = path.basename(resolvedPath);
    const spinner = ora(`Uploading ${chalk.bold(fileName)} (${Math.round(stats.size / 1024)} KB) to SuperDocs...`).start();

    try {
      const res = await superdocsClient.uploadDocument(resolvedPath);

      saveSession({
        activeDocumentId: res.document_id,
        documentName: res.name || fileName,
        originalPath: resolvedPath,
        originalContent: res.content || '',
        currentContent: res.content || '',
        originalHtml: res.html,
        currentHtml: res.html,
        pendingVersion: undefined,
        history: []
      });

      spinner.succeed(chalk.green(`Document ingested successfully!`));

      logger.box(
        'Active SuperDocs Session',
        `Document ID:   ${chalk.bold.cyan(res.document_id)}\n` +
        `File Name:     ${res.name || fileName}\n` +
        `Source Path:   ${resolvedPath}\n` +
        `Length:        ${(res.content || '').length} characters (${(res.content || '').split(/\s+/).filter(Boolean).length} words)`
      );

      logger.info(`Next step: Run ${chalk.bold.cyan('superdocs edit --prompt "<instruction>"')} or ${chalk.bold.cyan('superdocs chat')} to modify.`);
    } catch (err: any) {
      spinner.fail(chalk.red(`Upload failed: ${err.message}`));
      process.exit(1);
    }
  });
