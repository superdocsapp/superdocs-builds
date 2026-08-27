import { chmod, mkdir, open, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { dirname, join, basename } from 'node:path';

export async function ensurePrivateDir(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  await chmod(path, 0o700);
}

export async function atomicWrite(path, data, { mode = 0o600, overwrite = true, failBeforeRename = false } = {}) {
  await ensurePrivateDir(dirname(path));
  if (!overwrite) {
    try {
      await stat(path);
      throw new Error(`output already exists: ${basename(path)}`);
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomBytes(5).toString('hex')}.tmp`);
  try {
    const handle = await open(temporary, 'wx', mode);
    try {
      await handle.writeFile(data);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await chmod(temporary, mode);
    if (failBeforeRename) throw new Error('injected atomic rename failure');
    await rename(temporary, path);
    await chmod(path, mode);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
}

export async function readJson(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}
