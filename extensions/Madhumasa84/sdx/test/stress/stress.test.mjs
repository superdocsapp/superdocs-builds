import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';
import { promisify } from 'node:util';

import JSZip from 'jszip';

import { startFixtureServer } from '../fixtures/server.mjs';
import { generateStyledDocx } from './generate-docx.mjs';

const execFileAsync = promisify(execFile);
const cliPath = new URL('../../dist/cli.js', import.meta.url).pathname;
const evidencePath = new URL('../../docs/evidence/stage4-stress.json', import.meta.url).pathname;

function sha256(bytes) { return createHash('sha256').update(bytes).digest('hex'); }

async function inspectDocx(path, expectedTarget) {
  await execFileAsync('/usr/bin/unzip', ['-tqq', path]);
  const zip = await JSZip.loadAsync(await readFile(path));
  const documentXml = await zip.file('word/document.xml').async('string');
  assert.equal((documentXml.match(/w:type="page"/g) ?? []).length, 119);
  const pageMarkers = new Set(documentXml.match(/SDX_PAGE_\d{3}/g) ?? []);
  assert.equal(pageMarkers.size, 120);
  for (let page = 1; page <= 120; page += 1) {
    assert.ok(pageMarkers.has(`SDX_PAGE_${String(page).padStart(3, '0')}`));
  }
  assert.match(documentXml, new RegExp(expectedTarget));
  assert.match(documentXml, /<w:tbl>/);
  assert.match(documentXml, /<w:numPr>/);
  assert.match(documentXml, /<w:color/);
  assert.ok(zip.file('word/header1.xml'));
  assert.ok(zip.file('word/footer1.xml'));
  assert.ok(Object.keys(zip.files).some((name) => name.startsWith('word/media/') && !name.endsWith('/')));
  return documentXml;
}

function runMeasuredCli(args, { home, baseUrl, input, metricsPath }) {
  return new Promise((resolve, reject) => {
    const start = process.hrtime.bigint();
    const child = spawn('/usr/bin/time', ['-v', '-o', metricsPath, process.execPath, cliPath, ...args], {
      env: {
        ...process.env,
        HOME: home,
        SDX_API_BASE_URL: baseUrl,
        SUPERDOCS_API_KEY: 'fixture-api-key',
        NO_COLOR: '1',
      },
    });
    let stdout = ''; let stderr = '';
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', (value) => { stdout += value; });
    child.stderr.on('data', (value) => { stderr += value; });
    child.on('error', reject);
    child.stdin.end(input);
    child.on('close', (status) => {
      const wallClockMs = Number(process.hrtime.bigint() - start) / 1_000_000;
      resolve({ status, stdout, stderr, wallClockMs });
    });
  });
}

function peakRssKiB(text) {
  const match = text.match(/Maximum resident set size \(kbytes\):\s*(\d+)/);
  assert.ok(match, `GNU time peak RSS missing from:\n${text}`);
  return Number(match[1]);
}

function statistics(values) {
  const sorted = [...values].sort((left, right) => left - right);
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
  const round = (value) => Math.round(value * 1000) / 1000;
  return {
    minimum: round(sorted[0]),
    median: round(sorted[Math.floor(sorted.length / 2)]),
    p95: round(sorted[Math.ceil(sorted.length * 0.95) - 1]),
    maximum: round(sorted.at(-1)),
    mean: round(mean),
    populationVariance: round(variance),
    populationStandardDeviation: round(Math.sqrt(variance)),
  };
}

