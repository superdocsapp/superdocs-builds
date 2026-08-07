import { createInterface } from 'node:readline/promises';

import { Command } from 'commander';

import { SuperDocsClient } from './api/client.js';
import { SdxError, asSdxError } from './api/errors.js';
import { ExportFormatSchema } from './api/schemas.js';
import { approveJob } from './commands/approve.js';
import { authLogin, authStatus } from './commands/auth.js';
import { completionScript } from './commands/completions.js';
import { doctor } from './commands/doctor.js';
import { editDocumentV3, type InteractiveDecision } from './commands/edit-v3.js';
import { createDocument } from './commands/new.js';
import { listProfiles, showProfile, useProfile } from './commands/profiles.js';
import { resumeJob } from './commands/resume.js';
import { listSessions, removeSession, showSession } from './commands/sessions.js';
import { ProfileStore, resolveConfiguration, type ConfigurationOverrides, type RuntimeConfiguration } from './config/store.js';
import { failureEnvelope } from './core/envelope.js';
import { EXIT_CODES, type ExitCode } from './core/exit-codes.js';
import { commandAbortController } from './core/interrupt.js';
import type { OutputEnvelope } from './core/output.js';
import { OperationLedger } from './operations/ledger.js';
import { JsonPresenter, HumanPresenter } from './presentation/output.js';
import { renderProposedChange } from './presentation/diff.js';
import { readHiddenCredential, resolveCredential } from './security/credentials.js';
import { redactText } from './security/redaction.js';
import { PendingJobStore, SessionStore } from './sessions/store.js';
import { withSessionLock } from './storage/lock.js';

export const VERSION = '0.1.0';

interface CliOptions {
  readonly profile?: string; readonly session?: string; readonly json?: boolean;
  readonly output?: string; readonly export?: string; readonly timeout?: string;
  readonly verbose?: boolean; readonly color?: boolean; readonly format?: string;
  readonly pollInterval?: string; readonly approve?: boolean; readonly overwrite?: boolean;
  readonly diffLimit?: string; readonly accept?: string; readonly reject?: string;
  readonly acceptAll?: boolean; readonly feedback?: string; readonly title?: string;
}

function numberValue(value: string | undefined, label: string, defaultValue?: number): number | undefined {
  if (value === undefined) return defaultValue;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) throw new SdxError(`${label} must be a positive number.`, EXIT_CODES.invalidInput);
  return parsed;
}

function optionsOf(command: Command): CliOptions { return command.optsWithGlobals() as CliOptions; }

async function configurationFor(command: Command): Promise<{ configuration: RuntimeConfiguration; profiles: ProfileStore }> {
  const options = optionsOf(command);
  const profiles = new ProfileStore();
  const exportRaw = options.export ?? options.format;
  const normalizedExport = exportRaw === 'md' ? 'markdown' : exportRaw;
  const cli: ConfigurationOverrides = {
    ...(options.profile ? { profile: options.profile } : {}),
    ...(normalizedExport ? { exportFormat: normalizedExport } : {}),
    ...(options.timeout ? { timeoutSeconds: numberValue(options.timeout, '--timeout') as number } : {}),
    ...(options.pollInterval ? { pollIntervalMs: numberValue(options.pollInterval, '--poll-interval') as number } : {}),
    ...(options.color === false || process.env.NO_COLOR !== undefined ? { color: 'never' as const } : {}),
  };
  return { configuration: await resolveConfiguration(profiles, cli), profiles };
}

async function clientFor(configuration: RuntimeConfiguration): Promise<SuperDocsClient> {
  const credential = await resolveCredential();
  if (!credential) throw new SdxError('No SuperDocs credential is available. Run `sdx auth login` or set SUPERDOCS_API_KEY.', EXIT_CODES.authenticationFailure);
  return new SuperDocsClient(credential.apiKey, configuration.apiBaseUrl, fetch, {
    retryBudgetMs: configuration.timeoutSeconds * 1000,
    onRetry: (plan, operation) => new HumanPresenter().diagnostic(
      `Retrying ${operation} after ${plan.delayMs}ms (${plan.kind}, completed attempt ${plan.attempt}).`,
    ),
  });
}

function emit(envelope: OutputEnvelope, json: boolean, human: (envelope: OutputEnvelope) => void): void {
  if (json) new JsonPresenter().result(envelope); else human(envelope);
}

