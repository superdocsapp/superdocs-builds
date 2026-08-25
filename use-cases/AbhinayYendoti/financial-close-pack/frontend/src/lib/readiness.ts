import type { ApiReadiness } from "./types";

/**
 * View model for the readiness ring, metric tiles, and close gate.
 *
 * This module used to hold a second, independent implementation of the readiness
 * calculation that drifted from the backend's (different denominators, different
 * blockers) and was the only thing the close button consulted. Readiness is now
 * computed once, on the server, and this only reshapes it for rendering.
 */
export type ReadinessView = {
  readiness: number;
  docsReady: number;
  docsRequired: number;
  checklistDone: number;
  checklistRequired: number;
  reviewsResolved: number;
  reviewsTotal: number;
  signoffsDone: number;
  signoffsRequired: number;
  generated: boolean;
  exported: boolean;
  canClose: boolean;
  canGenerate: boolean;
  blockers: string[];
};

export const EMPTY_READINESS: ReadinessView = {
  readiness: 0,
  docsReady: 0,
  docsRequired: 0,
  checklistDone: 0,
  checklistRequired: 0,
  reviewsResolved: 0,
  reviewsTotal: 0,
  signoffsDone: 0,
  signoffsRequired: 0,
  generated: false,
  exported: false,
  canClose: false,
  canGenerate: false,
  blockers: []
};

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function toReadinessView(readiness: ApiReadiness | undefined | null): ReadinessView {
  if (!readiness) return EMPTY_READINESS;

  return {
    // Guarded so a malformed payload can never write NaN into the SVG dash array.
    readiness: clampPercent(readiness.readiness),
    docsReady: readiness.documents?.present ?? 0,
    docsRequired: readiness.documents?.required ?? 0,
    checklistDone: readiness.checklist?.complete ?? 0,
    checklistRequired: readiness.checklist?.required ?? 0,
    reviewsResolved: readiness.reviews?.resolved ?? 0,
    reviewsTotal: readiness.reviews?.total ?? 0,
    signoffsDone: readiness.signoffs?.approved ?? 0,
    signoffsRequired: readiness.signoffs?.required ?? 0,
    generated: readiness.generation?.generated ?? false,
    exported: readiness.export?.exported ?? false,
    canClose: readiness.ready_for_close ?? false,
    canGenerate: readiness.ready_for_generation ?? false,
    blockers: readiness.blockers ?? []
  };
}
