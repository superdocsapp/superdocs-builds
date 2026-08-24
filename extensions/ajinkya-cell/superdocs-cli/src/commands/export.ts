import { createCommand } from '@commander-js/extra-typings';
import fs from 'fs';
import path from 'path';
import ora from 'ora';
import chalk from 'chalk';
import { superdocsClient } from '../client/superdocs.js';
import { getSession, getConfig } from '../utils/state.js';
import { logger } from '../utils/logger.js';

export const exportCommand = createCommand('export')
  .description('Export compiled document from SuperDocs workspace to local disk')
  .option('-f, --format <type>', 'Export format (pdf, docx, md, html, txt)')
  .option('-o, --out <path>', 'Output destination file path')
  .action(async (options) => {
    const session = getSession();
    const config = getConfig();

    if (!session.activeDocumentId || !session.currentContent) {
      logger.error('No active document available to export.');
      logger.info(`Run ${chalk.bold.cyan('superdocs upload <path>')} first.`);
      process.exit(1);
    }

    const format = (options.format || config.defaultExportFormat || 'md').toLowerCase();
    const defaultFileName = session.documentName
      ? `${path.basename(session.documentName, path.extname(session.documentName))}.${format}`
      : `exported-document.${format}`;

    const outputPath = path.resolve(process.cwd(), options.out || defaultFileName);
    const spinner = ora(`Compiling document as ${chalk.bold(format.toUpperCase())}...`).start();

    try {
      const buffer = await superdocsClient.exportDocument(
        session.activeDocumentId,
        format,
        session.currentContent,
        session.currentHtml
      );

      // Ensure directory exists
      const targetDir = path.dirname(outputPath);
      if (!fs.existsSync(targetDir)) {
        fs.mkdirSync(targetDir, { recursive: true });
      }

      fs.writeFileSync(outputPath, buffer);
      spinner.succeed(chalk.green(`Exported successfully!`));

      logger.box(
        'Export Summary',
        `Destination:   ${chalk.bold.cyan(outputPath)}\n` +
        `Format:        ${format.toUpperCase()}\n` +
        `File Size:     ${Math.round(buffer.length / 1024 * 10) / 10} KB (${buffer.length} bytes)`
      );
    } catch (err: any) {
      spinner.fail(chalk.red(`Export failed: ${err.message}`));
      process.exit(1);
    }
  });
