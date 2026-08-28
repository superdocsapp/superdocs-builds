import * as vscode from "vscode";

const SECRET_KEY = "latexBridge.apiKey";

let secretStorage: vscode.SecretStorage | undefined;
let cachedKey: string | undefined;

export function initKeyStorage(storage: vscode.SecretStorage): void {
  secretStorage = storage;
}

export async function getKey(): Promise<string | undefined> {
  if (cachedKey !== undefined) return cachedKey;
  if (!secretStorage) return undefined;
  cachedKey = (await secretStorage.get(SECRET_KEY)) || undefined;
  return cachedKey;
}

export async function setKey(key: string): Promise<void> {
  if (!secretStorage) return;
  await secretStorage.store(SECRET_KEY, key);
  cachedKey = key;
}

export async function clearKey(): Promise<void> {
  if (!secretStorage) return;
  await secretStorage.delete(SECRET_KEY);
  cachedKey = undefined;
}
