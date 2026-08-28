import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { useQueueStore } from "@/stores/queueStore";
import { QueueSortControls } from "./QueueSortControls";

describe("QueueSortControls", () => {
  beforeEach(() => {
    useQueueStore.getState().reset();
  });

  it("renders sort field dropdown with ARIA label", () => {
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field");
    expect(select).toBeInTheDocument();
    expect(select.tagName).toBe("SELECT");
  });

  it("renders sort field options", () => {
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field");
    const options = select.querySelectorAll("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("Queued At");
    expect(options[1]).toHaveTextContent("Item Type");
  });

  it("renders sort direction button with ARIA label", () => {
    render(<QueueSortControls />);
    const button = screen.getByLabelText("Sort direction");
    expect(button).toBeInTheDocument();
    expect(button.tagName).toBe("BUTTON");
  });

  it("defaults to 'queued_at' sort field and 'asc' direction", () => {
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field") as HTMLSelectElement;
    const button = screen.getByLabelText("Sort direction");
    expect(select.value).toBe("queued_at");
    expect(button).toHaveTextContent("↑ Asc");
  });

  it("updates store sort field when dropdown changes", () => {
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field");
    fireEvent.change(select, { target: { value: "item_type" } });
    expect(useQueueStore.getState().sortBy).toBe("item_type");
  });

  it("preserves direction when changing sort field", () => {
    useQueueStore.getState().setSortBy("queued_at", "desc");
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field");
    fireEvent.change(select, { target: { value: "item_type" } });
    expect(useQueueStore.getState().sortBy).toBe("item_type");
    expect(useQueueStore.getState().sortDirection).toBe("desc");
  });

  it("toggles direction from asc to desc on button click", () => {
    render(<QueueSortControls />);
    const button = screen.getByLabelText("Sort direction");
    fireEvent.click(button);
    expect(useQueueStore.getState().sortDirection).toBe("desc");
    expect(button).toHaveTextContent("↓ Desc");
  });

  it("toggles direction from desc to asc on button click", () => {
    useQueueStore.getState().setSortBy("queued_at", "desc");
    render(<QueueSortControls />);
    const button = screen.getByLabelText("Sort direction");
    fireEvent.click(button);
    expect(useQueueStore.getState().sortDirection).toBe("asc");
    expect(button).toHaveTextContent("↑ Asc");
  });

  it("preserves sort field when toggling direction", () => {
    useQueueStore.getState().setSortBy("item_type", "asc");
    render(<QueueSortControls />);
    const button = screen.getByLabelText("Sort direction");
    fireEvent.click(button);
    expect(useQueueStore.getState().sortBy).toBe("item_type");
    expect(useQueueStore.getState().sortDirection).toBe("desc");
  });

  it("reflects current store sort field in dropdown", () => {
    useQueueStore.getState().setSortBy("item_type", "asc");
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field") as HTMLSelectElement;
    expect(select.value).toBe("item_type");
  });

  it("applies dark theme styling to controls", () => {
    render(<QueueSortControls />);
    const select = screen.getByLabelText("Sort by field");
    const button = screen.getByLabelText("Sort direction");
    expect(select.className).toContain("bg-gray-800");
    expect(select.className).toContain("text-gray-200");
    expect(button.className).toContain("bg-gray-800");
    expect(button.className).toContain("text-gray-200");
  });
});