async function guarded(
  command: Command, name: string, action: (options: CliOptions) => Promise<{ envelope: OutputEnvelope; exitCode?: ExitCode }>,
  human: (envelope: OutputEnvelope) => void, documentPath?: string,
): Promise<void> {
  const startedAt = new Date(); const options = optionsOf(command);
  try {
    const result = await action(options); emit(result.envelope, options.json === true, human);
    process.exitCode = result.exitCode ?? (result.envelope.ok ? EXIT_CODES.success : EXIT_CODES.invalidInput);
  } catch (error) {
    const failure = asSdxError(error, `sdx ${name} failed unexpectedly.`, EXIT_CODES.apiFailure);
    if (options.json) new JsonPresenter().result(failureEnvelope(name, failure, startedAt, documentPath));
    else new HumanPresenter().diagnostic(redactText(failure.message));
    process.exitCode = failure.exitCode;
  }
}

function renderEditHuman(envelope: OutputEnvelope, color: boolean, diffLimit: number): void {
  const presenter = new HumanPresenter();
  if (envelope.status === 'awaiting_approval') {
    presenter.result(`Changes waiting for approval: ${envelope.changes.length}`);
    const proposed = envelope.changes.map((change) => ({
      id: change.id, operation: change.operation ?? 'edit', chunkId: change.chunkId ?? null,
      documentId: change.documentId ?? null, oldContent: change.before, newContent: change.after,
      explanation: change.explanation ?? change.summary,
    }));
    proposed.forEach((change, index) => presenter.result(`\n${renderProposedChange(change, index + 1, proposed.length, { color, maxCharacters: diffLimit })}`));
    presenter.result(`\nPending change IDs: ${envelope.changes.map((change) => change.id).join(',')}`);
    presenter.result(`Approval command: sdx approve ${envelope.job?.id ?? '<job-id>'} --accept <accepted-change-ids> --reject <rejected-change-ids>`);
  } else if (envelope.status === 'completed') presenter.result(envelope.document?.outputPath ? `Exported verified document to ${envelope.document.outputPath}` : 'Approval completed and verified.');
  else if (envelope.status === 'unchanged') presenter.result('No document changes were needed.');
  else if (envelope.status === 'rejected') presenter.result('All proposed changes were explicitly rejected.');
  else presenter.diagnostic(envelope.error?.message ?? 'Command failed.');
}

function renderData(envelope: OutputEnvelope): void {
  const presenter = new HumanPresenter();
  if (envelope.command === 'doctor' && envelope.diagnostics) {
    for (const item of envelope.diagnostics) presenter.result(`${item.status.toUpperCase()} ${item.name}: ${item.message}`);
    return;
  }
  if (envelope.command === 'sessions remove') { presenter.result(envelope.warnings[0] ?? 'Local alias removed.'); return; }
  if (envelope.command === 'auth login') { presenter.result('Credential stored securely.'); return; }
  if (envelope.data) presenter.result(JSON.stringify(envelope.data, null, 2));
  else presenter.result(envelope.status);
}

function colorEnabled(configuration: RuntimeConfiguration, stream: NodeJS.WriteStream): boolean {
  return stream.isTTY === true && configuration.color !== 'never' && process.env.NO_COLOR === undefined;
}

