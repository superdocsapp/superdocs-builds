import { describe, expect, it } from "vitest";
import { createDraft, describeSchema, submissionFromDraft, validateToolArguments, type Draft } from "../src/shared/schema.js";
import type { JsonSchema } from "../src/shared/types.js";

const nested: JsonSchema = {
  type: "object",
  required: ["address", "count", "active", "tags"],
  properties: {
    title: { type: "string", description: "Optional title" },
    count: { type: "integer", minimum: 1 },
    ratio: { type: "number" },
    active: { type: "boolean" },
    kind: { type: "string", enum: ["docx", "pdf"] },
    note: { anyOf: [{ type: "string" }, { type: "null" }] },
    tags: { type: "array", items: { type: "string" } },
    address: {
      type: "object",
      required: ["city"],
      properties: {
        city: { type: "string" },
        visits: { type: "array", items: { type: "integer" } },
      },
    },
  },
};

function withDraft(schema: JsonSchema, mutate: (draft: Draft) => void): Draft {
  const draft = createDraft(schema);
  mutate(draft);
  return draft;
}

describe("schema-driven forms", () => {
  it("describes strings, numbers, booleans, enums, arrays, and nested objects from the schema", () => {
    const node = describeSchema(nested);
    expect(node.kind).toBe("object");
    if (node.kind !== "object") return;
    const names = node.fields.map((field) => field.name);
    expect(names).toEqual(["title", "count", "ratio", "active", "kind", "note", "tags", "address"]);
    const address = node.fields.find((field) => field.name === "address");
    expect(address?.required).toBe(true);
    expect(address?.node.kind).toBe("object");
    const tags = node.fields.find((field) => field.name === "tags");
    expect(tags?.node.kind).toBe("array");
    const kind = node.fields.find((field) => field.name === "kind");
    expect(kind?.node.kind).toBe("string");
    if (kind?.node.kind === "string") expect(kind.node.enumValues).toEqual(["docx", "pdf"]);
    const note = node.fields.find((field) => field.name === "note");
    if (note?.node.kind === "string") expect(note.node.nullable).toBe(true);
  });

  it("rejects a missing required field with a readable message", () => {
    const result = submissionFromDraft(nested, createDraft(nested));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.map((error) => error.message)).toContain("city is required");
    expect(result.errors.map((error) => error.message)).toContain("count is required");
  });

  it("accepts nested objects and arrays and rejects a non-integer", () => {
    const draft = withDraft(nested, (value) => {
      if (value.kind !== "object") return;
      const count = value.values.count;
      const active = value.values.active;
      const kind = value.values.kind;
      const tags = value.values.tags;
      const address = value.values.address;
      if (count?.kind === "number") count.value = "2";
      if (active?.kind === "boolean") active.value = true;
      if (kind?.kind === "string") kind.value = "pdf";
      if (tags?.kind === "array") tags.items = [{ kind: "string", value: "alpha", useNull: false }];
      if (address?.kind === "object") {
        const city = address.values.city;
        const visits = address.values.visits;
        if (city?.kind === "string") city.value = "Pune";
        if (visits?.kind === "array") visits.items = [{ kind: "number", value: "1.5", useNull: false }];
      }
    });
    const invalid = submissionFromDraft(nested, draft);
    expect(invalid.ok).toBe(false);
    if (!invalid.ok) {
      expect(invalid.errors.some((error) => error.path === "/address/visits/0" && /integer/.test(error.message))).toBe(true);
    }

    if (draft.kind === "object") {
      const address = draft.values.address;
      if (address?.kind === "object" && address.values.visits?.kind === "array") {
        address.values.visits.items = [{ kind: "number", value: "4", useNull: false }];
      }
    }
    const valid = submissionFromDraft(nested, draft);
    expect(valid.ok).toBe(true);
    if (valid.ok) {
      expect(valid.value).toMatchObject({
        count: 2,
        active: true,
        kind: "pdf",
        tags: ["alpha"],
        address: { city: "Pune", visits: [4] },
      });
      expect(valid.value.title).toBeUndefined();
    }
  });

  it("allows null only where the schema is nullable", () => {
    const schema: JsonSchema = {
      type: "object",
      properties: { note: { anyOf: [{ type: "string" }, { type: "null" }] } },
    };
    const draft = createDraft(schema);
    if (draft.kind === "object" && draft.values.note?.kind === "string") draft.values.note.useNull = true;
    const result = submissionFromDraft(schema, draft);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.note).toBeNull();
  });

  it("validates server-side payloads against the schema itself", () => {
    const schema: JsonSchema = {
      type: "object",
      required: ["city"],
      properties: { city: { type: "string" } },
    };
    const missing = validateToolArguments(schema, {});
    expect(missing.ok).toBe(false);
    if (!missing.ok) expect(missing.errors[0]?.message).toBe("city is required");
    expect(validateToolArguments(schema, { city: "Pune" }).ok).toBe(true);
  });

  it("uses schema defaults for generated drafts", () => {
    const schema: JsonSchema = {
      type: "object",
      required: ["format"],
      properties: { format: { type: "string", enum: ["docx", "pdf"], default: "docx" } },
    };
    const draft = createDraft(schema);
    const result = submissionFromDraft(schema, draft);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.format).toBe("docx");
  });
});
