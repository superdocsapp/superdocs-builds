import { describe, expect, it } from "vitest";
import { loadSource } from "./load-source";

const { renderTemplate } = loadSource<{ renderTemplate: (template: string, data: Record<string, unknown>) => string }>(
  "renderer.ts",
  ["renderTemplate"]
);

describe("template semantics", () => {
  it("documents the supported placeholder and conditional contract", () => {
    const template = "Hello {{Name}}{{#if Remote}} — Remote{{/if}}";
    expect(template).toContain("{{Name}}");
    expect(template).toContain("{{#if Remote}}");
  });

  it("fills names and escapes HTML-sensitive values", () => {
    expect(renderTemplate("Dear {{Name}}", { Name: "A <B> & Co. \"HR\"" }))
      .toBe("Dear A &lt;B&gt; &amp; Co. &quot;HR&quot;");
  });

  it("renders missing names as blank instead of the text undefined", () => {
    expect(renderTemplate("Dear {{Name}}", {})).toBe("Dear ");
    expect(renderTemplate("Dear {Name}", { Name: null })).toBe("Dear ");
  });

  it("supports both brace syntaxes and trims placeholder whitespace", () => {
    expect(renderTemplate("{{ Name }} / { Job Profile }", {
      Name: " Priya ",
      "Job Profile": "Software Engineer"
    })).toBe(" Priya  / Software Engineer");
  });

  it("handles conditional sections for blank, false, zero, and truthy values", () => {
    const template = "A{{#if Remote}}-remote{{/if}}B{{#if Salary > 50000}}-senior{{/if}}";
    expect(renderTemplate(template, { Remote: "", Salary: 60000 })).toBe("AB-senior");
    expect(renderTemplate(template, { Remote: false, Salary: 50000 })).toBe("AB");
    expect(renderTemplate(template, { Remote: true, Salary: "60000" })).toBe("A-remoteB-senior");
  });

  it("does not allow an unmatched conditional to leak placeholder markup", () => {
    expect(renderTemplate("{{#if Remote}}Remote: {{Name}}{{/if}}", { Remote: false, Name: "Asha" }))
      .toBe("");
  });
});
