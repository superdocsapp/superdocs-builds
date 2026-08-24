import { describe, expect, it } from "vitest";

import { createSuperDocsBlockNoteExtension } from "../src/blocknote/index.js";

describe("SuperDocs BlockNote extension", () => {
  it("creates a BlockNote extension factory", () => {
    const client = {
      edit: async () => ({
        changes: [],
      }),
    };

    const extension = createSuperDocsBlockNoteExtension({
      client,
      sessionId: "test-session",
    });

    expect(extension).toBeDefined();
    expect(typeof extension).toBe("function");
  });
});