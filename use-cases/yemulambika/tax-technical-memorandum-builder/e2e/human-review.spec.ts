import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

test("duplicate-heading proposals retain independent identity and export state", async ({
  page,
}) => {
  const nonLocalRequests: string[] = [];
  page.on("request", (request) => {
    if (!new URL(request.url()).hostname.match(/^(127\.0\.0\.1|localhost)$/))
      nonLocalRequests.push(request.url());
    expect(request.headers()).not.toHaveProperty("authorization");
  });
  await page.goto("/");
  await expect(page.getByText("SuperDocs mode: Offline demo")).toBeVisible();
  await page
    .getByRole("button", { name: "Start new tax memorandum case" })
    .click();
  await page.getByLabel("Synthetic document files").setInputFiles([
    {
      name: "synthetic-client-facts.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Synthetic client facts and tax question"),
    },
    {
      name: "synthetic-authority-1.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Synthetic Basis Rule"),
    },
    {
      name: "synthetic-authority-2.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Synthetic Disposal Proceeds Rule"),
    },
    {
      name: "synthetic-tax-memo.html",
      mimeType: "text/html",
      buffer: Buffer.from("<h1>Tax Technical Memorandum</h1>"),
    },
  ]);
  await page.getByRole("button", { name: "Upload four documents" }).click();
  await expect(
    page.locator("section p", { hasText: "— UPLOADED" }),
  ).toHaveCount(4);
  await page.getByRole("button", { name: "Generate memorandum" }).click();

  const proposals = page.locator("article.proposal");
  await expect(proposals).toHaveCount(2);
  await expect(
    proposals.getByRole("heading", { name: "Analysis", exact: true }),
  ).toHaveCount(2);
  const valid = page.locator(
    'article.proposal[data-proposal-id="fixture-change-valid"]',
  );
  const fabricated = page.locator(
    'article.proposal[data-proposal-id="fixture-change-fabricated"]',
  );
  await expect(valid).toHaveCount(1);
  await expect(fabricated).toHaveCount(1);

  const validNote = valid.getByRole("textbox", {
    name: "Reviewer note for Analysis proposal 1 of 2",
  });
  const fabricatedNote = fabricated.getByRole("textbox", {
    name: "Reviewer note for Analysis proposal 2 of 2",
  });
  await validNote.fill("Verified against the supplied monetary record.");
  await valid
    .getByRole("button", { name: "Approve Analysis proposal 1 of 2" })
    .click();
  await expect(valid.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(fabricated.getByText("PENDING", { exact: true })).toBeVisible();
  await expect(fabricatedNote).toHaveValue("");

  await fabricatedNote.fill("Fabricated and unsupported; exclude from output.");
  await fabricated
    .getByRole("button", { name: "Reject Analysis proposal 2 of 2" })
    .click();
  await expect(valid.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(fabricated.getByText("REJECTED", { exact: true })).toBeVisible();
  await expect(validNote).toHaveValue(
    "Verified against the supplied monetary record.",
  );
  await expect(fabricatedNote).toHaveValue(
    "Fabricated and unsupported; exclude from output.",
  );

  const blockingMonetaryRows = page.locator(
    '[data-testid="monetary-row"][data-trace-status="unmatched-blocking"]',
  );
  await expect(blockingMonetaryRows).toHaveCount(1);
  await expect(blockingMonetaryRows).toContainText("INR 999999.00");
  await expect(blockingMonetaryRows).toContainText("UNMATCHED");
  await expect(blockingMonetaryRows).toContainText("BLOCKING");
  await expect(blockingMonetaryRows).toContainText(
    "finalization is blocked until this figure is corrected",
  );
  const approvalAction = page.getByRole("button", {
    name: "Submit reviewed content",
    exact: true,
  });
  const clientExport = page.getByRole("button", {
    name: "Download client-ready HTML",
  });
  const fileExport = page.getByRole("button", {
    name: "Download file-ready HTML",
  });
  await expect(approvalAction).toBeDisabled();
  await expect(clientExport).toBeDisabled();
  await expect(fileExport).toBeDisabled();

  await page
    .getByRole("button", {
      name: "Reject fabricated quotation and correct unmatched figure",
    })
    .click();
  await expect(blockingMonetaryRows).toHaveCount(0);
  await expect(valid.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(fabricated.getByText("REJECTED", { exact: true })).toBeVisible();
  await expect(validNote).toHaveValue(
    "Verified against the supplied monetary record.",
  );
  await expect(fabricatedNote).toHaveValue(
    "Fabricated and unsupported; exclude from output.",
  );
  await expect(approvalAction).toBeEnabled();
  await expect(
    page.locator("p", { hasText: "Mandatory pending:" }),
  ).toContainText("0");
  await page.screenshot({
    path: resolve("docs/evidence/offline-duplicate-analysis-proposals.png"),
    fullPage: true,
  });

  const approvalRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/approve"),
  );
  await approvalAction.click();
  const submitted = (await approvalRequest).postDataJSON() as {
    proposals: Array<{
      id: string;
      decision: string;
      reviewerNote: string;
    }>;
  };
  expect(submitted.proposals).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        id: "fixture-change-valid",
        decision: "APPROVED",
        reviewerNote: "Verified against the supplied monetary record.",
      }),
      expect.objectContaining({
        id: "fixture-change-fabricated",
        decision: "REJECTED",
        reviewerNote: "Fabricated and unsupported; exclude from output.",
      }),
    ]),
  );
  await page
    .getByRole("button", { name: "Submit identical decisions again" })
    .click();
  await expect(
    page.getByText("Identical approval suppressed locally"),
  ).toBeVisible();

  for (const kind of ["client", "file"] as const) {
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("button", { name: `Download ${kind}-ready HTML` })
      .click();
    const download = await downloadPromise;
    const path = await download.path();
    expect(path).toBeTruthy();
    const html = await readFile(path!, "utf8");
    expect(html).toContain("INR 1200000 taxable amount is supported.");
    expect(html).not.toContain(
      "Every fictional disposal is automatically exempt from tax.",
    );
  }
  expect(nonLocalRequests).toEqual([]);
});
