import chalk from 'chalk';
import highlight from 'cli-highlight';

export const logger = {
  banner() {
    console.log(chalk.bold.cyan(`
   _____                      ____             
  / ___/__  ______  ___  _____/ __ \\____  ____ 
  \\__ \\/ / / / __ \\/ _ \\/ ___/ / / / __ \\/ ___/
 ___/ / /_/ / /_/ /  __/ /  / /_/ / /_/ / /__  
/____/\\__,_/ .___/\\___/_/  /_____/\\____/\\___/   
          /_/                                   
  ${chalk.dim('AI-Powered In-Document Developer Assistant')}
`));
  },

  info(msg: string) {
    console.log(`${chalk.blue('ℹ')} ${msg}`);
  },

  success(msg: string) {
    console.log(`${chalk.green('✔')} ${chalk.bold(msg)}`);
  },

  warn(msg: string) {
    console.log(`${chalk.yellow('⚠')} ${chalk.yellow(msg)}`);
  },

  error(msg: string, detail?: unknown) {
    console.error(`${chalk.red('✖')} ${chalk.red.bold(msg)}`);
    if (detail) {
      if (detail instanceof Error) {
        console.error(chalk.dim(detail.stack || detail.message));
      } else {
        console.error(chalk.dim(JSON.stringify(detail, null, 2)));
      }
    }
  },

  step(num: number, total: number, msg: string) {
    console.log(`${chalk.cyan(`[${num}/${total}]`)} ${chalk.bold(msg)}`);
  },

  box(title: string, content: string) {
    const lines = content.split('\n');
    const width = Math.max(title.length + 4, ...lines.map(l => l.length)) + 4;
    const border = '─'.repeat(width);

    console.log(chalk.cyan(`┌─ ${chalk.bold(title)} ${border.slice(title.length + 3)}┐`));
    for (const line of lines) {
      const padding = ' '.repeat(Math.max(0, width - line.length - 2));
      console.log(chalk.cyan('│ ') + line + padding + chalk.cyan('│'));
    }
    console.log(chalk.cyan(`└${border}┘`));
  },

  highlightCode(code: string, language = 'markdown'): string {
    try {
      return highlight.highlight(code, { language, ignoreIllegals: true });
    } catch {
      return code;
    }
  }
};
