import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { verifyExportFile } from '../../dist/api/export-validation.js';
import { createFixtureDocx, createFixturePdf } from '../fixtures/export-artifacts.mjs';

test('structural export validation accepts valid PDF and DOCX artifacts', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'sdx-export-validation-'));
  try {
    const pdf = join(directory, 'result.pdf');
    const docx = join(directory, 'result.docx');
    await writeFile(pdf, createFixturePdf());
    await writeFile(docx, await createFixtureDocx());
    await verifyExportFile(pdf, 'pdf');
    await verifyExportFile(docx, 'docx');
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('PDF validation scans large files without requiring page markers in the tail', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'sdx-export-validation-'));
  try {
    const path = join(directory, 'large.pdf');
    const base = createFixturePdf();
    const eof = base.lastIndexOf(Buffer.from('%%EOF'));
    await writeFile(path, Buffer.concat([base.subarray(0, eof), Buffer.alloc(70 * 1024, 0x20), base.subarray(eof)]));
    await verifyExportFile(path, 'pdf');
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('invalid PDF and DOCX artifacts fail before finalization', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'sdx-export-validation-'));
  try {
    for (const [name, format] of [['result.pdf', 'pdf'], ['result.docx', 'docx']]) {
      const path = join(directory, name);
      await writeFile(path, Buffer.from('not a ' + format));
      await assert.rejects(
        verifyExportFile(path, format),
        (error) => error.exitCode === 24 && /structural verification/.test(error.message),
      );
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
