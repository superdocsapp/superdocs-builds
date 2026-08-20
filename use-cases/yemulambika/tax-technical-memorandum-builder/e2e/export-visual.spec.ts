import { expect, test } from "@playwright/test";
import type { Proposal } from "../src/domain";
import { renderReviewedExports } from "../src/export-renderer";

const reviewedState = {
  draftHtml:
    "<h1>Tax Technical Memorandum</h1><h2>Facts</h2><p>Synthetic facts.</p><h2>Question presented</h2><p>Synthetic question.</p><h2>Authorities</h2><p>Synthetic Tax Code § 10(1)</p><p>Synthetic Tax Regulations 24(2)</p><h2>Analysis</h2><p>INR 1200000.00 is traced.</p><h2>Conclusion</h2><p>Supported conclusion.</p><h2>Confidence level</h2><p>Moderate</p>",
  proposals: [
    {
      id: "approved-analysis",
      section: "Analysis",
      before: "",
      after:
        "<h2>Approved Analysis</h2><p>Approved proposal content remains.</p>",
      decision: "APPROVED",
      reviewerNote: "Retain",
    },
    {
      id: "rejected-analysis",
      section: "Analysis",
      before: "",
      after:
        "<h2>Rejected Analysis</h2><p>Rejected proposal content is removed.</p>",
      decision: "REJECTED",
      reviewerNote: "Exclude",
    },
    {
      id: "orphan-heading",
      section: "Analysis",
      before: "",
      after: "<h2>Analysis</h2>",
      decision: "APPROVED",
      reviewerNote: "Heading-only fragment",
    },
  ] satisfies Proposal[],
  authorities: [
    { title: "Synthetic Basis Rule", citation: "Synthetic Tax Code § 10(1)" },
    {
      title: "Synthetic Disposal Rule",
      citation: "Synthetic Tax Regulations 24(2)",
    },
  ],
  rows: [{ amount: "1200000.00", source_row_id: "CALC-001" }],
  rejectedAuthorityTitle: "Fabricated Quotation Negative Control",
};
const rendered = renderReviewedExports(reviewedState);

for (const kind of ["client", "file"] as const) {
  test(`${kind} corrected offline HTML derives from reviewed state and renders`, async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.setContent(rendered[kind]);
    await expect(
      page.getByRole("heading", { name: "Approved Analysis", exact: true }),
    ).toBeVisible();
    await expect(page.locator("body")).toContainText(
      "Approved proposal content remains.",
    );
    await expect(page.locator("body")).not.toContainText("Rejected Analysis");
    await expect(page.locator("body")).not.toContainText(
      "Rejected proposal content is removed.",
    );
    const orphanHeadings = await page
      .locator("h2")
      .evaluateAll(
        (headings) =>
          headings.filter(
            (heading) =>
              heading.nextElementSibling?.tagName.toLowerCase() === "h2",
          ).length,
      );
    expect(orphanHeadings).toBe(0);
    const overflow = await page.evaluate(() => ({
      horizontal:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
      clipped: [...document.querySelectorAll("*")].some((element) => {
        const style = getComputedStyle(element);
        return (
          element.scrollWidth > element.clientWidth &&
          style.overflowX === "hidden"
        );
      }),
    }));
    expect(overflow).toEqual({ horizontal: false, clipped: false });
    if (kind === "client") {
      await expect(page.locator("body")).not.toContainText(
        "Unsupported-authority warnings",
      );
      await expect(page.locator("body")).not.toContainText(
        "Reviewer decision log",
      );
    } else {
      for (const heading of [
        "Authorities table",
        "Numeric traceability register",
        "Unsupported-authority warnings",
        "Reviewer decision log",
      ])
        await expect(
          page.getByRole("heading", { name: heading, exact: true }),
        ).toBeVisible();
    }
    expect(rendered.file.startsWith(rendered.client)).toBe(true);
    expect(consoleErrors).toEqual([]);
    await page.screenshot({
      path: `docs/evidence/manual-live/corrected-offline-${kind}-render.png`,
      fullPage: true,
    });
  });
}
