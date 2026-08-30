import { describe, expect, it } from "vitest";
import { summarizeChange, sortChangesByRecency } from "../../domain/changes";
import type { ChangeEvent } from "../../types/domain";
import { ironcladMsa } from "../../data/documents/ironcladMsa";

function change(overrides: Partial<ChangeEvent>): ChangeEvent {
  return {
    id: "change-x",
    documentId: "doc-x",
    fromVersion: "1.0",
    toVersion: "1.1",
    occurredAt: "2026-01-01T00:00:00.000Z",
    author: "Someone",
    summary: "test change",
    textChangeCount: 0,
    claimChangeIds: [],
    requirementChangeIds: [],
    evidenceChangeIds: [],
    riskDelta: 0,
    highlights: [],
    ...overrides,
  };
}

describe("summarizeChange", () => {
  it("omits lines for zero-count fields and says nothing about risk when the delta is zero", () => {
    const lines = summarizeChange(change({}));
    expect(lines).toEqual([]);
  });

  it("pluralizes correctly and marks a risk increase as a warning", () => {
    const lines = summarizeChange(change({ textChangeCount: 1, claimChangeIds: ["c1", "c2"], riskDelta: 1 }));
    expect(lines).toEqual([
      { label: "1 text change", tone: "neutral" },
      { label: "2 claim changes", tone: "neutral" },
      { label: "1 risk increased", tone: "warning" },
    ]);
  });

  it("marks a risk decrease as positive", () => {
    const lines = summarizeChange(change({ riskDelta: -2 }));
    expect(lines).toEqual([{ label: "2 risks resolved", tone: "positive" }]);
  });

  it("reproduces the flagship document's v3.1 → v3.2 change summary", () => {
    const latest = [...ironcladMsa.changes].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime())[0]!;
    const lines = summarizeChange(latest);
    expect(lines.map((l) => l.label)).toEqual([
      "12 text changes",
      "2 claim changes",
      "1 requirement affected",
      "1 evidence relationship changed",
      "1 risk increased",
    ]);
  });
});

describe("sortChangesByRecency", () => {
  it("orders the flagship document's changes newest first", () => {
    const sorted = sortChangesByRecency(ironcladMsa.changes);
    expect(sorted.map((c) => c.toVersion)).toEqual(["3.2", "3.1"]);
  });
});
