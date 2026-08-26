import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { parseYamlRecordList, type YamlRecord } from "./yaml.js";

export interface Client {
  id: string;
  name: string;
  onboarded_on: string;
  advisory_type: string;
  ai_assisted: boolean;
  agreement_version: string;
  risk_profile_reviewed_on: string | null;
}

const REQUIRED_FIELDS = [
  "id",
  "name",
  "onboarded_on",
  "advisory_type",
  "ai_assisted",
  "agreement_version",
  "risk_profile_reviewed_on",
] as const;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const DEFAULT_CLIENTS_PATH = fileURLToPath(new URL("../../config/clients.yaml", import.meta.url));

export class ClientConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClientConfigError";
  }
}

function requireString(rec: YamlRecord, field: string, idForError: string): string {
  const f = rec.fields.get(field);
  if (f === undefined || typeof f.value !== "string" || f.value.trim() === "") {
    throw new ClientConfigError(`client "${idForError}": missing or empty required field "${field}"`);
  }
  return f.value;
}

function requireBoolean(rec: YamlRecord, field: string, idForError: string): boolean {
  const f = rec.fields.get(field);
  if (f === undefined || typeof f.value !== "boolean") {
    throw new ClientConfigError(
      `client "${idForError}": field "${field}" must be true or false (got ${JSON.stringify(f?.value)})`,
    );
  }
  return f.value;
}

function requireDate(rec: YamlRecord, field: string, idForError: string): string {
  const f = rec.fields.get(field);
  if (f === undefined || typeof f.value !== "string" || !DATE_RE.test(f.value)) {
    throw new ClientConfigError(
      `client "${idForError}": field "${field}" must be a YYYY-MM-DD date (got ${JSON.stringify(f?.value)})`,
    );
  }
  return f.value;
}

function requireDateOrNull(rec: YamlRecord, field: string, idForError: string): string | null {
  if (!rec.fields.has(field)) {
    throw new ClientConfigError(`client "${idForError}": missing required field "${field}"`);
  }
  const value = rec.fields.get(field)!.value;
  if (value === null) return null;
  if (typeof value !== "string" || !DATE_RE.test(value)) {
    throw new ClientConfigError(
      `client "${idForError}": field "${field}" must be a YYYY-MM-DD date or null (got ${JSON.stringify(value)})`,
    );
  }
  return value;
}

export function parseClients(text: string, filePath: string): Client[] {
  const records = parseYamlRecordList(text, "clients", filePath);
  const seenIds = new Set<string>();
  const result: Client[] = [];

  for (const rec of records) {
    const idField = rec.fields.get("id");
    const idForError = typeof idField?.value === "string" ? idField.value : `<line ${rec.line}>`;

    for (const key of rec.fields.keys()) {
      if (!(REQUIRED_FIELDS as readonly string[]).includes(key)) {
        throw new ClientConfigError(
          `client "${idForError}": unknown field "${key}" (line ${rec.fields.get(key)!.line})`,
        );
      }
    }
    for (const field of REQUIRED_FIELDS) {
      if (!rec.fields.has(field)) {
        throw new ClientConfigError(`client "${idForError}": missing required field "${field}"`);
      }
    }

    const id = requireString(rec, "id", idForError);
    if (seenIds.has(id)) {
      throw new ClientConfigError(`duplicate client id "${id}" (line ${rec.line})`);
    }
    seenIds.add(id);

    result.push({
      id,
      name: requireString(rec, "name", id),
      onboarded_on: requireDate(rec, "onboarded_on", id),
      advisory_type: requireString(rec, "advisory_type", id),
      ai_assisted: requireBoolean(rec, "ai_assisted", id),
      agreement_version: requireString(rec, "agreement_version", id),
      risk_profile_reviewed_on: requireDateOrNull(rec, "risk_profile_reviewed_on", id),
    });
  }

  if (result.length === 0) {
    throw new ClientConfigError(`no clients found in ${filePath}`);
  }

  return result;
}

export async function loadClients(filePath: string = DEFAULT_CLIENTS_PATH): Promise<Client[]> {
  let text: string;
  try {
    text = await readFile(filePath, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new ClientConfigError(`clients file not found: ${filePath}`);
    }
    throw err;
  }
  return parseClients(text, filePath);
}
