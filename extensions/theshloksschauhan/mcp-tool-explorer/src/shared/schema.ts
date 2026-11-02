import Ajv, { type ErrorObject } from "ajv";
import type { FieldError, JsonSchema } from "./types.js";

const ajv = new Ajv({
  allErrors: true,
  strict: false,
  validateSchema: false,
});

const compiled = new Map<string, ReturnType<Ajv["compile"]>>();

export type FormNode =
  | {
      kind: "object";
      description?: string;
      fields: FormField[];
    }
  | {
      kind: "array";
      description?: string;
      items: FormNode;
    }
  | {
      kind: "string";
      description?: string;
      enumValues?: unknown[];
      nullable: boolean;
      minLength?: number;
      maxLength?: number;
      defaultValue?: unknown;
    }
  | {
      kind: "number";
      description?: string;
      integer: boolean;
      enumValues?: unknown[];
      nullable: boolean;
      minimum?: number;
      maximum?: number;
      defaultValue?: unknown;
    }
  | {
      kind: "boolean";
      description?: string;
      nullable: boolean;
      defaultValue?: unknown;
    }
  | {
      kind: "json";
      description?: string;
      nullable: boolean;
    };

export type FormField = {
  name: string;
  required: boolean;
  description?: string;
  node: FormNode;
};

export type Draft =
  | { kind: "object"; values: Record<string, Draft> }
  | { kind: "array"; items: Draft[] }
  | { kind: "string"; value: string; useNull: boolean }
  | { kind: "number"; value: string; useNull: boolean }
  | { kind: "boolean"; value: boolean | "unset"; useNull: boolean }
  | { kind: "json"; text: string; useNull: boolean };

type Built = {
  omit: boolean;
  value: unknown;
  errors: FieldError[];
};

function isNullSchema(schema: JsonSchema | undefined): boolean {
  return Boolean(schema && (schema.type === "null" || schema.const === null));
}

function unwrapNullable(schema: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  const union = schema.anyOf ?? schema.oneOf;
  if (union && union.length > 0) {
    const nonNull = union.filter((entry) => !isNullSchema(entry));
    const nullable = union.some((entry) => isNullSchema(entry));
    if (nullable && nonNull.length === 1) {
      const { anyOf: _any, oneOf: _one, ...rest } = schema;
      return { schema: { ...rest, ...nonNull[0] }, nullable: true };
    }
  }
  if (Array.isArray(schema.type)) {
    const types = schema.type.filter((entry) => entry !== "null");
    const nullable = schema.type.includes("null") || schema.nullable === true;
    if (types.length === 1) return { schema: { ...schema, type: types[0] }, nullable };
    if (types.length === 0 && nullable) return { schema, nullable: true };
  }
  return { schema, nullable: schema.nullable === true };
}

function descriptionOf(schema: JsonSchema): string | undefined {
  return typeof schema.description === "string" ? schema.description : undefined;
}

