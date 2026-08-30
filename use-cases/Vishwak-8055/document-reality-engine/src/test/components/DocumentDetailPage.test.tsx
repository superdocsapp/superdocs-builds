import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DocumentDetailPage } from "../../components/document-detail/DocumentDetailPage";
import { useAppStore } from "../../store/appStore";
import { SEED_DOCUMENTS } from "../../data/documents";

beforeEach(() => {
  useAppStore.setState({ documents: SEED_DOCUMENTS, toasts: [], commandPaletteOpen: false });
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="/documents/:documentId/:tab" element={<DocumentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DocumentDetailPage", () => {
  it("shows a not-found state for an unknown document id", () => {
    renderAt("/documents/does-not-exist");
    expect(screen.getByText("Document not found")).toBeInTheDocument();
  });

  it("renders the Reality tab by default with the document title and status", () => {
    renderAt("/documents/doc-ironclad-msa");
    expect(screen.getByRole("heading", { name: "Master Services Agreement — Ironclad Cloud Services" })).toBeInTheDocument();
    expect(screen.getByText("In Review")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Reality/ })).toHaveAttribute("aria-selected", "true");
  });

  it("lets a reviewer open a claim, see its provenance thread and contradiction note, and mark it verified", async () => {
    const user = userEvent.setup();
    renderAt("/documents/doc-ironclad-msa/claims");

    const claimsHeading = screen.getByRole("heading", { name: "Claims" });
    const claimsColumn = claimsHeading.closest("div")!;
    const claimButton = within(claimsColumn).getByText(/Monthly Uptime Percentage of 99.95%/).closest("button")!;
    await user.click(claimButton);

    const dialog = await screen.findByRole("dialog", { name: "Claim detail" });
    expect(within(dialog).getByText(/Trailing 6-month average uptime is 99.91%/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Mark as verified" }));

    const claim = useAppStore
      .getState()
      .documents.find((d) => d.id === "doc-ironclad-msa")!
      .claims.find((c) => c.id === "claim-ic-01")!;
    expect(claim.verificationStatus).toBe("Verified");

    // Once verified, the action button is gone and the badge in the drawer reflects the new state.
    expect(within(dialog).queryByRole("button", { name: "Mark as verified" })).not.toBeInTheDocument();
    expect(within(dialog).getByText("Verified")).toBeInTheDocument();
  });

  it("resolves an open risk from the Risk tab", async () => {
    const user = userEvent.setup();
    renderAt("/documents/doc-ironclad-msa/risk");

    const findingsHeading = screen.getByRole("heading", { name: "All findings" });
    const findingsList = findingsHeading.closest("section")!;
    const staleSoc2Row = within(findingsList).getByText("SOC 2 Type II report is 14 months old").closest("li")!;

    await user.click(within(staleSoc2Row).getByRole("button", { name: "Mark resolved" }));

    const risk = useAppStore
      .getState()
      .documents.find((d) => d.id === "doc-ironclad-msa")!
      .risks.find((r) => r.id === "risk-ic-03")!;
    expect(risk.status).toBe("Mitigated");
  });

  it("opens the approve confirmation dialog from the Reviews tab and warns about open findings", async () => {
    const user = userEvent.setup();
    renderAt("/documents/doc-ironclad-msa/reviews");

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Approve this document?")).toBeInTheDocument();
    expect(screen.getByText(/open risk finding/)).toBeInTheDocument();
  });

  it("submits a request-changes note and records it as a Deferred decision", async () => {
    const user = userEvent.setup();
    renderAt("/documents/doc-ironclad-msa/reviews");

    await user.click(screen.getByRole("button", { name: "Request changes" }));
    const textarea = await screen.findByLabelText("What needs to change?");
    await user.type(textarea, "Please get the updated SOC 2 report first.");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    const doc = useAppStore.getState().documents.find((d) => d.id === "doc-ironclad-msa")!;
    expect(doc.decisions.at(-1)).toMatchObject({ outcome: "Deferred", notes: "Please get the updated SOC 2 report first." });
    expect(doc.status).toBe("In Review");
  });
});
