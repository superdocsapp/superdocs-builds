#!/usr/bin/env node
/**
 * chunk-guard -- the pipeline check.
 *
 * Exit codes are the contract:
 *   0  nothing at or above the failure threshold
 *   1  the round trip lost identity
 *   2  the check could not run (bad arguments, unreadable file, unusable input)
 *
 * A reordered document exits 0. A missing identifier exits 1. The two are
 * different events and the exit code says so.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import process from 'node:process';

import { checkRoundTrip, formatReport, hasFindingsAtLeast } from './index.js';
import { createBaseline, applyBaseline } from './baseline.js';
import { extractDocumentHtml } from './capture.js';
import { RULES, SEVERITIES } from './rules.js';

const VERSION = '1.0.0';

const USAGE = `chunk-guard ${VERSION} -- validate a SuperDocs document round trip

USAGE
  chunk-guard check <before.html> <after.html> [options]
  chunk-guard capture <payload> [--out before.html] [--document-id <id>]
  chunk-guard rules
  chunk-guard --help | --version

  <before.html>  HTML as SuperDocs sent it (a document_sync payload)
  <after.html>   HTML as your integration serialised it back
  Use - for either path to read that side from stdin.

CHECK OPTIONS
  --id-attribute <name>       identifier attribute (default: data-chunk-id)
  --format <human|json|github>  report format (default: human)
  --fail-on <error|warning|info|never>  exit 1 at this severity (default: error)
  --strict-parts              treat an omitted header/footer/footnote as a failure
  --include-content-changes   also report blocks whose text changed
  --baseline <file>           accept the findings recorded in this file
  --update-baseline           write the current findings to --baseline and exit 0
  --out <file>                write the report to a file instead of stdout
  --file <path>               path to attribute findings to (github format)
  --no-color                  plain output
  --quiet                     print nothing when the check passes

CAPTURE OPTIONS
  --out <file>                write the extracted HTML here (default: stdout)
  --document-id <id>          pick one document out of a multi-document session
  --event <name>              event to read (default: document_sync)

EXAMPLES
  chunk-guard check fixtures/before.html fixtures/after.html
  chunk-guard check before.html after.html --format github --file before.html
  chunk-guard capture stream.log --out before.html
`;

export function run(argv, io = defaultIo()) {
  const args = argv.slice();
  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    io.out(USAGE);
    return args.length === 0 ? 2 : 0;
  }
  if (args[0] === '--version' || args[0] === '-v') {
    io.out(VERSION);
    return 0;
  }

  const command = args[0].startsWith('-') ? 'check' : args.shift();
  switch (command) {
    case 'check':
      return runCheck(args, io);
    case 'capture':
      return runCapture(args, io);
    case 'rules':
      return runRules(io);
    default:
      io.err(`unknown command: ${command}\n\n${USAGE}`);
      return 2;
  }
}

function runCheck(args, io) {
  let options;
  try {
    options = parseCheckArgs(args);
  } catch (error) {
    io.err(`${error.message}\n\n${USAGE}`);
    return 2;
  }

  let beforeHtml;
  let afterHtml;
  try {
    beforeHtml = readInput(options.beforePath, io);
    afterHtml = readInput(options.afterPath, io);
  } catch (error) {
    io.err(error.message);
    return 2;
  }

  let report;
  try {
    report = checkRoundTrip(beforeHtml, afterHtml, {
      idAttribute: options.idAttribute,
      strictParts: options.strictParts,
      includeContentChanges: options.includeContentChanges,
    });
  } catch (error) {
    io.err(`could not run the check: ${error.message}`);
    return 2;
  }

  if (options.updateBaseline) {
    if (!options.baselinePath) {
      io.err('--update-baseline needs --baseline <file>');
      return 2;
    }
    const baseline = createBaseline(report);
    io.write(options.baselinePath, `${JSON.stringify(baseline, null, 2)}\n`);
    io.out(`wrote ${baseline.accepted.length} accepted finding(s) to ${options.baselinePath}`);
    return 0;
  }

  if (options.baselinePath) {
    try {
      report = applyBaseline(report, JSON.parse(io.read(options.baselinePath)));
    } catch (error) {
      io.err(`could not read baseline ${options.baselinePath}: ${error.message}`);
      return 2;
    }
  }

  const failing = hasFindingsAtLeast(report, options.failOn);
  const text = formatReport(report, {
    format: options.format,
    colour: options.colour && !options.outPath,
    file: options.file || options.beforePath,
  });

  if (options.outPath) io.write(options.outPath, `${text}\n`);
  else if (!options.quiet || failing) io.out(text);

  return failing ? 1 : 0;
}

function runCapture(args, io) {
  let payloadPath = null;
  let outPath = null;
  let documentId = null;
  let event = 'document_sync';

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '--out' || arg === '-o') outPath = args[++i];
    else if (arg === '--document-id') documentId = args[++i];
    else if (arg === '--event') event = args[++i];
    else if (!arg.startsWith('-') || arg === '-') payloadPath = arg;
    else {
      io.err(`unknown option: ${arg}\n\n${USAGE}`);
      return 2;
    }
  }

  if (!payloadPath) {
    io.err(`capture needs a payload file (or - for stdin)\n\n${USAGE}`);
    return 2;
  }

  let extracted;
  try {
    extracted = extractDocumentHtml(readInput(payloadPath, io), { documentId, event });
  } catch (error) {
    io.err(error.message);
    return 2;
  }

  if (outPath) {
    io.write(outPath, extracted.html);
    io.err(
      `wrote ${extracted.html.length} characters from ${extracted.source}`
      + `${extracted.documentId ? ` (document ${extracted.documentId})` : ''} to ${outPath}`,
    );
  } else {
    io.out(extracted.html);
  }
  return 0;
}

function runRules(io) {
  const lines = ['chunk-guard rule table', ''];
  for (const rule of Object.values(RULES)) {
    lines.push(`${rule.severity.toUpperCase().padEnd(8)} ${rule.code}`);
    lines.push(`         ${rule.title}`);
    lines.push(`         ${rule.meaning}`);
    lines.push('');
  }
  io.out(lines.join('\n').trimEnd());
  return 0;
}

function parseCheckArgs(args) {
  const options = {
    beforePath: null,
    afterPath: null,
    idAttribute: 'data-chunk-id',
    format: 'human',
    failOn: 'error',
    strictParts: false,
    includeContentChanges: false,
    baselinePath: null,
    updateBaseline: false,
    outPath: null,
    file: null,
    colour: process.stdout.isTTY === true && !process.env.NO_COLOR,
    quiet: false,
  };

  const positional = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    switch (arg) {
      case '--id-attribute': options.idAttribute = required(args[++i], arg); break;
      case '--format': options.format = required(args[++i], arg); break;
      case '--fail-on': options.failOn = required(args[++i], arg); break;
      case '--baseline': options.baselinePath = required(args[++i], arg); break;
      case '--out': case '-o': options.outPath = required(args[++i], arg); break;
      case '--file': options.file = required(args[++i], arg); break;
      case '--strict-parts': options.strictParts = true; break;
      case '--include-content-changes': options.includeContentChanges = true; break;
      case '--update-baseline': options.updateBaseline = true; break;
      case '--no-color': case '--no-colour': options.colour = false; break;
      case '--color': case '--colour': options.colour = true; break;
      case '--quiet': case '-q': options.quiet = true; break;
      default:
        if (arg !== '-' && arg.startsWith('-')) throw new Error(`unknown option: ${arg}`);
        positional.push(arg);
    }
  }

  if (positional.length !== 2) {
    throw new Error(`check needs exactly two paths, received ${positional.length}`);
  }
  if (!['human', 'json', 'github'].includes(options.format)) {
    throw new Error(`unknown format: ${options.format}`);
  }
  if (options.failOn !== 'never' && !SEVERITIES.includes(options.failOn)) {
    throw new Error(`unknown severity: ${options.failOn}`);
  }
  if (positional[0] === '-' && positional[1] === '-') {
    throw new Error('only one side can be read from stdin');
  }

  options.beforePath = positional[0];
  options.afterPath = positional[1];
  return options;
}

function required(value, flag) {
  if (value === undefined) throw new Error(`${flag} needs a value`);
  return value;
}

function readInput(path, io) {
  try {
    return path === '-' ? io.readStdin() : io.read(path);
  } catch (error) {
    throw new Error(`could not read ${path === '-' ? 'stdin' : path}: ${error.message}`);
  }
}

function defaultIo() {
  return {
    out: (text) => process.stdout.write(`${text}\n`),
    err: (text) => process.stderr.write(`${text}\n`),
    read: (path) => readFileSync(path, 'utf8'),
    readStdin: () => readFileSync(0, 'utf8'),
    write: (path, text) => writeFileSync(path, text, 'utf8'),
  };
}

const invokedDirectly = process.argv[1]
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  process.exitCode = run(process.argv.slice(2));
}

export { USAGE, VERSION, defaultIo };
