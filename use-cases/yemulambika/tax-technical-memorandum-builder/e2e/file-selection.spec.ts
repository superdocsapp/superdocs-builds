import { expect, test } from "@playwright/test";
import { SYNTHETIC_DOCUMENT_ORDER } from "../src/file-selection";

const input = (name: string) => ({
  name,
  mimeType: name.endsWith(".html") ? "text/html" : "text/plain",
  buffer: Buffer.from(`Synthetic fixture content for ${name}`),
});

test("FileList permutations upload canonically and invalid sets upload nothing", async ({
  browser,
}) => {
  for (const names of [
    [...SYNTHETIC_DOCUMENT_ORDER].sort(),
    [...SYNTHETIC_DOCUMENT_ORDER].reverse(),
    [...SYNTHETIC_DOCUMENT_ORDER],
  ]) {
    const page = await browser.newPage();
    const uploadedNames: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/documents"))
        uploadedNames.push((request.postDataJSON() as { name: string }).name);
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Start new tax memorandum case" })
      .click();
    await page
      .getByLabel("Synthetic document files")
      .setInputFiles(names.map(input));
    await page.getByRole("button", { name: "Upload four documents" }).click();
    await expect(
      page.locator("section p", { hasText: "— UPLOADED" }),
    ).toHaveCount(4);
    expect(uploadedNames).toEqual(SYNTHETIC_DOCUMENT_ORDER);
    await page.close();
  }

  const invalidSelections = [
    {
      names: SYNTHETIC_DOCUMENT_ORDER.slice(0, 3),
      messages: ["Missing: synthetic-tax-memo.html"],
    },
    {
      names: [
        "synthetic-client-facts.txt",
        "synthetic-client-facts.txt",
        "synthetic-authority-1.txt",
        "synthetic-authority-2.txt",
      ],
      messages: [
        "Missing: synthetic-tax-memo.html",
        "Duplicate: synthetic-client-facts.txt",
      ],
    },
    {
      names: [
        "synthetic-client-facts.txt",
        "synthetic-authority-1.txt",
        "synthetic-authority-2.txt",
        "surprise.txt",
      ],
      messages: [
        "Missing: synthetic-tax-memo.html",
        "Unexpected: surprise.txt",
      ],
    },
  ];
  for (const selection of invalidSelections) {
    const page = await browser.newPage();
    let uploadRequests = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/documents"))
        uploadRequests += 1;
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Start new tax memorandum case" })
      .click();
    await page
      .getByLabel("Synthetic document files")
      .setInputFiles(selection.names.map(input));
    const alert = page.getByRole("alert");
    for (const message of selection.messages)
      await expect(alert).toContainText(message);
    await expect(
      page.getByRole("button", { name: "Upload four documents" }),
    ).toBeDisabled();
    expect(uploadRequests).toBe(0);
    await page.close();
  }
});
