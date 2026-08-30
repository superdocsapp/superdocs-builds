import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CommandPalette } from "../../components/command-center/CommandPalette";
import { useAppStore } from "../../store/appStore";
import { SEED_DOCUMENTS } from "../../data/documents";

beforeEach(() => {
  useAppStore.setState({ documents: SEED_DOCUMENTS, toasts: [], commandPaletteOpen: true });
});

function RiskTabMarker() {
  return <p>You are on the risk tab</p>;
}

function renderPalette() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<CommandPalette />} />
        <Route
          path="/documents/:id/risk"
          element={
            <>
              <CommandPalette />
              <RiskTabMarker />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CommandPalette", () => {
  it("shows canned commands when the query is empty", () => {
    renderPalette();
    expect(screen.getByText("Find unsupported claims")).toBeInTheDocument();
    expect(screen.getByText("Show high-risk documents")).toBeInTheDocument();
    expect(screen.getByText("Show documents awaiting approval")).toBeInTheDocument();
  });

  it("runs the high-risk-documents command and navigates to the selected result", async () => {
    const user = userEvent.setup();
    renderPalette();

    const input = screen.getByRole("textbox", { name: "Search SuperDocs" });
    await user.type(input, "high risk");

    const result = await screen.findByText("Vendor Security Questionnaire — Meridian Analytics");
    await user.click(result);

    expect(await screen.findByText("You are on the risk tab")).toBeInTheDocument();
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });

  it("shows a friendly empty state for a query with no matches", async () => {
    const user = userEvent.setup();
    renderPalette();
    await user.type(screen.getByRole("textbox", { name: "Search SuperDocs" }), "zzzznomatch");
    expect(await screen.findByText(/No matches for/)).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    renderPalette();
    expect(screen.getByRole("dialog", { name: "Search SuperDocs" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });
});
