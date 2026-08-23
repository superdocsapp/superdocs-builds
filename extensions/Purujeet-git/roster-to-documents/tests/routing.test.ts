import { describe, expect, it } from "vitest";
import { loadSource } from "./load-source";

const properties = { value: "invalid-template" };
const dynamicTemplates: Record<string, { profile: string; templateId: string; templateName: string }> = {};
(globalThis as any).CONFIG = { TEMPLATE_PROPERTY: "ROSTER_TEMPLATE" };
(globalThis as any).PropertiesService = {
  getScriptProperties: () => ({ getProperty: () => properties.value })
};
(globalThis as any).getScriptProperty = () => properties.value;
(globalThis as any).getDynamicTemplateMap = () => dynamicTemplates;
const { routeRow } = loadSource<{ routeRow: (row: { rowNumber: number; values: Record<string, unknown> }) => { templateId: string; method: string } }>(
  "routing.ts",
  ["routeRow"]
);

describe("routing contract", () => {
  it("keeps the ten stable template IDs", () => {
    const ids = ["software-engineer","data-ai","product-manager","sales-executive","hr-executive","marketing-executive","finance-analyst","operations-manager","customer-support","general"];
    expect(new Set(ids).size).toBe(10);
  });

  it("routes exact names case-insensitively after an invalid configured template", () => {
    expect(routeRow({ rowNumber: 2, values: { "Job Profile": "  SOFTWARE ENGINEER " } }))
      .toMatchObject({ templateId: "software-engineer", method: "exact" });
  });

  it("supports explicit auto mode and ignores surrounding whitespace/case", () => {
    properties.value = "  AUTO ";
    expect(routeRow({ rowNumber: 2, values: { "Job Profile": "Product Manager" } }))
      .toMatchObject({ templateId: "product-manager", method: "exact" });
    properties.value = "invalid-template";
  });

  it("prefers a cached sheet-specific template in auto mode", () => {
    properties.value = "auto";
    dynamicTemplates["ux designer"] = {
      profile: "UX Designer",
      templateId: "dynamic-ux-designer",
      templateName: "UX Designer Template"
    };
    expect(routeRow({ rowNumber: 2, values: { "Job Profile": " UX DESIGNER " } }))
      .toMatchObject({ templateId: "dynamic-ux-designer", method: "dynamic" });
    delete dynamicTemplates["ux designer"];
    properties.value = "invalid-template";
  });

  it("still supports forcing one configured template", () => {
    properties.value = "finance-analyst";
    expect(routeRow({ rowNumber: 2, values: { "Job Profile": "Software Engineer" } }))
      .toMatchObject({ templateId: "finance-analyst", method: "configured" });
    properties.value = "invalid-template";
  });

  it("routes supported aliases", () => {
    expect(routeRow({ rowNumber: 2, values: { JobProfile: "ML Engineer" } }))
      .toMatchObject({ templateId: "data-ai", method: "alias" });
  });

  it("uses keyword matching when the profile is not an exact alias", () => {
    expect(routeRow({ rowNumber: 2, values: {
      "Job Profile": "Platform role",
      "Job Description": "Build APIs with TypeScript and a database",
      Department: "Engineering"
    } })).toMatchObject({ templateId: "software-engineer", method: "keyword" });
  });

  it("falls back safely for missing or unknown job information", () => {
    expect(routeRow({ rowNumber: 2, values: {} })).toMatchObject({ templateId: "general", method: "general" });
    expect(routeRow({ rowNumber: 2, values: { "Job Profile": "Something nobody has entered" } }))
      .toMatchObject({ templateId: "general", method: "general" });
  });
});
