import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

test("@live complete browser-to-BFF-to-SuperDocs workflow", async ({
  page,
}) => {
  test.skip(
    process.env.RUN_SUPERDOCS_LIVE_TESTS !== "1" ||
      process.env.SUPERDOCS_MODE !== "real",
  );
  test.setTimeout(180_000);
  const started = Date.now();
  const root = resolve(import.meta.dirname, "..");
  const evidenceDir = resolve(root, "docs/evidence/ui-live");
  await mkdir(evidenceDir, { recursive: true });
  const consoleErrors: string[] = [];
  const httpFailures: Array<{ status: number; path: string }> = [];
  const corsFailures: string[] = [];
  const browserHosts = new Set<string>();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    browserHosts.add(url.hostname);
    expect(["127.0.0.1", "localhost"]).toContain(url.hostname);
    expect(request.headers()).not.toHaveProperty("authorization");
  });
  page.on("response", (response) => {
    if (response.status() >= 400)
      httpFailures.push({
        status: response.status(),
        path: new URL(response.url()).pathname,
      });
  });
  page.on("requestfailed", (request) => {
    if (/cors/i.test(request.failure()?.errorText ?? ""))
      corsFailures.push(request.url());
  });

  const shot = async (name: string) =>
    page.screenshot({
      path: resolve(evidenceDir, `${name}.png`),
      fullPage: true,
    });
  await page.goto("/");
  await expect(
    page.getByText("SuperDocs mode: Live", { exact: true }),
  ).toHaveCount(1);
  await shot("01-live-ready");
  await page
    .getByRole("button", { name: "Start new tax memorandum case" })
    .click();
  await page.getByLabel("Synthetic document files").setInputFiles([
    {
      name: "synthetic-client-facts.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "Fictional Deccan Byteworks facts. Sale INR 6500000.00; basis INR 4800000.00; costs INR 200000.00 and INR 300000.00; taxable amount INR 1200000.00.",
      ),
    },
    {
      name: "synthetic-authority-1.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "SYNTHETIC AUTHORITY — FOR DEMONSTRATION ONLY\nThe verified acquisition price and direct acquisition costs form the taxpayer's basis in an asset.",
      ),
    },
    {
      name: "synthetic-authority-2.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "SYNTHETIC AUTHORITY — FOR DEMONSTRATION ONLY\nTaxable disposal proceeds equal consideration received less verified basis and direct disposal expenses.",
      ),
    },
    {
      name: "synthetic-tax-memo.html",
      mimeType: "text/html",
      buffer: Buffer.from(
        "<h1>Tax Technical Memorandum</h1><h2>Analysis</h2><p>INR 6500000.00 less INR 4800000.00, INR 200000.00 and INR 300000.00 equals INR 1200000.00.</p><h2>Conclusion</h2><p>INR 1200000.00.</p>",
      ),
    },
  ]);
  await page.getByRole("button", { name: "Upload four documents" }).click();
  await expect(
    page.locator("section p", { hasText: "— UPLOADED" }),
  ).toHaveCount(4, { timeout: 30_000 });
  await shot("02-four-documents-uploaded");

  await page.getByRole("button", { name: "Generate memorandum" }).click();
  await expect(page.locator("article.proposal")).toHaveCount(2, {
    timeout: 120_000,
  });
  const jobStatus = page
    .locator("section", {
      has: page.getByRole("heading", { name: "Uploaded documents" }),
    })
    .locator("p", { hasText: "Job status:" });
  await expect(jobStatus).toHaveCount(1);
  await expect(jobStatus).toContainText("awaiting_approval");
  const jobDurationText = await jobStatus.innerText();
  const proposals = page.locator("article.proposal");
  const approvedProposal = proposals.nth(0);
  const rejectedProposal = proposals.nth(1);
  const proposalIds = await proposals.evaluateAll((cards) =>
    cards.map((card) => card.getAttribute("data-proposal-id")),
  );
  expect(proposalIds).toHaveLength(2);
  expect(proposalIds[0]).toBeTruthy();
  expect(proposalIds[1]).toBeTruthy();
  expect(proposalIds[0]).not.toBe(proposalIds[1]);
  await expect(
    proposals.getByRole("heading", { name: "Analysis", exact: true }),
  ).toHaveCount(2);
  const approvedProposalText = await approvedProposal
    .locator("> p")
    .innerText();
  const rejectedProposalText = await rejectedProposal
    .locator("> p")
    .innerText();
  await shot("03-awaiting-approval-verification");

  const quotations = page.locator("section", {
    has: page.getByRole("heading", { name: "Quotation verification" }),
  });
  const monetary = page.locator("section", {
    has: page.getByRole("heading", { name: "Monetary traceability" }),
  });
  await expect(quotations.locator("article")).toHaveCount(3);
  await expect(
    quotations.getByText("REJECTED / BLOCKING", { exact: true }),
  ).toHaveCount(1);
  const monetaryRows = monetary.getByTestId("monetary-row");
  const blockingMonetaryRows = monetary.locator(
    '[data-testid="monetary-row"][data-trace-status="unmatched-blocking"]',
  );
  await expect(monetaryRows).toHaveCount(7);
  await expect(blockingMonetaryRows).toHaveCount(1);
  await expect(blockingMonetaryRows).toContainText("INR 999999.00");
  await expect(blockingMonetaryRows).toContainText("UNMATCHED");
  await expect(blockingMonetaryRows).toContainText("BLOCKING");
  await expect(blockingMonetaryRows).toContainText(
    "finalization is blocked until this figure is corrected",
  );
  const approvedNote =
    "Verified against supplied synthetic facts, citations, and monetary rows.";
  const rejectedNote =
    "Rejected by the human reviewer; excluded from both exports.";
  await approvedProposal
    .getByRole("textbox", { name: /Reviewer note for .* proposal 1 of 2/ })
    .fill(approvedNote);
  await approvedProposal
    .getByRole("button", { name: /Approve .* proposal 1 of 2/ })
    .click();
  await rejectedProposal
    .getByRole("textbox", { name: /Reviewer note for .* proposal 2 of 2/ })
    .fill(rejectedNote);
  await rejectedProposal
    .getByRole("button", { name: /Reject .* proposal 2 of 2/ })
    .click();
  await expect(
    approvedProposal.getByText("APPROVED", { exact: true }),
  ).toBeVisible();
  await expect(
    rejectedProposal.getByText("REJECTED", { exact: true }),
  ).toBeVisible();
  await expect(
    approvedProposal.getByRole("textbox", {
      name: /Reviewer note for .* proposal 1 of 2/,
    }),
  ).toHaveValue(approvedNote);
  await expect(
    rejectedProposal.getByRole("textbox", {
      name: /Reviewer note for .* proposal 2 of 2/,
    }),
  ).toHaveValue(rejectedNote);
  await page
    .getByRole("button", {
      name: "Reject fabricated quotation and correct unmatched figure",
    })
    .click();
  await expect(monetaryRows).toHaveCount(6);
  await expect(blockingMonetaryRows).toHaveCount(0);
  await expect(
    approvedProposal.getByText("APPROVED", { exact: true }),
  ).toBeVisible();
  await expect(
    rejectedProposal.getByText("REJECTED", { exact: true }),
  ).toBeVisible();
  await expect(
    approvedProposal.getByRole("textbox", {
      name: /Reviewer note for .* proposal 1 of 2/,
    }),
  ).toHaveValue(approvedNote);
  await expect(
    rejectedProposal.getByRole("textbox", {
      name: /Reviewer note for .* proposal 2 of 2/,
    }),
  ).toHaveValue(rejectedNote);
  const mandatoryPending = page.locator("p", {
    hasText: "Mandatory pending:",
  });
  await expect(mandatoryPending).toHaveCount(1);
  await expect(mandatoryPending).toContainText("0");
  await shot("04-mixed-review-complete");
  const approvalAction = page.getByRole("button", {
    name: "Submit reviewed content",
    exact: true,
  });
  await expect(approvalAction).toHaveCount(1);
  const approvalResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/approve"),
  );
  await approvalAction.click();
  const approvalResponse = await approvalResponsePromise;
  expect(approvalResponse.status()).toBe(200);
  const approvalBody = (await approvalResponse.json()) as {
    upstreamApprovalCount: number;
  };
  expect(approvalBody.upstreamApprovalCount).toBe(1);
  await expect(
    page.getByText("Review submitted — memo content approved"),
  ).toBeVisible();
  const duplicateResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/approve"),
  );
  await page
    .getByRole("button", { name: "Submit identical decisions again" })
    .click();
  const duplicateResponse = await duplicateResponsePromise;
  expect(duplicateResponse.status()).toBe(200);
  const duplicateBody = (await duplicateResponse.json()) as {
    duplicateSuppressed: boolean;
    upstreamApprovalCount: number;
  };
  expect(duplicateBody).toMatchObject({
    duplicateSuppressed: true,
    upstreamApprovalCount: 1,
  });
  await expect(
    page.getByText("Identical approval suppressed locally"),
  ).toBeVisible();

  const exports = [] as Array<{
    kind: string;
    name: string;
    size: number;
    sha256: string;
  }>;
  for (const kind of ["client", "file"] as const) {
    const downloadPromise = page.waitForEvent("download");
    const exportButton = page.getByRole("button", {
      name: `Download ${kind}-ready HTML`,
      exact: true,
    });
    await expect(exportButton).toHaveCount(1);
    await exportButton.click();
    const download = await downloadPromise;
    const path = await download.path();
    expect(path).toBeTruthy();
    const bytes = await readFile(path!);
    const content = bytes.toString("utf8");
    const toPlain = (value: string) =>
      value
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    const plainContent = toPlain(content);
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    expect(bytes.length).toBeGreaterThan(0);
    expect(content.trimStart()).toMatch(/^<!doctype html>|^<html|^<h1/i);
    expect(content).toContain("Tax Technical Memorandum");
    expect(content).toContain("Synthetic Tax Code § 10(1)");
    expect(content).toContain("Synthetic Tax Regulations 24(2)");
    expect(content).toContain("INR 1200000.00");
    expect(plainContent).toContain(toPlain(approvedProposalText));
    expect(plainContent).not.toContain(toPlain(rejectedProposalText));
    expect(plainContent).not.toContain(
      "Every fictional disposal is automatically exempt from tax.",
    );
    expect(plainContent).not.toContain("[object Object]");
    if (kind === "client") {
      expect(content).not.toContain("Unsupported-authority warnings");
      expect(content).not.toContain("Reviewer decision log");
    } else {
      for (const sourceId of [
        "COST-001",
        "PROCEEDS-001",
        "EXP-001",
        "EXP-002",
        "CALC-001",
      ])
        expect(content).toContain(sourceId);
    }
    await expect(page.getByText(sha256, { exact: true })).toBeVisible();
    exports.push({
      kind,
      name: download.suggestedFilename(),
      size: bytes.length,
      sha256,
    });
    const preview = await page.context().newPage();
    preview.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await preview.setContent(content);
    await expect(
      preview.getByRole("heading", { name: "Tax Technical Memorandum" }),
    ).toBeVisible();
    const layout = await preview.evaluate(() => ({
      horizontalOverflow:
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
      emptyVisibleElements: [
        ...document.body.querySelectorAll("h1,h2,p"),
      ].filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width === 0 || rect.height === 0;
      }).length,
      rawObjectText: document.body.innerText.includes("[object Object]"),
    }));
    expect(layout).toEqual({
      horizontalOverflow: false,
      emptyVisibleElements: 0,
      rawObjectText: false,
    });
    await preview.screenshot({
      path: resolve(evidenceDir, `06-${kind}-preview.png`),
      fullPage: true,
    });
    await preview.close();
  }
  await shot("05-exports-downloaded");
  expect(consoleErrors).toEqual([]);
  expect(httpFailures.filter((failure) => failure.status === 500)).toEqual([]);
  expect(corsFailures).toEqual([]);
  const ids = await page
    .locator("section")
    .filter({ hasText: "Uploaded documents" })
    .locator("small")
    .allTextContents();
  const evidence = {
    timestamp: new Date().toISOString(),
    mode: "Live",
    total_duration_ms: Date.now() - started,
    job_status: "awaiting_approval",
    job_duration_display: jobDurationText,
    uploaded_document_count: 4,
    upstream_document_ids: ids,
    quotation_verification: { total: 3, verified: 2, rejected: 1 },
    monetary_traceability: {
      traced: 6,
      unmatched_before_correction: 1,
      unmatched_after_correction: 0,
    },
    review: {
      proposal_ids: proposalIds,
      approved: 1,
      rejected: 1,
      notes: [approvedNote, rejectedNote],
      mandatory_pending: 0,
      duplicate_submission_suppressed_locally: true,
      upstream_approval_request_count: 1,
      upstream_idempotency_claimed: false,
    },
    exports,
    browser_hosts: [...browserHosts],
    console_error_count: consoleErrors.length,
    http_failure_count: httpFailures.length,
    http_500_count: httpFailures.filter((failure) => failure.status === 500)
      .length,
    cors_failure_count: corsFailures.length,
    final_status: "passed",
    contains_credentials: false,
    contains_signed_urls: false,
  };
  await writeFile(
    resolve(root, "docs/evidence/ui-live-superdocs-validation.json"),
    JSON.stringify(evidence, null, 2) + "\n",
  );
});
