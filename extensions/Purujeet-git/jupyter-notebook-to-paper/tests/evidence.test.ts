import { describe, expect, it } from "vitest";
import { makeEvidence } from "../src/evidence.js";

describe("Evidence", () => {
  it("creates stable fingerprints for identical evidence", () => {
    const input = {
      id: "metric:model_b_accuracy",
      kind: "metric" as const,
      source: {
        notebook: "synthetic_research.ipynb",
        cellId: "metrics",
        cellIndex: 1,
      },
      label: "Model B accuracy",
      value: 0.881,
    };

    const a = makeEvidence(input);
    const b = makeEvidence(input);

    expect(a.fingerprint).toBe(b.fingerprint);
    expect(a.fingerprint).toHaveLength(64);
  });
});
