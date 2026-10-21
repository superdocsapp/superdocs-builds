import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import { installApiMock } from "./mockApi";

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

async function ready() {
  return screen.findByRole("combobox", { name: /organization/i });
}

describe("reviewer application", () => {
  beforeEach(() => {
    window.localStorage.clear();
    installApiMock();
  });

  it("renders primary navigation", async () => {
    renderApp("/");
    await ready();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const label of [
      "Overview",
      "Sources",
      "Architecture",
      "Exceptions",
      "Framework",
      "Profiles",
      "Change Impact",
      "Review",
      "Export",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("collapses the desktop sidebar without dropping accessible names", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await ready();
    const toggle = screen.getByRole("button", { name: /collapse navigation/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleName(/expand navigation/i);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const overview = within(nav).getByRole("link", { name: "Overview" });
    expect(overview).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Change Impact" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Integration status" })).not.toBeInTheDocument();
    await user.unhover(toggle);
    overview.focus();
    expect(await screen.findByRole("tooltip", { name: "Overview" })).toBeInTheDocument();
  });

  it("opens the organization dropdown and switches corpus to Meridian HealthTech", async () => {
    const user = userEvent.setup();
    renderApp("/sources");
    const combo = await ready();
    await user.click(combo);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Meridian HealthTech" }));
    expect(combo).toHaveTextContent("Meridian HealthTech");
    expect(await screen.findByText("Clinical Operations Analyst")).toBeInTheDocument();
  });

  it("selects an organization with ArrowDown and Enter, and Escape closes the menu", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const combo = await ready();
    await user.click(combo);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(combo).toHaveTextContent("Meridian HealthTech");
    await user.click(combo);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(combo).toHaveFocus();
  });

  it("changes occupied level and canonical dimension from custom dropdowns", async () => {
    const user = userEvent.setup();
    renderApp("/impact");
    expect(await screen.findByRole("heading", { name: "Change impact" })).toBeInTheDocument();
    const level = screen.getByRole("combobox", { name: /occupied level/i });
    expect(level).toHaveTextContent("IC4 v1");
    await user.click(level);
    await user.click(screen.getByRole("option", { name: "IC1 v1" }));
    expect(level).toHaveTextContent("IC1 v1");
    expect(screen.getByText("Local tickets")).toBeInTheDocument();

    const dimension = screen.getByRole("combobox", { name: /canonical dimension/i });
    expect(dimension).toHaveTextContent("Scope");
    await user.click(dimension);
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Autonomy" }));
    expect(dimension).toHaveTextContent("Autonomy");
  });

  it("shows architecture metrics, title-conflict evidence, and the role drawer", async () => {
    const user = userEvent.setup();
    renderApp("/architecture");
    expect(await screen.findByText("Total roles")).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(screen.getByText("Senior Software Engineer, Workplace Tools")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Title vs evidence" })).toBeInTheDocument();
    expect(screen.getByText(/Title signal/)).toBeInTheDocument();
    expect(screen.getByText(/Evidence-based outcome/)).toBeInTheDocument();
    expect(screen.getByText(/Why it differs/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open evidence" }));
    const drawer = await screen.findByRole("dialog", { name: "Senior Software Engineer, Workplace Tools" });
    expect(within(drawer).getByText(/title was not used to classify/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/Works from defined tickets/)).toBeInTheDocument();
  });

  it("renders provisional and misfit findings as architecture results", async () => {
    renderApp("/exceptions");
    expect(await screen.findByRole("heading", { name: "Provisional and misfit review" })).toBeInTheDocument();
    expect(screen.getByText(/Misfits are valid architecture findings/)).toBeInTheDocument();
    expect(screen.getByText(/Facilities operations sit outside/)).toBeInTheDocument();
    expect(screen.getByText(/requires architecture decision/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /auto assign/i })).not.toBeInTheDocument();
  });

  it("renders the framework level comparison table", async () => {
    renderApp("/framework");
    expect(await screen.findByRole("heading", { name: "Framework" })).toBeInTheDocument();
    expect(screen.getByText("Individual contributor levels")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: "Scope" }).length).toBe(2);
    expect(screen.getByText("IC4 v1")).toBeInTheDocument();
    expect(screen.getByText("Cross-team domain")).toBeInTheDocument();
    expect(screen.getByText("M1 v1")).toBeInTheDocument();
  });

  it("renders an IC4 profile", async () => {
    const user = userEvent.setup();
    renderApp("/profiles");
    expect(await screen.findByText("Software Engineer II, Payments")).toBeInTheDocument();
    const payments = screen.getByText("Software Engineer II, Payments").closest("article");
    expect(payments).toBeTruthy();
    await user.click(within(payments as HTMLElement).getByRole("button", { name: "Open profile" }));
    expect(await screen.findByText("Owns payment sequencing.")).toBeInTheDocument();
    expect(screen.getByText(/Scope: Cross-team domain/)).toBeInTheDocument();
  });

  it("surfaces an invalid level edit", async () => {
    const user = userEvent.setup();
    renderApp("/impact");
    await screen.findByRole("heading", { name: "Change impact" });
    await user.click(screen.getByRole("button", { name: "Analyze impact" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/non-empty strings/i);
  });

  it("plans a targeted IC4 scope change", async () => {
    const user = userEvent.setup();
    renderApp("/impact");
    expect(await screen.findByRole("heading", { name: "Change impact" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OLD" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "NEW" })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/proposed value/i), "Cross-team domain plus sequencing veto.");
    await user.click(screen.getByRole("button", { name: "Plan targeted updates" }));
    expect(await screen.findByText("affected profiles")).toBeInTheDocument();
    expect(screen.getByText("Unrelated sections preserved. Only listed fields change.")).toBeInTheDocument();
    expect(screen.getByText("Scope: Cross-team domain plus sequencing veto.")).toBeInTheDocument();
  });

  it("shows before/after review cards and records approve or reject", async () => {
    const user = userEvent.setup();
    renderApp("/review");
    expect(await screen.findByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();
    expect(screen.getByText("Remote operation")).toBeInTheDocument();
    expect(screen.getByText("Review outcome")).toBeInTheDocument();
    expect(screen.getByText("Document mutation")).toBeInTheDocument();
    expect(screen.getByText("Domain update")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Decision: approved/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText(/Decision: rejected/)).toBeInTheDocument();
  });

  it("shows SuperDocs as not configured on Export", async () => {
    const user = userEvent.setup();
    renderApp("/export");
    expect(await screen.findByText("not configured")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /live superdocs export unavailable/i })).toBeDisabled();
    expect(screen.getByText(/SUPERDOCS_API_KEY is not configured/)).toBeInTheDocument();
    const combo = await screen.findByRole("combobox", { name: /^profile$/i });
    await user.click(combo);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: /filter profile/i })).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: /Software Engineer II, Payments/i }));
    expect(combo).toHaveTextContent(/Software Engineer II, Payments/);
    await user.click(combo);
    await user.type(screen.getByRole("searchbox", { name: /filter profile/i }), "Pay");
    expect(screen.getByRole("option", { name: /Software Engineer II, Payments/i })).toBeInTheDocument();
  });
});

describe("empty and error states", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows an empty review state", async () => {
    installApiMock({ reviewEmpty: true });
    renderApp("/review");
    expect(await screen.findByText(/No pending review/)).toBeInTheDocument();
  });

  it("shows an architecture API error", async () => {
    installApiMock({ failArchitecture: true });
    renderApp("/architecture");
    expect(await screen.findByRole("alert")).toHaveTextContent("Architecture service unavailable.");
  });
});
