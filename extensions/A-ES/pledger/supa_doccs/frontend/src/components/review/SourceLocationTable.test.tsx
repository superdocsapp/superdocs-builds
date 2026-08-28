import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SourceLocationTable } from "./SourceLocationTable";
import type { SourceCitation } from "@/types/review";

function makeCitation(
  overrides: Partial<SourceCitation> = {}
): SourceCitation {
  return {
    claim_id: "loan_agreement.interest_1",
    claim_text: "The annual interest rate on the principal is 12.5% per annum.",
    citation_status: "grounded",
    source_location: {
      page_number: 4,
      section_id: "sec-3.1",
      start_offset: 1450,
      end_offset: 1520,
      clause_ref: "§3.1.2",
    },
    ...overrides,
  };
}

describe("SourceLocationTable", () => {
  it("renders nothing when no citations have locations", () => {
    const { container } = render(
      <SourceLocationTable
        citations={[
          makeCitation({ source_location: null }),
        ]}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders document identity and readable snippet for a specific document/version", () => {
    render(
      <SourceLocationTable
        citations={[
          makeCitation({
            document_id: "3b729393-fb27-4c41-8f41-5a3d2bfd3f72",
            document_version_id: "9f2c1a44-1111-2222-3333-444455556666",
            snippet:
              "The annual interest rate on the principal is 12.5% per annum.",
          }),
        ]}
      />
    );

    // Document identity (short ids, full values on hover title)
    expect(screen.getByText(/doc 3b729393/)).toBeInTheDocument();
    expect(screen.getByText(/v9f2c1a4/)).toBeInTheDocument();

    // Readable quoted text — not just offset numbers
    expect(
      screen.getByText(
        /“The annual interest rate on the principal is 12\.5% per annum\.”/
      )
    ).toBeInTheDocument();

    // Location metadata still present
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("sec-3.1")).toBeInTheDocument();
    expect(screen.getByText("§3.1.2")).toBeInTheDocument();
    expect(screen.getByText("1450–1520")).toBeInTheDocument();
  });

  it("flags citations missing a document reference as unlinked", () => {
    render(
      <SourceLocationTable
        citations={[makeCitation({ snippet: "some text" })]}
      />
    );
    expect(screen.getByText("unlinked")).toBeInTheDocument();
  });
});
