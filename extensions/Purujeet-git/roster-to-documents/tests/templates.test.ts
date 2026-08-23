import { describe, expect, it, beforeEach } from "vitest";
import { loadSource } from "./load-source";

let fileContents: Record<string, string>;
let driveReads: Record<string, number>;

const properties = { templateFolderId: "template-folder" };

(globalThis as any).CONFIG = {
  TEMPLATE_FOLDER_PROPERTY: "TEMPLATE_FOLDER_ID"
};
(globalThis as any).getScriptProperty = (key: string) =>
  key === "TEMPLATE_FOLDER_ID" ? properties.templateFolderId : "";
(globalThis as any).getTemplateDefinitions = () => [
  { id: "software-engineer", name: "Software Engineer" }
];
(globalThis as any).DriveApp = {
  getFolderById: () => ({
    getFilesByName: (name: string) => {
      driveReads[name] = (driveReads[name] || 0) + 1;
      const content = fileContents[name];
      let consumed = false;
      return {
        hasNext: () => !consumed && content !== undefined,
        next: () => {
          consumed = true;
          return { getBlob: () => ({ getDataAsString: () => content }) };
        }
      };
    }
  })
};

const { getTemplateBody, clearTemplateCache } = loadSource<{
  getTemplateBody: (templateId: string) => string;
  clearTemplateCache: () => void;
}>("templates.ts", ["getTemplateBody", "clearTemplateCache"]);

describe("template cache", () => {
  beforeEach(() => {
    fileContents = {
      "software-engineer.html": "<h1>first</h1>",
      "product-manager.html": "<h1>product</h1>"
    };
    driveReads = {};
    clearTemplateCache();
  });

  it("reads a template from Drive once and serves subsequent reads from memory", () => {
    expect(getTemplateBody("software-engineer")).toBe("<h1>first</h1>");

    fileContents["software-engineer.html"] = "<h1>changed in Drive</h1>";
    expect(getTemplateBody("software-engineer")).toBe("<h1>first</h1>");
    expect(driveReads["software-engineer.html"]).toBe(1);
  });

  it("clears cached templates so a new job can observe updated Drive content", () => {
    expect(getTemplateBody("software-engineer")).toBe("<h1>first</h1>");
    fileContents["software-engineer.html"] = "<h1>new version</h1>";

    clearTemplateCache();

    expect(getTemplateBody("software-engineer")).toBe("<h1>new version</h1>");
    expect(driveReads["software-engineer.html"]).toBe(2);
  });

  it("keeps separate cache entries for different template IDs", () => {
    expect(getTemplateBody("software-engineer")).toBe("<h1>first</h1>");
    expect(getTemplateBody("product-manager")).toBe("<h1>product</h1>");
    expect(getTemplateBody("software-engineer")).toBe("<h1>first</h1>");

    expect(driveReads).toEqual({
      "software-engineer.html": 1,
      "product-manager.html": 1
    });
  });
});
