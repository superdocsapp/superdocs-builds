/** @vitest-environment happy-dom */
import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { SchemaForm } from "../src/client/SchemaForm.js";
import { createDraft } from "../src/shared/schema.js";
import type { Draft } from "../src/shared/schema.js";
import type { JsonSchema } from "../src/shared/types.js";

function Harness({ schema }: { schema: JsonSchema }) {
  const [draft, setDraft] = useState<Draft>(() => createDraft(schema));
  return <SchemaForm schema={schema} draft={draft} onChange={setDraft} errors={[{ path: "/field_qz", message: "field_qz is required" }]} />;
}

describe("schema form rendering", () => {
  it("renders controls from the schema and picks up a newly added field", () => {
    const schema: JsonSchema = {
      type: "object",
      required: ["field_qz"],
      properties: {
        field_qz: { type: "string", description: "A discovered field" },
        nested_block: {
          type: "object",
          properties: { inner_city: { type: "string" } },
        },
        item_list: { type: "array", items: { type: "string" } },
      },
    };
    const view = render(<Harness schema={schema} />);
    expect(screen.getByLabelText(/field_qz/)).toBeTruthy();
    expect(screen.getByText("field_qz is required")).toBeTruthy();
    expect(screen.getByText("inner_city")).toBeTruthy();
    view.rerender(
      <Harness
        schema={{
          ...schema,
          properties: {
            ...schema.properties,
            another_field: { type: "integer" },
          },
        }}
      />,
    );
    expect(screen.getByLabelText(/another_field/)).toBeTruthy();
  });
});