function commaList(value: string | undefined): string[] {
  if (value === undefined || value.trim() === '') return [];
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function promptReader(): {
  askYesNo: (question: string) => Promise<boolean>;
  askOptional: (question: string) => Promise<string | undefined>;
  close: () => void;
} {
  const prompt = createInterface({ input: process.stdin, output: process.stderr });
  const answers = prompt[Symbol.asyncIterator]();
  const next = async (question: string): Promise<string | undefined> => {
    process.stderr.write(question); const answer = await answers.next();
    return answer.done ? undefined : answer.value;
  };
  return {
    askYesNo: async (question) => {
      while (true) {
        const answer = (await next(question))?.trim().toLowerCase();
        if (answer === 'y' || answer === 'yes') return true;
        if (answer === 'n' || answer === 'no') return false;
        if (answer === undefined) throw new SdxError('Approval input ended before every proposal received a decision.', EXIT_CODES.invalidInput);
        process.stderr.write('Please answer yes or no.\n');
      }
    },
    askOptional: async (question) => { const answer = await next(question); return answer?.trim() || undefined; },
    close: () => prompt.close(),
  };
}

export function createProgram(): Command {
  const program = new Command();
  program.name('sdx').description('Pipe-friendly document workflows for SuperDocs').version(VERSION).showHelpAfterError()
    .option('--profile <name>', 'configuration profile')
    .option('--session <name>', 'durable local session alias')
    .option('--json', 'emit exactly one JSON object', false)
    .option('--output <path>', 'export destination')
    .option('--export <format>', 'export format: docx, pdf, html, md, or txt')
    .option('--timeout <seconds>', 'overall operation timeout in seconds')
    .option('--verbose', 'show safe diagnostics', false)
    .option('--no-color', 'disable colour output');

  program.command('edit').description('Edit a local document through explicit review')
    .argument('<document>', 'DOCX, PDF, HTML, MD, RTF, or TXT path').argument('<instruction>', 'editing instruction')
    .option('--approve', 'review every proposed change interactively', false)
    .option('--format <format>', 'legacy alias for --export')
    .option('--poll-interval <ms>', 'job polling interval in milliseconds')
    .option('--diff-limit <characters>', 'maximum visible characters per old/new block', '4000')
    .option('--overwrite', 'atomically replace an existing output', false)
    .action(async (documentPath: string, instruction: string, _local: CliOptions, command: Command) => {
      let outputColor = false;
      await guarded(command, 'edit', async (options) => {
        if (options.approve && options.json) throw new SdxError('`--approve` is interactive and cannot be combined with `--json`.', EXIT_CODES.invalidInput);
        const { configuration } = await configurationFor(command); const client = await clientFor(configuration);
        outputColor = colorEnabled(configuration, process.stdout);
        const sessions = new SessionStore(); const jobs = new PendingJobStore(); const ledger = new OperationLedger(); const controller = commandAbortController();
        const interrupt = (): void => controller.abort(); process.once('SIGINT', interrupt);
        const prompts = options.approve ? promptReader() : undefined;
        let activeJobId: string | undefined;
        const diffLimit = numberValue(options.diffLimit, '--diff-limit', 4000) as number;
        try {
          const runEdit = () => editDocumentV3({
            documentPath, instruction, approve: options.approve === true,
            ...(options.output ? { outputPath: options.output } : {}), format: configuration.exportFormat,
            modelTier: configuration.modelTier, ...(options.session ? { sessionName: options.session } : {}),
            pollIntervalMs: configuration.pollIntervalMs, timeoutMs: configuration.timeoutSeconds * 1000,
            overwrite: options.overwrite === true, signal: controller.signal,
          }, {
            client, sessions, jobs, ledger,
            decideChange: async (change, index, total): Promise<InteractiveDecision> => {
              process.stderr.write(`\n${renderProposedChange(change, index, total, { color: colorEnabled(configuration, process.stderr), maxCharacters: diffLimit })}\n`);
              const approved = await prompts?.askYesNo('Apply this change? [y/n] ');
              if (approved === undefined) throw new SdxError('Interactive approval is unavailable.', EXIT_CODES.invalidInput);
              const feedback = approved || process.stdin.isTTY !== true ? undefined : await prompts?.askOptional('Optional rejection feedback (Enter to skip): ');
              return { approved, ...(feedback ? { feedback } : {}) };
            },
            decideContinuation: (message) => prompts?.askYesNo(`\n${message}\nContinue the edit? [y/n] `) ?? Promise.reject(new SdxError('Continuation requires interactive approval.', EXIT_CODES.invalidInput)),
            diagnostic: (message) => new HumanPresenter().diagnostic(message),
            onJobStarted: (jobId) => { activeJobId = jobId; },
          });
          const result = options.session
            ? await withSessionLock(options.session, runEdit, { signal: controller.signal })
            : await runEdit();
          return result;
        } catch (error) {
          if (controller.signal.aborted && activeJobId) {
            throw new SdxError(`Operation interrupted by the user. Remote job ${activeJobId} may still be running; it was not cancelled.`, EXIT_CODES.interrupted, undefined, { cause: error });
          }
          throw error;
        } finally { prompts?.close(); process.removeListener('SIGINT', interrupt); }
      }, (envelope) => {
        const configured = { color: outputColor, limit: numberValue(optionsOf(command).diffLimit, '--diff-limit', 4000) as number };
        renderEditHuman(envelope, configured.color, configured.limit);
      }, documentPath);
    });

  program.command('approve').description('Submit explicit programmatic decisions for a pending job')
    .argument('<job-id>', 'pending job ID').option('--accept <ids>', 'comma-separated accepted change IDs')
    .option('--reject <ids>', 'comma-separated rejected change IDs').option('--accept-all', 'explicitly accept every pending change', false)
    .option('--feedback <text>', 'feedback applied to rejected changes').option('--poll-interval <ms>', 'job polling interval in milliseconds')
    .option('--overwrite', 'atomically replace an existing output', false)
    .action(async (jobId: string, _local: CliOptions, command: Command) => guarded(command, 'approve', async (options) => {
      const { configuration } = await configurationFor(command); const client = await clientFor(configuration);
      const exportCandidate = options.export ? (options.export === 'md' ? 'markdown' : options.export) : undefined;
      const parsedExport = exportCandidate ? ExportFormatSchema.safeParse(exportCandidate) : undefined;
      if (parsedExport && !parsedExport.success) throw new SdxError('Export format must be docx, pdf, html, md, or txt.', EXIT_CODES.invalidInput);
      const jobs = new PendingJobStore(); const ledger = new OperationLedger();
      const runApprove = () => approveJob({
        jobId, accept: commaList(options.accept), reject: commaList(options.reject), acceptAll: options.acceptAll === true,
        ...(options.feedback ? { feedback: options.feedback } : {}), ...(parsedExport?.success ? { exportFormat: parsedExport.data } : {}),
        ...(options.output ? { outputPath: options.output } : {}), overwrite: options.overwrite === true,
        pollIntervalMs: configuration.pollIntervalMs, timeoutMs: configuration.timeoutSeconds * 1000,
      }, { client, jobs, ledger, diagnostic: (message) => new HumanPresenter().diagnostic(message) });
      const pending = await jobs.get(jobId);
      return pending?.sessionName ? withSessionLock(pending.sessionName, runApprove) : runApprove();
    }, (envelope) => renderEditHuman(envelope, false, 4000)));

  program.command('resume').description('Resume one persisted remote job without creating replacement work')
    .argument('[job-id]', 'persisted job ID')
    .option('--approve', 'review repeated proposals and continuation prompts interactively', false)
    .option('--poll-interval <ms>', 'job polling interval in milliseconds')
    .option('--overwrite', 'atomically replace an existing output', false)
    .action(async (jobId: string | undefined, _local: CliOptions, command: Command) => guarded(command, 'resume', async (options) => {
      if (options.approve && options.json) throw new SdxError('`--approve` is interactive and cannot be combined with `--json`.', EXIT_CODES.invalidInput);
      const { configuration } = await configurationFor(command); const client = await clientFor(configuration);
      const controller = commandAbortController(); const interrupt = (): void => controller.abort(); process.once('SIGINT', interrupt);
      const prompts = options.approve ? promptReader() : undefined;
      try {
        return await resumeJob({
          ...(jobId ? { jobId } : {}), ...(options.session ? { sessionName: options.session } : {}),
          approve: options.approve === true, overwrite: options.overwrite === true,
          pollIntervalMs: configuration.pollIntervalMs, timeoutMs: configuration.timeoutSeconds * 1000,
          signal: controller.signal,
        }, {
          client, jobs: new PendingJobStore(), ledger: new OperationLedger(),
          decideChange: async (change, index, total) => {
            process.stderr.write(`\n${renderProposedChange(change, index, total, { color: colorEnabled(configuration, process.stderr), maxCharacters: 4000 })}\n`);
            const approved = await prompts?.askYesNo('Apply this change? [y/n] ');
            if (approved === undefined) throw new SdxError('Interactive approval is unavailable.', EXIT_CODES.invalidInput);
            const feedback = approved || process.stdin.isTTY !== true ? undefined : await prompts?.askOptional('Optional rejection feedback (Enter to skip): ');
            return { approved, ...(feedback ? { feedback } : {}) };
          },
          decideContinuation: (message) => prompts?.askYesNo(`\n${message}\nContinue the edit? [y/n] `) ?? Promise.reject(new SdxError('Continuation requires interactive approval.', EXIT_CODES.invalidInput)),
          diagnostic: (message) => new HumanPresenter().diagnostic(message),
        });
      } finally { prompts?.close(); process.removeListener('SIGINT', interrupt); }
    }, (envelope) => renderEditHuman(envelope, false, 4000)));

  program.command('new').description('Create a document from a text file or streamed stdin')
    .argument('[file]', 'Markdown, TXT, or HTML source').option('--title <title>', 'document title')
    .option('--overwrite', 'atomically replace an existing output', false)
    .action(async (filePath: string | undefined, _local: CliOptions, command: Command) => guarded(command, 'new', async (options) => {
      if (!options.title?.trim()) throw new SdxError('`--title` must not be empty.', EXIT_CODES.invalidInput);
      const { configuration } = await configurationFor(command); const client = await clientFor(configuration);
      const controller = commandAbortController(); const interrupt = (): void => controller.abort(); process.once('SIGINT', interrupt);
      try {
        const runNew = () => createDocument({
          ...(filePath ? { filePath } : {}), title: options.title ?? '', format: configuration.exportFormat,
          ...(options.output ? { outputPath: options.output } : {}), ...(options.session ? { sessionName: options.session } : {}),
          overwrite: options.overwrite === true, signal: controller.signal,
        }, { client, sessions: new SessionStore(), jobs: new PendingJobStore(), input: process.stdin, inputIsTTY: process.stdin.isTTY === true, diagnostic: (message) => new HumanPresenter().diagnostic(message) });
        return options.session ? withSessionLock(options.session, runNew, { signal: controller.signal }) : runNew();
      } finally { process.removeListener('SIGINT', interrupt); }
    }, (envelope) => renderEditHuman(envelope, false, 4000), filePath));

  const auth = program.command('auth').description('Manage credentials');
  auth.command('login').description('store an API key using a hidden prompt').action(async (_local: CliOptions, command: Command) => guarded(command, 'auth login', async () => ({ envelope: await authLogin(readHiddenCredential) }), renderData));
  auth.command('status').description('show safe credential status').action(async (_local: CliOptions, command: Command) => guarded(command, 'auth status', async () => { const { configuration } = await configurationFor(command); return { envelope: await authStatus(configuration) }; }, renderData));

  const profiles = program.command('profiles').description('Inspect and select profiles');
  profiles.command('list').action(async (_local: CliOptions, command: Command) => guarded(command, 'profiles list', async () => ({ envelope: await listProfiles(new ProfileStore()) }), renderData));
  profiles.command('show').argument('<name>').action(async (name: string, _local: CliOptions, command: Command) => guarded(command, 'profiles show', async () => ({ envelope: await showProfile(new ProfileStore(), name) }), renderData));
  profiles.command('use').argument('<name>').action(async (name: string, _local: CliOptions, command: Command) => guarded(command, 'profiles use', async () => ({ envelope: await useProfile(new ProfileStore(), name) }), renderData));

  const sessions = program.command('sessions').description('Manage local named-session aliases');
  sessions.command('list').action(async (_local: CliOptions, command: Command) => guarded(command, 'sessions list', async () => ({ envelope: await listSessions(new SessionStore()) }), renderData));
  sessions.command('show').argument('<name>').action(async (name: string, _local: CliOptions, command: Command) => guarded(command, 'sessions show', async () => ({ envelope: await showSession(new SessionStore(), name) }), renderData));
  sessions.command('remove').argument('<name>').action(async (name: string, _local: CliOptions, command: Command) => guarded(command, 'sessions remove', async () => ({ envelope: await removeSession(new SessionStore(), name) }), renderData));

  program.command('completions').description('write a deterministic shell completion script').argument('<shell>', 'bash, zsh, or fish')
    .action((shell: string) => { try { process.stdout.write(completionScript(shell)); } catch (error) { const failure = asSdxError(error, 'Completion generation failed.', EXIT_CODES.invalidInput); process.stderr.write(`${failure.message}\n`); process.exitCode = failure.exitCode; } });

  program.command('doctor').description('run non-billable local diagnostics').action(async (_local: CliOptions, command: Command) => guarded(command, 'doctor', async () => {
    const { configuration, profiles: store } = await configurationFor(command);
    const envelope = await doctor(configuration, store, new SessionStore(), new PendingJobStore(), new OperationLedger());
    return { envelope, exitCode: envelope.ok ? EXIT_CODES.success : EXIT_CODES.invalidInput };
  }, renderData));
  return program;
}

await createProgram().parseAsync(process.argv);
