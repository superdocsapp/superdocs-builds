import assert from "node:assert/strict";
import { test } from "node:test";
import type { Client } from "../domain/clients.js";
import { recordConsent, recordIssue, registerTemplateVersion, type VersionStore } from "./registry.js";
import { buildConsentMatrix, formatConsentMatrixTable } from "./report.js";

function client(id: string, name: string): Client {
  return {
    id,
    name,
    onboarded_on: "2020-01-01",
    advisory_type: "individual",
    ai_assisted: false,
    agreement_version: "v1",
    risk_profile_reviewed_on: null,
  };
}

test("buildConsentMatrix: covers current+consented, behind, and never-issued in one pass", () => {
  const store: VersionStore = { template_versions: [], client_versions: [] };
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");
  recordConsent(store, "CL-01", "agreement", "v1", "2021-03-10", "notes.md:5");
  registerTemplateVersion(store, "agreement", "v2", "2023-01-01", ["RIA-AGR-01", "RIA-AI-01"], "content v2");
  recordIssue(store, "CL-02", "agreement", "v2", "2023-06-15");
  recordConsent(store, "CL-02", "agreement", "v2", "2023-06-15", "notes.md:20");

  const clients = [client("CL-01", "Ananya Rao"), client("CL-02", "Vikram Deshmukh"), client("CL-03", "Meera Family Trust")];
  const matrix = buildConsentMatrix(store, clients);

  assert.deepEqual(matrix.templates, ["agreement"]);
  assert.equal(matrix.rows[0]!.cells[0]!.status, "BEHIND"); // CL-01 still on v1, v2 is current
  assert.equal(matrix.rows[1]!.cells[0]!.status, "CURRENT_CONSENTED"); // CL-02 on v2
  assert.equal(matrix.rows[2]!.cells[0]!.status, "NOT_ISSUED"); // CL-03 never issued anything

  const table = formatConsentMatrixTable(matrix);
  assert.match(table, /BEHIND \(current: v2\), consented 2021-03-10/);
  assert.match(table, /current, consented 2023-06-15/);
  assert.match(table, /NOT ISSUED/);
});

test("formatConsentMatrixTable: an empty store still renders without a template column", () => {
  const store: VersionStore = { template_versions: [], client_versions: [] };
  const matrix = buildConsentMatrix(store, [client("CL-01", "Ananya Rao")]);
  assert.equal(formatConsentMatrixTable(matrix), "(no template versions registered yet)");
});
