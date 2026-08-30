import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Dashboard } from "../../components/dashboard/Dashboard";
import { useAppStore } from "../../store/appStore";
import { SEED_DOCUMENTS } from "../../data/documents";

beforeEach(() => {
  useAppStore.setState({ documents: SEED_DOCUMENTS, toasts: [], commandPaletteOpen: false });
});

function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}

describe("Dashboard", () => {
  it("renders the page heading and metric labels", () => {
    renderDashboard();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Verified Claims")).toBeInTheDocument();
    expect(screen.getByText("Compliance")).toBeInTheDocument();
    expect(screen.getByText("Open Risks")).toBeInTheDocument();
  });

  it("lists every document under 'Documents at a glance'", () => {
    renderDashboard();
    const heading = screen.getByRole("heading", { name: "Documents at a glance" });
    const section = heading.closest("section")!;
    for (const doc of SEED_DOCUMENTS) {
      expect(within(section).getByText(doc.title)).toBeInTheDocument();
    }
  });

  it("surfaces the flagship document's data-residency risk in the attention feed, linked to the right document", () => {
    renderDashboard();
    const item = screen.getByText("Data-residency claim conflicts with the disclosed EU read-replica");
    expect(item).toBeInTheDocument();
    const link = item.closest("a");
    expect(link).toHaveAttribute("href", "/documents/doc-ironclad-msa/risk?risk=risk-ic-01");
  });

  it("shows the fully-clean NDA with a Low risk badge in the documents list", () => {
    renderDashboard();
    const heading = screen.getByRole("heading", { name: "Documents at a glance" });
    const section = heading.closest("section")!;
    const row = within(section).getByText("Mutual NDA — Helios Ventures Partnership").closest("a")!;
    expect(within(row).getByText("Low")).toBeInTheDocument();
  });
});
