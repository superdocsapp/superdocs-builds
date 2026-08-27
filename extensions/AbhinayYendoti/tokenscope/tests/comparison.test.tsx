// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TokenComparison } from "../src/components/TokenComparison.js";
import { measure } from "../shared/tokens.js";
import type { DocumentSnapshot, JobWork, Measurement } from "../shared/types.js";

/**
 * What the pane actually renders.
 *
 * The product's claim is not "here are two numbers", it is "here are two numbers
 * and you can tell which is which". These tests hold that line: a figure that was
 * estimated must never render as measured, and a figure that does not exist must
 * never render as a number.
 */

const DOCUMENT: DocumentSnapshot = {
  paragraphs: [
    { id: "p0", text: "Quarterly Review" },
    { id: "p1", text: "The quarterly review covers three business units this period." },
    { id: "p2", text: "Headcount grew by eleven people, concentrated in engineering." }
  ]
};

const SELECTION = { paragraphIds: ["p1"], text: DOCUMENT.paragraphs[1]!.text };

function work(sections: number, tokens: number): JobWork {
  return {
    sectionsChanged: sections,
    output: { tokens, source: "tokenized", method: "test fixture" }
  };
}

function show(measurement: Measurement, measuring = false) {
  return render(
    <TokenComparison
      measurement={measurement}
      measuring={measuring}
      onMeasureWholeDocument={vi.fn()}
    />
  );
}

/** The block for one of the two comparisons, found by its heading. */
function block(label: string): HTMLElement {
  return screen.getByRole("region", { name: label });
}

function figure(label: string, side: "Surgical edit" | "Whole document"): HTMLElement {
  const heading = within(block(label)).getByText(side);
  const element = heading.parentElement;

  if (element === null) throw new Error(`no figure for ${side}`);

  return element;
}

const REPORTED = "What SuperDocs reported it cost";
const WRITTEN = "How much text had to be written";

afterEach(cleanup);

describe("before a regeneration has been run", () => {
  const measurement = measure({
    document: DOCUMENT,
    selection: SELECTION,
    surgicalWork: work(1, 18),
    reportedSurgicalTokens: 90_711
  });

  it("shows the measured surgical cost with a Measured badge", () => {
    show(measurement);

    const surgical = figure(REPORTED, "Surgical edit");

    expect(within(surgical).getByText("90,711")).toBeDefined();
    expect(within(surgical).getByText("Measured")).toBeDefined();
    expect(within(surgical).queryByText("Estimated")).toBeNull();
  });

  it("never labels the whole-document estimate as measured", () => {
    show(measurement);

    for (const label of [REPORTED, WRITTEN]) {
      const whole = figure(label, "Whole document");

      expect(within(whole).getByText("Estimated")).toBeDefined();
      expect(within(whole).queryByText("Measured")).toBeNull();
    }
  });

  it("offers to replace the estimate with a measurement", () => {
    show(measurement);

    expect(
      screen.getByRole("button", { name: /measure it for real/iu }).getAttribute("disabled")
    ).toBeNull();
  });

  it("disables that offer while the regeneration is running", () => {
    show(measurement, true);

    expect(screen.getByRole("button", { name: /regenerating/iu }).hasAttribute("disabled")).toBe(
      true
    );
  });
});

describe("after a regeneration has been measured", () => {
  const measurement = measure({
    document: DOCUMENT,
    selection: SELECTION,
    surgicalWork: work(1, 37),
    reportedSurgicalTokens: 345_779,
    wholeDocumentWork: work(300, 17_576),
    reportedWholeDocumentTokens: 856_393
  });

  it("shows both sides as measured, with the real numbers", () => {
    show(measurement);

    expect(within(figure(REPORTED, "Surgical edit")).getByText("345,779")).toBeDefined();
    expect(within(figure(REPORTED, "Whole document")).getByText("856,393")).toBeDefined();
    expect(within(figure(REPORTED, "Whole document")).getByText("Measured")).toBeDefined();
  });

  it("states the savings as the measured difference", () => {
    show(measurement);

    // (856,393 - 345,779) / 856,393
    expect(within(block(REPORTED)).getByText("59.62%")).toBeDefined();
    // (17,576 - 37) / 17,576
    expect(within(block(WRITTEN)).getByText("99.79%")).toBeDefined();
  });

  it("reports the sections each side changed", () => {
    show(measurement);

    expect(screen.getByText("1 vs 300")).toBeDefined();
  });

  it("stops offering to measure something already measured", () => {
    show(measurement);

    expect(screen.queryByRole("button", { name: /measure it for real/iu })).toBeNull();
  });
});

describe("when SuperDocs reported no token count", () => {
  const measurement = measure({
    document: DOCUMENT,
    selection: SELECTION,
    surgicalWork: work(1, 25),
    reportedSurgicalTokens: null
  });

  it("says so rather than rendering a zero", () => {
    show(measurement);

    const surgical = figure(REPORTED, "Surgical edit");

    expect(within(surgical).getByText("Not reported")).toBeDefined();
    expect(within(surgical).queryByText("0")).toBeNull();
    expect(within(block(REPORTED)).getByText(/No comparison is possible/u)).toBeDefined();
  });

  it("still shows the comparison that does not depend on that number", () => {
    show(measurement);

    expect(within(figure(WRITTEN, "Surgical edit")).getByText("25")).toBeDefined();
    expect(within(block(WRITTEN)).getByText(/%$/u)).toBeDefined();
  });
});

describe("when the surgical edit cost more than the regeneration", () => {
  const measurement = measure({
    document: DOCUMENT,
    selection: SELECTION,
    surgicalWork: work(1, 20),
    reportedSurgicalTokens: 181_978,
    wholeDocumentWork: work(20, 1_124),
    reportedWholeDocumentTokens: 138_122
  });

  it("says that plainly instead of hiding the sign", () => {
    show(measurement);

    const reported = within(block(REPORTED));

    expect(reported.getByText("+31.75%")).toBeDefined();
    expect(reported.getByText(/more than regenerating this document/u)).toBeDefined();
  });
});
