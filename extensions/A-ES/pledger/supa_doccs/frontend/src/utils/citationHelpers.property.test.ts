import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { getCitationLabel, isUnverifiable } from "./citationHelpers";
import type { SourceCitation, SourceLocation } from "@/types/review";

/**
 * **Validates: Requirements 1.3, 1.4**
 *
 * Property 1: Citation Chip Rendering Correctness
 *
 * For any SourceCitation:
 * - IF citation_status === "unverifiable" OR source_location === null:
 *     getCitationLabel SHALL return "[citation unverifiable]"
 *     isUnverifiable SHALL return true
 * - IF citation_status === "grounded" AND source_location !== null:
 *     getCitationLabel SHALL return clause_ref if non-null, otherwise "p.{page_number}"
 *     isUnverifiable SHALL return false
 */

// --- Generators ---

const sourceLocationArb: fc.Arbitrary<SourceLocation> = fc.record({
  page_number: fc.option(fc.integer({ min: 1, max: 9999 }), { nil: null }),
  section_id: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
  start_offset: fc.nat({ max: 100000 }),
  end_offset: fc.nat({ max: 100000 }),
  clause_ref: fc.option(fc.string({ minLength: 1, maxLength: 50 }), { nil: null }),
});

const sourceCitationArb: fc.Arbitrary<SourceCitation> = fc.record({
  claim_id: fc.uuid(),
  claim_text: fc.string({ minLength: 1, maxLength: 200 }),
  citation_status: fc.constantFrom("grounded" as const, "unverifiable" as const),
  source_location: fc.option(sourceLocationArb, { nil: null }),
});

// --- Property Tests ---

describe("Citation Helpers - Property 1: Citation Chip Rendering Correctness", () => {
  it("unverifiable citations (status=unverifiable OR source_location=null) return correct label and flag", () => {
    fc.assert(
      fc.property(sourceCitationArb, (citation) => {
        const isUnverifiableCase =
          citation.citation_status === "unverifiable" ||
          citation.source_location === null;

        if (isUnverifiableCase) {
          expect(getCitationLabel(citation)).toBe("[citation unverifiable]");
          expect(isUnverifiable(citation)).toBe(true);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("grounded citations with non-null source_location return correct label and flag", () => {
    // Generate only grounded citations with non-null source_location
    const groundedWithLocationArb: fc.Arbitrary<SourceCitation> = fc.record({
      claim_id: fc.uuid(),
      claim_text: fc.string({ minLength: 1, maxLength: 200 }),
      citation_status: fc.constant("grounded" as const),
      source_location: sourceLocationArb,
    });

    fc.assert(
      fc.property(groundedWithLocationArb, (citation) => {
        expect(isUnverifiable(citation)).toBe(false);

        const label = getCitationLabel(citation);
        const loc = citation.source_location!;

        if (loc.clause_ref !== null) {
          expect(label).toBe(loc.clause_ref);
        } else {
          expect(label).toBe(`p.${loc.page_number}`);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("getCitationLabel and isUnverifiable are consistent for all citations", () => {
    fc.assert(
      fc.property(sourceCitationArb, (citation) => {
        const unverifiable = isUnverifiable(citation);
        const label = getCitationLabel(citation);

        if (unverifiable) {
          expect(label).toBe("[citation unverifiable]");
        } else {
          // Must be grounded with a non-null source_location
          expect(citation.citation_status).toBe("grounded");
          expect(citation.source_location).not.toBeNull();
          // Label is either clause_ref or "p.{page_number}"
          const loc = citation.source_location!;
          if (loc.clause_ref !== null) {
            expect(label).toBe(loc.clause_ref);
          } else {
            expect(label).toBe(`p.${loc.page_number}`);
          }
        }
      }),
      { numRuns: 100 }
    );
  });
});
