import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueueList } from "./QueueList";
import { QueueItem } from "@/types/review";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Test summary",
      details: {},
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-01T00:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
    ...overrides,
  };
}

describe("QueueList", () => {
  it("renders with role=listbox and aria-label", () => {
    render(
      <QueueList
        items={[]}
        selectedItemId={null}
        optimisticStatuses={{}}
        onSelectItem={() => {}}
        total={0}
        pending={0}
      />
    );
    const listbox = screen.getByRole("listbox", { name: "Approval queue items" });
    expect(listbox).toBeInTheDocument();
  });

  it("renders one QueueItemCard per item", () => {
    const items = [
      makeItem({ id: "item-1" }),
      makeItem({ id: "item-2", item_type: "conflict" }),
      makeItem({ id: "item-3", item_type: "proposed_update" }),
    ];
    render(
      <QueueList
        items={items}
        selectedItemId={null}
        optimisticStatuses={{}}
        onSelectItem={() => {}}
        total={3}
        pending={3}
      />
    );
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
  });

  it("marks the selected item with aria-selected=true", () => {
    const items = [
      makeItem({ id: "item-1" }),
      makeItem({ id: "item-2", item_type: "conflict" }),
    ];
    render(
      <QueueList
        items={items}
        selectedItemId="item-2"
        optimisticStatuses={{}}
        onSelectItem={() => {}}
        total={2}
        pending={2}
      />
    );
    const options = screen.getAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "false");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
  });

  it("marks items with optimistic status as loading", () => {
    const items = [makeItem({ id: "item-1" })];
    render(
      <QueueList
        items={items}
        selectedItemId={null}
        optimisticStatuses={{ "item-1": "approved" }}
        onSelectItem={() => {}}
        total={1}
        pending={1}
      />
    );
    const option = screen.getByRole("option");
    expect(option).toHaveAttribute("aria-busy", "true");
  });

  it("calls onSelectItem with the item id when a card is clicked", () => {
    const items = [
      makeItem({ id: "item-1" }),
      makeItem({ id: "item-2", item_type: "conflict" }),
    ];
    const handleSelect = vi.fn();
    render(
      <QueueList
        items={items}
        selectedItemId={null}
        optimisticStatuses={{}}
        onSelectItem={handleSelect}
        total={2}
        pending={2}
      />
    );
    const options = screen.getAllByRole("option");
    fireEvent.click(options[1]);
    expect(handleSelect).toHaveBeenCalledWith("item-2");
  });

  it("displays QueueSummaryBar with total and pending", () => {
    render(
      <QueueList
        items={[]}
        selectedItemId={null}
        optimisticStatuses={{}}
        onSelectItem={() => {}}
        total={15}
        pending={7}
      />
    );
    expect(screen.getByText("7 pending")).toBeInTheDocument();
    expect(screen.getByText("15 total")).toBeInTheDocument();
  });

  it("renders empty list when no items provided", () => {
    render(
      <QueueList
        items={[]}
        selectedItemId={null}
        optimisticStatuses={{}}
        onSelectItem={() => {}}
        total={0}
        pending={0}
      />
    );
    const listbox = screen.getByRole("listbox");
    expect(listbox.children).toHaveLength(0);
  });
});