export function describeSchema(schema: JsonSchema | undefined): FormNode {
  const source = schema ?? { type: "object", properties: {} };
  const { schema: unwrapped, nullable } = unwrapNullable(source);
  if (unwrapped.enum && unwrapped.enum.length > 0 && (unwrapped.type === "string" || unwrapped.type === undefined)) {
    return {
      kind: "string",
      description: descriptionOf(unwrapped),
      enumValues: unwrapped.enum,
      nullable,
      defaultValue: unwrapped.default,
    };
  }
  if (unwrapped.const !== undefined && (typeof unwrapped.const === "string" || unwrapped.type === "string")) {
    return {
      kind: "string",
      description: descriptionOf(unwrapped),
      enumValues: [unwrapped.const],
      nullable,
      defaultValue: unwrapped.default ?? unwrapped.const,
    };
  }
  const type = Array.isArray(unwrapped.type) ? unwrapped.type[0] : unwrapped.type;
  if ((type === "object" || (type === undefined && unwrapped.properties)) && unwrapped.properties) {
    const required = new Set(unwrapped.required ?? []);
    const fields = Object.entries(unwrapped.properties).map(([name, property]) => ({
      name,
      required: required.has(name),
      description: descriptionOf(property),
      node: describeSchema(property),
    }));
    return { kind: "object", description: descriptionOf(unwrapped), fields };
  }
  if (type === "array" && unwrapped.items && !Array.isArray(unwrapped.items)) {
    return {
      kind: "array",
      description: descriptionOf(unwrapped),
      items: describeSchema(unwrapped.items),
    };
  }
  if (type === "integer" || type === "number") {
    return {
      kind: "number",
      description: descriptionOf(unwrapped),
      integer: type === "integer",
      enumValues: unwrapped.enum,
      nullable,
      minimum: typeof unwrapped.minimum === "number" ? unwrapped.minimum : undefined,
      maximum: typeof unwrapped.maximum === "number" ? unwrapped.maximum : undefined,
      defaultValue: unwrapped.default,
    };
  }
  if (type === "boolean") {
    return {
      kind: "boolean",
      description: descriptionOf(unwrapped),
      nullable,
      defaultValue: unwrapped.default,
    };
  }
  if (type === "string" || type === undefined) {
    if (type === undefined && (unwrapped.anyOf || unwrapped.oneOf || unwrapped.properties || unwrapped.items)) {
      return { kind: "json", description: descriptionOf(unwrapped), nullable };
    }
    return {
      kind: "string",
      description: descriptionOf(unwrapped),
      nullable,
      minLength: typeof unwrapped.minLength === "number" ? unwrapped.minLength : undefined,
      maxLength: typeof unwrapped.maxLength === "number" ? unwrapped.maxLength : undefined,
      defaultValue: unwrapped.default,
    };
  }
  return { kind: "json", description: descriptionOf(unwrapped), nullable };
}

