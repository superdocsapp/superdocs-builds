import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { parseYamlRecordList, type YamlRecord } from "./yaml.js";

export type RequirementFrequency = "continuous" | "annual" | "on_change" | "on_onboarding";
export type RequirementScope = "all_clients" | "firm" | "advisory_clients";

export interface Requirement {
  id: string;
  citation: string;
  title: string;
  obligation: string;
  evidence_expected: string[];
  frequency: RequirementFrequency;
  applies_to: RequirementScope;
}

const REQUIRED_FIELDS = [
  "id",
  "citation",
  "title",
  "obligation",
  "evidence_expected",
  "frequency",
  "applies_to",
] as const;

const FREQUENCIES: readonly RequirementFrequency[] = [
  "continuous",
  "annual",
  "on_change",
  "on_onboarding",
];

const SCOPES: readonly RequirementScope[] = ["all_clients", "firm", "advisory_clients"];

export const DEFAULT_REQUIREMENTS_PATH = fileURLToPath(
  new URL("../../config/requirements.yaml", import.meta.url),
);

export class RequirementConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RequirementConfigError";
  }
}

function requireString(rec: YamlRecord, field: string, idForError: string): string {
  const f = rec.fields.get(field);
  if (f === undefined || typeof f.value !== "string" || f.value.trim() === "") {
    throw new RequirementConfigError(
      `requirement "${idForError}": missing or empty required field "${field}"`,
    );
  }
  return f.value;
}

function requireStringArray(rec: YamlRecord, field: string, idForError: string): string[] {
  const f = rec.fields.get(field);
  if (f === undefined || !Array.isArray(f.value) || f.value.length === 0) {
    throw new RequirementConfigError(
      `requirement "${idForError}": missing or empty required list field "${field}"`,
    );
  }
  return f.value;
}

function requireEnum<T extends string>(
  rec: YamlRecord,
  field: string,
  allowed: readonly T[],
  idForError: string,
): T {
  const raw = rec.fields.get(field)?.value;
  if (typeof raw !== "string" || !allowed.includes(raw as T)) {
    throw new RequirementConfigError(
      `requirement "${idForError}": field "${field}" must be one of ${allowed.join(", ")} (got ${JSON.stringify(raw)})`,
    );
  }
  return raw as T;
}

export function parseRequirements(text: string, filePath: string): Requirement[] {
  const records = parseYamlRecordList(text, "requirements", filePath);
  const seenIds = new Set<string>();
  const result: Requirement[] = [];

  for (const rec of records) {
    const idField = rec.fields.get("id");
    const idForError = typeof idField?.value === "string" ? idField.value : `<line ${rec.line}>`;

    for (const key of rec.fields.keys()) {
      if (!(REQUIRED_FIELDS as readonly string[]).includes(key)) {
        throw new RequirementConfigError(
          `requirement "${idForError}": unknown field "${key}" (line ${rec.fields.get(key)!.line})`,
        );
      }
    }
    for (const field of REQUIRED_FIELDS) {
      if (!rec.fields.has(field)) {
        throw new RequirementConfigError(
          `requirement "${idForError}": missing required field "${field}"`,
        );
      }
    }

    const id = requireString(rec, "id", idForError);
    if (seenIds.has(id)) {
      throw new RequirementConfigError(`duplicate requirement id "${id}" (line ${rec.line})`);
    }
    seenIds.add(id);

    result.push({
      id,
      citation: requireString(rec, "citation", id),
      title: requireString(rec, "title", id),
      obligation: requireString(rec, "obligation", id),
      evidence_expected: requireStringArray(rec, "evidence_expected", id),
      frequency: requireEnum(rec, "frequency", FREQUENCIES, id),
      applies_to: requireEnum(rec, "applies_to", SCOPES, id),
    });
  }

  if (result.length === 0) {
    throw new RequirementConfigError(`no requirements found in ${filePath}`);
  }

  return result;
}

export async function loadRequirements(
  filePath: string = DEFAULT_REQUIREMENTS_PATH,
): Promise<Requirement[]> {
  let text: string;
  try {
    text = await readFile(filePath, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new RequirementConfigError(`requirements file not found: ${filePath}`);
    }
    throw err;
  }
  return parseRequirements(text, filePath);
}
