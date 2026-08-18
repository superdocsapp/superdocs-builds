import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Loads a local .env file without adding a runtime dependency. Existing process.env wins. */
export function loadLocalEnv(cwd = process.cwd()): void {
  const path = resolve(cwd, ".env");
  if (!existsSync(path)) return;
  const text = readFileSync(path, "utf8");
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    const key = match[1]!;
    let value = match[2]!.trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    const placeholder = /^(?:your[-_ ]?key(?:[-_ ]?here)?|your[-_ ]?api[-_ ]?key(?:[-_ ]?here)?|replace[-_ ]?me|changeme)$/i.test(value);
    if (placeholder) value = "";
    if (!(key in process.env)) process.env[key] = value;
  }
}
