#!/usr/bin/env node
import { preview, approve, resume, status, publicationDryRun } from './workflow.js';
import { writePublicationPlan } from './publication.js';
import { ChangelogError } from './errors.js';

const VERSION = '0.1.0';

function parse(argv) {
  const [command = 'help', ...rest] = argv; const options = { command, accept: [], reject: [], feedback: {} };
  for (let index = 0; index < rest.length; index += 1) {
    const arg = rest[index];
    if (arg === '--json') options.json = true;
    else if (arg === '--overwrite') options.overwrite = true;
    else if (arg === '--changelog') options.canonicalPath = rest[++index];
    else if (arg === '--release') options.releasePath = rest[++index];
    else if (arg === '--run' || arg === '--run-id') options.runId = rest[++index];
    else if (arg === '--state-dir') options.stateDir = rest[++index];
    else if (arg === '--output-dir') options.outputDir = rest[++index];
    else if (arg === '--output') options.output = rest[++index];
    else if (arg === '--accept') options.accept.push(...(rest[++index] || '').split(',').filter(Boolean));
    else if (arg === '--reject') options.reject.push(...(rest[++index] || '').split(',').filter(Boolean));
    else if (arg === '--feedback') { const value = rest[++index] || ''; const [id, ...parts] = value.split('='); options.feedback[id] = parts.join('='); }
    else if (arg === '--repository') options.repository = rest[++index];
    else if (arg === '--base') options.base = rest[++index];
    else if (arg === '--fail-at') options.failAt = rest[++index];
    else throw new ChangelogError(`unknown option: ${arg}`);
  }
  return options;
}

function help() {
  return `Usage: sdx-changelog <command> [options]\n\nCommands:\n  preview             Create a no-spend proposed release\n  approve            Submit explicit item decisions and append/export\n  resume             Resume a durable run without creating replacement work\n  status             Show safe run state\n  publish-dry-run    Produce an intended-publication plan without network\n\nCommon options:\n  --changelog <path> --release <path> --state-dir <path> --output-dir <path>\n  --accept <id,...> --reject <id,...> --feedback <id=text> --json --overwrite\n`;
}

function emit(value, json) { if (json) process.stdout.write(`${JSON.stringify(value)}\n`); else process.stdout.write(`${typeof value === 'string' ? value : JSON.stringify(value, null, 2)}\n`); }

async function main() {
  const options = parse(process.argv.slice(2));
  if (options.command === '--version' || options.command === 'version') return emit(VERSION, options.json);
  if (options.command === 'help' || options.command === '--help') return emit(help(), false);
  let result;
  if (options.command === 'preview') result = await preview(options);
  else if (options.command === 'approve') result = await approve(options);
  else if (options.command === 'resume') result = await resume(options);
  else if (options.command === 'status') result = await status(options);
  else if (options.command === 'publish-dry-run') { result = await publicationDryRun(options); if (options.output) await writePublicationPlan(options.output, result, options.overwrite); }
  else throw new ChangelogError(`unknown command: ${options.command}`);
  emit(result, options.json);
  if (result.status === 'awaiting_decisions' || (result.pending_items && result.pending_items.length)) process.exitCode = 3;
}

main().catch((error) => {
  const safe = { error: { code: error.code || 'ERROR', message: error.message || 'operation failed' } };
  if (process.argv.includes('--json')) process.stdout.write(`${JSON.stringify(safe)}\n`); else process.stderr.write(`${safe.error.code}: ${safe.error.message}\n`);
  process.exitCode = error.exitCode || 1;
});