test('five-run 120-page styled DOCX pre-signed workflow remains streaming and verifiable', { timeout: 180_000 }, async () => {
  const root = await mkdtemp('/tmp/sdx-stage4-stress-');
  const sourcePath = join(root, 'styled-120-pages.docx');
  const editedPath = join(root, 'edited-120-pages.docx');
  try {
    const sourceBytes = await generateStyledDocx(sourcePath);
    const editedBytes = await generateStyledDocx(editedPath, { edited: true });
    const sourceHash = sha256(sourceBytes); const outputHash = sha256(editedBytes);
    await inspectDocx(sourcePath, 'SDX_TARGET_PAGE_120_ORIGINAL');
    await inspectDocx(editedPath, 'SDX_TARGET_PAGE_120_EDITED');

    const regeneratedPath = join(root, 'regenerated.docx');
    assert.equal(sha256(await generateStyledDocx(regeneratedPath)), sourceHash, 'fixture generation must be byte-deterministic');

    const observations = [];
    for (let iteration = 1; iteration <= 5; iteration += 1) {
      const home = join(root, `home-${iteration}`); await mkdir(home, { recursive: true, mode: 0o700 });
      const outputPath = join(root, `result-${iteration}.docx`);
      const metricsPath = join(root, `time-${iteration}.txt`);
      const fixture = await startFixtureServer({ streamingUpload: true, downloadBytes: editedBytes });
      try {
        const result = await runMeasuredCli([
          'edit', sourcePath,
          'Replace SDX_TARGET_PAGE_120_ORIGINAL with SDX_TARGET_PAGE_120_EDITED only',
          '--approve', '--output', outputPath, '--export', 'docx',
          '--poll-interval', '1', '--timeout', '10', '--no-color',
        ], { home, baseUrl: fixture.baseUrl, input: 'y\ny\n', metricsPath });
        assert.equal(result.status, 0, result.stderr);
        assert.match(result.stdout, /Exported verified document to/);
        assert.equal(fixture.observations.editCalls, 1);
        assert.equal(fixture.observations.approvalCalls, 1);
        assert.equal(fixture.observations.downloadCalls, 1);
        assert.equal(fixture.observations.uploadedByteCount, sourceBytes.length);
        assert.equal(fixture.observations.uploadedSha256, sourceHash);
        assert.equal(fixture.observations.uploadedBytes.length, 0, 'streaming fixture must not retain the whole request body');
        assert.ok(fixture.observations.uploadChunkCount > 1);
        assert.ok(fixture.observations.maxUploadChunkBytes < sourceBytes.length);
        assert.equal(fixture.observations.signedUploadAuthorization, undefined);
        assert.equal(fixture.observations.signedDownloadAuthorization, undefined);
        assert.equal(fixture.observations.uploadRequest.size_bytes, sourceBytes.length);
        assert.equal(fixture.observations.editRequest.message.includes('SDX_TARGET_PAGE_120_ORIGINAL'), true);
        const apiBodies = JSON.stringify({
          upload: fixture.observations.uploadRequest,
          process: fixture.observations.processRequest,
          edit: fixture.observations.editRequest,
          approval: fixture.observations.approvalRequest,
          download: fixture.observations.downloadRequest,
        });
        assert.doesNotMatch(apiBodies, /UEsDB|base64|X-Amz-Signature/i);

        const outputBytes = await readFile(outputPath);
        assert.equal(outputBytes.length, editedBytes.length);
        assert.equal(sha256(outputBytes), outputHash);
        await inspectDocx(outputPath, 'SDX_TARGET_PAGE_120_EDITED');
        assert.equal(sha256(await readFile(sourcePath)), sourceHash, 'source must remain untouched');
        const outputInfo = await stat(outputPath); assert.ok(outputInfo.size > 0);
        const metricText = await readFile(metricsPath, 'utf8');
        observations.push({
          iteration,
          inputBytes: sourceBytes.length,
          inputSha256: sourceHash,
          outputBytes: outputBytes.length,
          outputSha256: outputHash,
          wallClockMs: Math.round(result.wallClockMs * 1000) / 1000,
          peakRssKiB: peakRssKiB(metricText),
          uploadChunkCount: fixture.observations.uploadChunkCount,
          maximumUploadChunkBytes: fixture.observations.maxUploadChunkBytes,
          chatSubmissions: fixture.observations.editCalls,
          failures: [],
        });
      } finally {
        await fixture.close();
      }
    }

    const evidence = {
      schemaVersion: 1,
      provenance: 'offline deterministic contract-derived fixture; no live API operation',
      measurementMethod: 'docs/stress-method.md',
      runtime: { node: process.version, platform: process.platform, architecture: process.arch, peakRssTool: '/usr/bin/time -v' },
      renderedPageCountMeasured: false,
      structuralPageCount: 120,
      explicitPageBreaks: 119,
      iterations: observations,
      statistics: {
        wallClockMs: statistics(observations.map((entry) => entry.wallClockMs)),
        peakRssKiB: statistics(observations.map((entry) => entry.peakRssKiB)),
      },
      failures: [],
    };
    await mkdir(new URL('../../docs/evidence/', import.meta.url), { recursive: true });
    await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
