import { createCommand } from '@commander-js/extra-typings';
import { input, select, confirm } from '@inquirer/prompts';
import chalk from 'chalk';
import ora from 'ora';
import { getConfig, saveConfig, resetConfig } from '../utils/state.js';
import { superdocsClient } from '../client/superdocs.js';
import { logger } from '../utils/logger.js';
import { ExportFormat } from '../types.js';

export const initCommand = createCommand('init')
  .description('Initialize SuperDocs configuration, credentials, or automated agent signup')
  .option('-k, --key <key>', 'SuperDocs API Key')
  .option('-u, --url <url>', 'SuperDocs API Base URL (default: https://api.superdocs.app/v1)')
  .option('-s, --signup', 'Automatically provision a new agent API key via SuperDocs Agent Signup')
  .option('-m, --mock', 'Enable local mock/offline simulation mode')
  .option('-l, --live', 'Enable live API mode')
  .option('-f, --format <type>', 'Default export format (pdf, docx, md, html)')
  .option('--reset', 'Reset all persistent configuration to defaults')
  .action(async (options) => {
    logger.banner();

    if (options.reset) {
      resetConfig();
      logger.success('SuperDocs configuration reset to factory defaults.');
      return;
    }

    const currentConfig = getConfig();
    let apiKey = options.key;
    let baseUrl = options.url || currentConfig.baseUrl;
    let mockMode = options.mock ? true : (options.live ? false : (options.key ? false : currentConfig.mockMode));
    let defaultFormat = (options.format as ExportFormat) || currentConfig.defaultExportFormat;

    // Handle automated signup flag
    if (options.signup) {
      mockMode = false;
      const spinner = ora('Registering agent with SuperDocs API...').start();
      try {
        const signupRes = await superdocsClient.signupAgent();
        spinner.succeed(chalk.green(`Agent registered! API Key: ${chalk.bold(signupRes.api_key)}`));
        apiKey = signupRes.api_key;
      } catch (err: any) {
        spinner.fail(chalk.red(`Registration failed: ${err.message}`));
        return;
      }
    }

    // Interactive flow if no flags were provided
    if (!options.key && !options.signup && !options.url && options.mock === undefined && !options.format) {
      const action = await select({
        message: 'How would you like to configure SuperDocs CLI?',
        choices: [
          { name: '🔑 Enter existing SuperDocs API Key', value: 'key' },
          { name: '🤖 Auto-generate Agent API Key (POST /v1/agents/signup)', value: 'signup' },
          { name: '🧪 Use Offline Mock Simulation Mode (No API key required)', value: 'mock' }
        ]
      });

      if (action === 'key') {
        apiKey = await input({
          message: 'Enter your SuperDocs API Key:',
          default: currentConfig.apiKey || ''
        });
      } else if (action === 'signup') {
        const agentName = await input({
          message: 'Enter your Agent/Client name:',
          default: 'superdocs-developer'
        });
        const spinner = ora('Connecting to SuperDocs Agent Signup API...').start();
        try {
          const signupRes = await superdocsClient.signupAgent(agentName);
          spinner.succeed(chalk.green(`Agent registered! Key: ${chalk.bold(signupRes.api_key)}`));
          apiKey = signupRes.api_key;
        } catch (err: any) {
          spinner.fail(chalk.red(`Registration failed: ${err.message}`));
          return;
        }
      } else if (action === 'mock') {
        mockMode = true;
        logger.info('Mock mode activated. All REST and SSE calls will be simulated locally.');
      }

      defaultFormat = (await select({
        message: 'Select default document export format:',
        choices: [
          { name: 'Markdown (.md)', value: 'md' },
          { name: 'PDF Document (.pdf)', value: 'pdf' },
          { name: 'Microsoft Word (.docx)', value: 'docx' },
          { name: 'HTML Document (.html)', value: 'html' }
        ],
        default: currentConfig.defaultExportFormat
      })) as ExportFormat;
    }

    const updated = saveConfig({
      apiKey: apiKey || currentConfig.apiKey,
      baseUrl,
      mockMode,
      defaultExportFormat: defaultFormat
    });

    logger.box(
      'SuperDocs CLI Configuration Saved',
      `Base URL:      ${updated.baseUrl}\n` +
      `API Key:       ${updated.apiKey ? `${updated.apiKey.slice(0, 8)}...` : chalk.yellow('None (Mock/Unset)')}\n` +
      `Mock Mode:     ${updated.mockMode ? chalk.green('ENABLED') : chalk.dim('DISABLED')}\n` +
      `Export Format: ${updated.defaultExportFormat}`
    );

    logger.success('Configuration ready! Next step: run `superdocs upload <file>` to ingest a document.');
  });
