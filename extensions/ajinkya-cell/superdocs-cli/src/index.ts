import { Command } from '@commander-js/extra-typings';
import { initCommand } from './commands/init.js';
import { uploadCommand } from './commands/upload.js';
import { editCommand } from './commands/edit.js';
import { approveCommand } from './commands/approve.js';
import { exportCommand } from './commands/export.js';
import { chatCommand } from './commands/chat.js';
import { statusCommand } from './commands/status.js';
import { logger } from './utils/logger.js';

export function createProgram(): Command {
  const program = new Command();

  program
    .name('superdocs')
    .description('Interactive terminal developer assistant for SuperDocs AI in-document intelligence & editing')
    .version('1.0.1');

  program.addCommand(initCommand);
  program.addCommand(uploadCommand);
  program.addCommand(editCommand);
  program.addCommand(approveCommand);
  program.addCommand(exportCommand);
  program.addCommand(chatCommand);
  program.addCommand(statusCommand);

  return program;
}

export async function runCLI(argv = process.argv): Promise<void> {
  const program = createProgram();

  try {
    await program.parseAsync(argv);
  } catch (err: any) {
    logger.error(`Command error: ${err.message}`, err);
    process.exit(1);
  }
}
