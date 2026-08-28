import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MasterDetail } from "./MasterDetail";

describe("MasterDetail", () => {
  const listContent = <div data-testid="list-panel">Queue List</div>;
  const detailContent = <div data-testid="detail-panel">Detail View</div>;

  it("renders both panels", () => {
    render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={false}
      />
    );

    expect(screen.getByTestId("list-panel")).toBeInTheDocument();
    expect(screen.getByTestId("detail-panel")).toBeInTheDocument();
  });

  it("applies correct responsive classes for desktop side-by-side layout", () => {
    const { container } = render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={false}
      />
    );

    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.className).toContain("md:flex-row");

    // List panel container
    const listContainer = wrapper.children[0] as HTMLElement;
    expect(listContainer.className).toContain("md:w-2/5");
    expect(listContainer.className).toContain("md:block");

    // Detail panel container (now uses md:flex-1 after the divider)
    const detailContainer = wrapper.children[2] as HTMLElement;
    expect(detailContainer.className).toContain("md:flex-1");
    expect(detailContainer.className).toContain("md:block");
  });

  it("shows list panel and hides detail on mobile when hasSelection is false", () => {
    const { container } = render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={false}
      />
    );

    const wrapper = container.firstElementChild as HTMLElement;
    const listContainer = wrapper.children[0] as HTMLElement;
    // Detail panel is now children[2] (after divider at children[1])
    const detailContainer = wrapper.children[2] as HTMLElement;

    // List visible on mobile (block class applied)
    expect(listContainer.className).toContain("block");
    expect(listContainer.className).not.toContain("hidden");

    // Detail hidden on mobile
    expect(detailContainer.className).toContain("hidden");
  });

  it("shows detail panel and hides list on mobile when hasSelection is true", () => {
    const { container } = render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={true}
      />
    );

    const wrapper = container.firstElementChild as HTMLElement;
    const listContainer = wrapper.children[0] as HTMLElement;
    // Detail panel is now children[2] (after divider at children[1])
    const detailContainer = wrapper.children[2] as HTMLElement;

    // List hidden on mobile
    expect(listContainer.className).toContain("hidden");

    // Detail visible on mobile (block class applied)
    expect(detailContainer.className).toContain("block");
    expect(detailContainer.className).not.toContain("hidden");
  });

  it("renders back button when hasSelection is true", () => {
    render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={true}
        onBack={vi.fn()}
      />
    );

    expect(
      screen.getByRole("button", { name: "Back to queue list" })
    ).toBeInTheDocument();
  });

  it("does not render back button when hasSelection is false", () => {
    render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={false}
        onBack={vi.fn()}
      />
    );

    expect(
      screen.queryByRole("button", { name: "Back to queue list" })
    ).not.toBeInTheDocument();
  });

  it("calls onBack when back button is clicked", () => {
    const onBack = vi.fn();

    render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={true}
        onBack={onBack}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Back to queue list" })
    );

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("back button has correct aria-label", () => {
    render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={true}
        onBack={vi.fn()}
      />
    );

    const backButton = screen.getByRole("button", {
      name: "Back to queue list",
    });
    expect(backButton).toHaveAttribute("aria-label", "Back to queue list");
  });

  it("back button container is hidden on desktop via md:hidden", () => {
    const { container } = render(
      <MasterDetail
        listPanel={listContent}
        detailPanel={detailContent}
        hasSelection={true}
        onBack={vi.fn()}
      />
    );

    const wrapper = container.firstElementChild as HTMLElement;
    // Detail panel is children[2] (after divider at children[1])
    const detailContainer = wrapper.children[2] as HTMLElement;
    const backButtonContainer = detailContainer.children[0] as HTMLElement;

    expect(backButtonContainer.className).toContain("md:hidden");
  });
});
