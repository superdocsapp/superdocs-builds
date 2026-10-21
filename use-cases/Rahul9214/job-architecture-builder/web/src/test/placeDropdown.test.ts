import { describe, expect, it } from "vitest";
import { placeDropdown, viewportGutter, type DropdownViewport } from "../components/placeDropdown";

function view(width: number, height = 800): DropdownViewport {
  return { width, height, offsetLeft: 0, offsetTop: 0, layoutHeight: height };
}

function fits(width: number, left: number, panelWidth: number) {
  const gutter = viewportGutter(width);
  expect(left).toBeGreaterThanOrEqual(gutter);
  expect(left + panelWidth).toBeLessThanOrEqual(width - gutter);
}

describe("placeDropdown", () => {
  it("uses a 12px gutter below 390 and 16px at 390+", () => {
    expect(viewportGutter(320)).toBe(12);
    expect(viewportGutter(360)).toBe(12);
    expect(viewportGutter(390)).toBe(16);
    expect(viewportGutter(1440)).toBe(16);
  });

  it.each([320, 360, 390, 412, 430, 768, 1024, 1440])(
    "keeps a flush-left trigger inside the %spx viewport",
    (width) => {
      const placed = placeDropdown({ top: 80, left: 0, bottom: 124, width }, view(width));
      fits(width, placed.left, placed.width);
      expect(placed.width).toBe(width - viewportGutter(width) * 2);
    },
  );

  it("matches trigger width when the control is already inset", () => {
    const placed = placeDropdown({ top: 80, left: 200, bottom: 124, width: 280 }, view(1440));
    expect(placed.left).toBe(200);
    expect(placed.width).toBe(280);
    fits(1440, placed.left, placed.width);
  });

  it("clamps a right-edge trigger instead of overflowing", () => {
    const placed = placeDropdown({ top: 80, left: 400, bottom: 124, width: 200 }, view(430));
    fits(430, placed.left, placed.width);
    expect(placed.left).toBe(430 - 200 - 16);
  });

  it("opens upward when there is not enough room below", () => {
    const placed = placeDropdown({ top: 740, left: 24, bottom: 784, width: 280 }, view(1440, 800), 0, 120);
    expect(placed.bottom ?? 0).toBe(0);
    expect(placed.top).toBeLessThan(740);
    expect((placed.top ?? 0) + 120).toBeLessThanOrEqual(740);
  });

  it("does not create document-overflow coordinates on a 320px viewport", () => {
    const placed = placeDropdown({ top: 64, left: 0, bottom: 108, width: 320 }, view(320, 568));
    expect(placed.left).toBe(12);
    expect(placed.width).toBe(296);
    expect(placed.left + placed.width).toBe(308);
  });
});
