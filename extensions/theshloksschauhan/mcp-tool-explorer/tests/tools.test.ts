import { describe, expect, it } from "vitest";
import { filterTools } from "../src/shared/tools.js";

describe("dynamic tool handling", () => {
  it("filters whatever tools the server returned", () => {
    const first = [
      { name: "alpha_tool", description: "Writes a memo" },
      { name: "beta_tool", description: "Reads a ledger" },
    ];
    expect(filterTools(first, "ledger").map((tool) => tool.name)).toEqual(["beta_tool"]);
    const withNewTool = [...first, { name: "gamma_tool", description: "Archives a binder" }];
    expect(filterTools(withNewTool, "").map((tool) => tool.name)).toEqual(["alpha_tool", "beta_tool", "gamma_tool"]);
    expect(filterTools(withNewTool, "archive").map((tool) => tool.name)).toEqual(["gamma_tool"]);
  });
});
