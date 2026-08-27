import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

export async function hashFile(path) {
  return sha256(await readFile(path));
}

export function stableJson(value) {
  return JSON.stringify(value, Object.keys(value).sort());
}
