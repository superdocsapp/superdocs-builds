import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { useQueueStore } from "@/stores/queueStore";
import { QueueFilters } from "./QueueFilters";

describe("QueueFilters", () => {
  beforeEach(() => {
    useQueueStore.getState().reset();
  });

  it("renders item type filter dropdown with ARIA label", () => {
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type");
    expect(select).toBeInTheDocument();
    expect(select.tagName).toBe("SELECT");
  });

  it("renders all item type options including 'All Types'", () => {
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type");
    const options = select.querySelectorAll("option");
    expect(options).toHaveLength(4);
    expect(options[0]).toHaveTextContent("All Types");
    expect(options[1]).toHaveTextContent("Finding");
    expect(options[2]).toHaveTextContent("Conflict");
    expect(options[3]).toHaveTextContent("Proposed Update");
  });

  it("renders unverifiable-only checkbox with ARIA label", () => {
    render(<QueueFilters />);
    const checkbox = screen.getByLabelText("Show unverifiable only");
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).toHaveAttribute("type", "checkbox");
  });

  it("defaults to 'All Types' and unchecked unverifiable toggle", () => {
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type") as HTMLSelectElement;
    const checkbox = screen.getByLabelText("Show unverifiable only") as HTMLInputElement;
    expect(select.value).toBe("");
    expect(checkbox.checked).toBe(false);
  });

  it("updates store when item type filter changes to 'finding'", () => {
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type");
    fireEvent.change(select, { target: { value: "finding" } });
    expect(useQueueStore.getState().filters.itemType).toBe("finding");
  });

  it("updates store when item type filter changes to 'conflict'", () => {
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type");
    fireEvent.change(select, { target: { value: "conflict" } });
    expect(useQueueStore.getState().filters.itemType).toBe("conflict");
  });

  it("sets itemType to null when 'All Types' is selected", () => {
    // First set a filter
    useQueueStore.getState().setFilters({ itemType: "finding", unverifiableOnly: false });
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type");
    fireEvent.change(select, { target: { value: "" } });
    expect(useQueueStore.getState().filters.itemType).toBeNull();
  });

  it("updates store when unverifiable toggle is checked", () => {
    render(<QueueFilters />);
    const checkbox = screen.getByLabelText("Show unverifiable only");
    fireEvent.click(checkbox);
    expect(useQueueStore.getState().filters.unverifiableOnly).toBe(true);
  });

  it("updates store when unverifiable toggle is unchecked", () => {
    useQueueStore.getState().setFilters({ itemType: null, unverifiableOnly: true });
    render(<QueueFilters />);
    const checkbox = screen.getByLabelText("Show unverifiable only");
    fireEvent.click(checkbox);
    expect(useQueueStore.getState().filters.unverifiableOnly).toBe(false);
  });

  it("preserves itemType when toggling unverifiable", () => {
    useQueueStore.getState().setFilters({ itemType: "conflict", unverifiableOnly: false });
    render(<QueueFilters />);
    const checkbox = screen.getByLabelText("Show unverifiable only");
    fireEvent.click(checkbox);
    expect(useQueueStore.getState().filters.itemType).toBe("conflict");
    expect(useQueueStore.getState().filters.unverifiableOnly).toBe(true);
  });

  it("reflects current store state in the dropdown value", () => {
    useQueueStore.getState().setFilters({ itemType: "proposed_update", unverifiableOnly: false });
    render(<QueueFilters />);
    const select = screen.getByLabelText("Filter by item type") as HTMLSelectElement;
    expect(select.value).toBe("proposed_update");
  });
});
