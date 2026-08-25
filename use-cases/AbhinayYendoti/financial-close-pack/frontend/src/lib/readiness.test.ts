import { describe, expect, it } from "vitest";
import { EMPTY_READINESS, toReadinessView } from "./readiness";
import type { ApiReadiness } from "./types";

const apiReadiness = (overrides: Partial<ApiReadiness> = {}): ApiReadiness => ({
  ready_for_generation: false,
  ready_for_close: false,
  readiness: 42,
  documents: { required: 8, present: 7, missing_types: ["Revenue"], unclassified: 1 },
  checklist: { required: 7, complete: 5 },
  generation: { generated: false },
  reviews: { total: 3, resolved: 0 },
  signoffs: { required: 3, approved: 2 },
  export: { exported: false },
  blockers: ["1 required document needs attention"],
  ...overrides
});

describe("toReadinessView", () => {
  it("maps the backend gate onto the counters the UI renders", () => {
    const view = toReadinessView(apiReadiness());

    expect(view).toMatchObject({
      readiness: 42,
      docsReady: 7,
      docsRequired: 8,
      checklistDone: 5,
      checklistRequired: 7,
      reviewsResolved: 0,
      reviewsTotal: 3,
      signoffsDone: 2,
      signoffsRequired: 3,
      canClose: false
    });
    expect(view.blockers).toEqual(["1 required document needs attention"]);
  });

  it("reports canClose only when the backend says the gate is open", () => {
    expect(toReadinessView(apiReadiness({ ready_for_close: true })).canClose).toBe(true);
    expect(toReadinessView(apiReadiness({ ready_for_close: false })).canClose).toBe(false);
  });

  it("falls back to an empty view when readiness has not loaded", () => {
    expect(toReadinessView(undefined)).toEqual(EMPTY_READINESS);
    expect(toReadinessView(null)).toEqual(EMPTY_READINESS);
  });

  it("never emits NaN into the progress ring", () => {
    const view = toReadinessView(apiReadiness({ readiness: Number.NaN }));
    expect(view.readiness).toBe(0);
  });

  it("clamps the percentage to the 0-100 the SVG dash array expects", () => {
    expect(toReadinessView(apiReadiness({ readiness: 140 })).readiness).toBe(100);
    expect(toReadinessView(apiReadiness({ readiness: -20 })).readiness).toBe(0);
  });
});