function stringDefault(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function blankDraft(node: FormNode, required = false): Draft {
  switch (node.kind) {
    case "object": {
      const values: Record<string, Draft> = {};
      for (const field of node.fields) values[field.name] = blankDraft(field.node, field.required);
      return { kind: "object", values };
    }
    case "array":
      return { kind: "array", items: [] };
    case "string":
      return { kind: "string", value: stringDefault(node.defaultValue), useNull: false };
    case "number":
      return {
        kind: "number",
        value: typeof node.defaultValue === "number" ? String(node.defaultValue) : "",
        useNull: false,
      };
    case "boolean": {
      if (typeof node.defaultValue === "boolean") {
        return { kind: "boolean", value: node.defaultValue, useNull: false };
      }
      return { kind: "boolean", value: required ? false : "unset", useNull: false };
    }
    case "json":
      return { kind: "json", text: "", useNull: false };
  }
}

export function createDraft(schema: JsonSchema | undefined): Draft {
  const node = describeSchema(schema);
  return blankDraft(node, true);
}

function label(path: string, fallback: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? fallback;
}

function valueFromDraft(node: FormNode, draft: Draft, path: string): Built {
  if (draft.kind !== node.kind) {
    return { omit: false, value: undefined, errors: [{ path: path || "/", message: "This value does not match the schema." }] };
  }
  if ((draft.kind === "string" || draft.kind === "number" || draft.kind === "boolean" || draft.kind === "json") && draft.useNull) {
    return { omit: false, value: null, errors: [] };
  }
  switch (node.kind) {
    case "object": {
      if (draft.kind !== "object") break;
      const value: Record<string, unknown> = {};
      const errors: FieldError[] = [];
      for (const field of node.fields) {
        const childPath = `${path}/${field.name}`;
        const child = draft.values[field.name] ?? blankDraft(field.node, field.required);
        const built = valueFromDraft(field.node, child, childPath);
        if (built.errors.length > 0) {
          errors.push(...built.errors);
          continue;
        }
        if (built.omit) {
          if (field.required && field.node.kind !== "array") {
            errors.push({ path: childPath, message: `${field.name} is required` });
          } else if (field.required && field.node.kind === "array") {
            value[field.name] = [];
          }
          continue;
        }
        value[field.name] = built.value;
      }
      return { omit: false, value, errors };
    }
    case "array": {
      if (draft.kind !== "array") break;
      if (draft.items.length === 0) return { omit: true, value: [], errors: [] };
      const items: unknown[] = [];
      const errors: FieldError[] = [];
      draft.items.forEach((item, index) => {
        const built = valueFromDraft(node.items, item, `${path}/${index}`);
        if (built.errors.length > 0) errors.push(...built.errors);
        else if (built.omit) errors.push({ path: `${path}/${index}`, message: `Item ${index + 1} is required` });
        else items.push(built.value);
      });
      return { omit: false, value: items, errors };
    }
    case "string": {
      if (draft.kind !== "string") break;
      if (draft.value === "") return { omit: true, value: undefined, errors: [] };
      return { omit: false, value: draft.value, errors: [] };
    }
    case "number": {
      if (draft.kind !== "number") break;
      if (draft.value.trim() === "") return { omit: true, value: undefined, errors: [] };
      const numeric = Number(draft.value);
      if (!Number.isFinite(numeric)) {
        return { omit: false, value: undefined, errors: [{ path: path || "/", message: `${label(path, "Value")} must be a number` }] };
      }
      if (node.integer && !Number.isInteger(numeric)) {
        return { omit: false, value: undefined, errors: [{ path: path || "/", message: `${label(path, "Value")} must be an integer` }] };
      }
      return { omit: false, value: numeric, errors: [] };
    }
    case "boolean": {
      if (draft.kind !== "boolean") break;
      if (draft.value === "unset") return { omit: true, value: undefined, errors: [] };
      return { omit: false, value: draft.value, errors: [] };
    }
    case "json": {
      if (draft.kind !== "json") break;
      if (draft.text.trim() === "") return { omit: true, value: undefined, errors: [] };
      try {
        return { omit: false, value: JSON.parse(draft.text) as unknown, errors: [] };
      } catch {
        return { omit: false, value: undefined, errors: [{ path: path || "/", message: `${label(path, "Value")} must be valid JSON` }] };
      }
    }
  }
  return { omit: false, value: undefined, errors: [{ path: path || "/", message: "This value does not match the schema." }] };
}

function formatAjvError(error: ErrorObject): FieldError {
  const missing = error.keyword === "required" ? String(error.params.missingProperty ?? "") : "";
  const base = error.instancePath || "";
  const path = missing ? `${base}/${missing}` : base || "/";
  const name = label(path, "Value");
  if (error.keyword === "required") return { path, message: `${missing} is required` };
  if (error.keyword === "type") return { path, message: `${name} must be a ${String(error.params.type)}` };
  if (error.keyword === "enum") {
    const allowed = Array.isArray(error.params.allowedValues) ? error.params.allowedValues.map(String).join(", ") : "";
    return { path, message: `${name} must be one of: ${allowed}` };
  }
  if (error.keyword === "minimum" || error.keyword === "maximum") {
    return { path, message: `${name} ${error.message ?? "is out of range"}` };
  }
  if (error.keyword === "minLength" || error.keyword === "maxLength") {
    return { path, message: `${name} ${error.message ?? "has an invalid length"}` };
  }
  if (error.keyword === "minItems" || error.keyword === "maxItems") {
    return { path, message: `${name} ${error.message ?? "has an invalid number of items"}` };
  }
  return { path, message: `${name} ${error.message ?? "is invalid"}` };
}

export function validateToolArguments(
  schema: JsonSchema | undefined,
  data: unknown,
): { ok: true; data: Record<string, unknown> } | { ok: false; errors: FieldError[] } {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, errors: [{ path: "/", message: "Tool arguments must be an object." }] };
  }
  const inputSchema = schema && typeof schema === "object" ? schema : { type: "object", properties: {} };
  const key = JSON.stringify(inputSchema);
  let validate = compiled.get(key);
  if (!validate) {
    try {
      validate = ajv.compile(inputSchema);
    } catch {
      return {
        ok: false,
        errors: [{ path: "/", message: "This tool's input schema could not be used for validation." }],
      };
    }
    if (compiled.size > 200) compiled.clear();
    compiled.set(key, validate);
  }
  const valid = validate(data);
  if (!valid) {
    return { ok: false, errors: (validate.errors ?? []).map(formatAjvError) };
  }
  return { ok: true, data: data as Record<string, unknown> };
}

export function submissionFromDraft(
  schema: JsonSchema | undefined,
  draft: Draft,
): { ok: true; value: Record<string, unknown> } | { ok: false; errors: FieldError[] } {
  const node = describeSchema(schema);
  const built = valueFromDraft(node, draft, "");
  if (built.errors.length > 0) return { ok: false, errors: built.errors };
  const validated = validateToolArguments(schema, built.value);
  if (!validated.ok) return validated;
  return { ok: true, value: validated.data };
}
