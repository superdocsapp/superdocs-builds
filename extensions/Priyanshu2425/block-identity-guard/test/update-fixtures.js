/**
 * Regenerates the expected report for every fixture.
 *
 *   npm run fixtures:update
 *
 * The expected files are the specification: a diff in one of them is a change in
 * what the tool says about a document, which is the whole product. Regenerate
 * deliberately, read the diff, and commit it as part of the change.
 */

import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { checkRoundTrip, formatReport, hasFindingsAtLeast } from '../src/index.js';

const FIXTURES = new URL('../fixtures/', import.meta.url).pathname;

export function fixtureNames() {
  return readdirSync(FIXTURES, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

export function runFixture(name) {
  const directory = join(FIXTURES, name);
  const before = readFileSync(join(directory, 'before.html'), 'utf8');
  const after = readFileSync(join(directory, 'after.html'), 'utf8');
  const report = checkRoundTrip(before, after);
  const text = formatReport(report, { format: 'human', colour: false });
  return {
    directory,
    report,
    text: `${text}\n\nexit code: ${hasFindingsAtLeast(report, 'error') ? 1 : 0}\n`,
  };
}

function main() {
  for (const name of fixtureNames()) {
    const { directory, text } = runFixture(name);
    writeFileSync(join(directory, 'expected.txt'), text, 'utf8');
    process.stdout.write(`updated ${name}/expected.txt\n`);
  }
}

if (process.argv[1] && process.argv[1].endsWith('update-fixtures.js')) main();
