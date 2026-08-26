import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clientsBehind,
  clientsOnVersion,
  ConsentEvidenceRequiredError,
  currentVersion,
  recordConsent,
  recordIssue,
  registerTemplateVersion,
  RegistryError,
  type VersionStore,
} from "./registry.js";

function freshStore(): VersionStore {
  return { template_versions: [], client_versions: [] };
}

test("registerTemplateVersion + currentVersion: a freshly registered version is current", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  const current = currentVersion(store, "agreement");
  assert.equal(current?.version, "v1");
  assert.equal(current?.superseded_by, null);
});

test("recordIssue: refuses to issue a template version that was never registered", () => {
  const store = freshStore();
  assert.throws(
    () => recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10"),
    RegistryError,
  );
});

test("recordIssue: succeeds once the template version is registered", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  const record = recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");
  assert.equal(record.consented_on, null);
  assert.equal(record.consent_evidence, null);
  assert.equal(store.client_versions.length, 1);
});

test("clientsOnVersion: reflects each client's most recent issuance, not their first", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  registerTemplateVersion(store, "agreement", "v2", "2023-01-01", ["RIA-AGR-01", "RIA-AI-01"], "content v2");
  recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");
  recordIssue(store, "CL-02", "agreement", "v1", "2020-01-01");
  recordIssue(store, "CL-02", "agreement", "v2", "2023-06-15"); // re-issued later

  assert.deepEqual(clientsOnVersion(store, "agreement", "v1"), ["CL-01"]);
  assert.deepEqual(clientsOnVersion(store, "agreement", "v2"), ["CL-02"]);
});

test("clientsBehind: a client only ever issued the superseded version is behind", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");
  registerTemplateVersion(store, "agreement", "v2", "2023-01-01", ["RIA-AGR-01", "RIA-AI-01"], "content v2");

  const behind = clientsBehind(store, "agreement");
  assert.equal(behind.length, 1);
  assert.equal(behind[0]!.client_id, "CL-01");
  assert.equal(behind[0]!.reason, "outdated_version_and_not_consented");
});

test("registerTemplateVersion: identical content is the same version, not a duplicate", () => {
  const store = freshStore();
  const first = registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "same content");
  const second = registerTemplateVersion(store, "agreement", "v1-retyped", "2015-04-01", ["RIA-AGR-01"], "same content");

  assert.equal(store.template_versions.length, 1);
  assert.equal(second.version, first.version); // "v1", not "v1-retyped" — the existing entry wins
  assert.equal(currentVersion(store, "agreement")?.superseded_by, null);
});

test("registerTemplateVersion: genuinely different content supersedes the old current version", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  registerTemplateVersion(store, "agreement", "v2", "2023-01-01", ["RIA-AGR-01", "RIA-AI-01"], "content v2");

  assert.equal(store.template_versions.length, 2);
  assert.equal(store.template_versions[0]!.superseded_by, "v2");
  assert.equal(currentVersion(store, "agreement")?.version, "v2");
});

test("recordConsent: refuses to record consent with no evidence (undefined, null, or blank)", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");

  assert.throws(
    () => recordConsent(store, "CL-01", "agreement", "v1", "2021-03-10", undefined),
    ConsentEvidenceRequiredError,
  );
  assert.throws(
    () => recordConsent(store, "CL-01", "agreement", "v1", "2021-03-10", null),
    ConsentEvidenceRequiredError,
  );
  assert.throws(
    () => recordConsent(store, "CL-01", "agreement", "v1", "2021-03-10", "   "),
    ConsentEvidenceRequiredError,
  );

  // None of the failed attempts left a partial write.
  assert.equal(store.client_versions[0]!.consented_on, null);
  assert.equal(store.client_versions[0]!.consent_evidence, null);
});

test("recordConsent: succeeds with evidence and sets both fields together", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  recordIssue(store, "CL-01", "agreement", "v1", "2021-03-10");

  const record = recordConsent(
    store,
    "CL-01",
    "agreement",
    "v1",
    "2021-03-10",
    "client-onboarding-notes.md:5",
  );
  assert.equal(record.consented_on, "2021-03-10");
  assert.equal(record.consent_evidence, "client-onboarding-notes.md:5");
});

test("recordConsent: refuses to consent to an issuance that doesn't exist", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  assert.throws(
    () => recordConsent(store, "CL-01", "agreement", "v1", "2021-03-10", "some-evidence.md:1"),
    RegistryError,
  );
});

test("clientsBehind: a client on the current version with nothing else wrong is not behind", () => {
  const store = freshStore();
  registerTemplateVersion(store, "agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "content v1");
  const record = recordIssue(store, "CL-04", "agreement", "v1", "2024-01-20");
  record.consented_on = "2024-01-20";
  record.consent_evidence = "client-onboarding-notes.md:33";

  assert.deepEqual(clientsBehind(store, "agreement"), []);
});
