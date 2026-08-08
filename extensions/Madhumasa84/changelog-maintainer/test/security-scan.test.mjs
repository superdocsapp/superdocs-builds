import assert from 'node:assert/strict';
import { readdir, readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

const root = new URL('..', import.meta.url).pathname;
const scanRoots = ['src', 'test', 'docs', 'schemas', 'fixtures'];
const forbidden = [
  new RegExp('sk_' + '[A-Za-z0-9]{20,}'),
  new RegExp('X-Amz-' + 'Signature=[A-Za-z0-9%_-]{16,}'),
  new RegExp('Authorization\\s*:\\s*Bearer\\s+[A-Za-z0-9._-]{20,}', 'i'),
  /\/home\/masa84|\/mnt\/c\/Users\/Dell/i,
];

async function filesUnder(path) {
  const info = await stat(path); if (info.isFile()) return [path];
  const entries = await readdir(path); const files = [];
  for (const entry of entries) files.push(...await filesUnder(join(path, entry)));
  return files;
}

test('repository artifacts contain no credentials, signed URLs, or developer machine paths', async () => {
  const files = (await Promise.all(scanRoots.map((name) => filesUnder(join(root, name))))).flat();
  const hits = [];
  for (const file of files) {
    const value = await readFile(file, 'utf8');
    for (const pattern of forbidden) if (pattern.test(value)) hits.push(`${file}: ${pattern}`);
  }
  assert.deepEqual(hits, []);
});
