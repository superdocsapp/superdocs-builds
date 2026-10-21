import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { loadLocalEnv } from "../src/config/env.js";
import { SuperDocsIntegration, emptySuperDocsState } from "../src/superdocs/integration.js";

loadLocalEnv();

if (!process.env.SUPERDOCS_API_KEY) {
  console.log("SUPERDOCS_API_KEY is not configured. Live SuperDocs smoke test is intentionally skipped.");
  process.exit(0);
}

const integration = new SuperDocsIntegration();
const probe = await integration.probe();
console.log(`Authenticated: ${probe.authenticated} (HTTP ${probe.status})`);
if (!probe.authenticated) throw new Error("SuperDocs authentication failed.");

const html = `<h1 data-chunk-id="demo-title">Translation QA Smoke Test</h1><p data-chunk-id="demo-p1">Keep the named term Starfall unchanged.</p>`;
const state = await integration.prepareDocument(
  emptySuperDocsState(),
  html,
  "translation-qa-smoke.html",
  "Preserve the named term Starfall and make only the narrowly requested translation-preparation change. Return a reviewable proposal.",
);
console.log(`Job: ${state.jobId ?? "n/a"}`);
console.log(`Status: ${state.status}`);
console.log(`Proposed changes: ${state.pendingChanges.length}`);

let finalState = state;
if (state.status === "awaiting_approval" && state.pendingChanges.length) {
  finalState = await integration.approve(
    state,
    state.pendingChanges.map((change) => ({ changeId: String(change.changeId ?? change.change_id), approved: true })),
  );
  console.log(`After approval: ${finalState.status}`);
}

if (!finalState.sessionId) throw new Error("SuperDocs did not return a session id.");
const output = await integration.exportDocx(finalState);
const outDir = join(process.cwd(), "run-artifacts", "superdocs-smoke");
mkdirSync(outDir, { recursive: true });
const outputPath = join(outDir, "reviewed.docx");
writeFileSync(outputPath, Buffer.from(await output.arrayBuffer()));
console.log(`Exported: ${outputPath}`);
