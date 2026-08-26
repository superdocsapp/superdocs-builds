import assert from "node:assert/strict";
import { test } from "node:test";
import { rm } from "node:fs/promises";
import { OpsLedger } from "../budget.js";
import { SuperDocsClient } from "../client.js";
import type { Client } from "../domain/clients.js";
import { Logger } from "../logger.js";
import type { Requirement } from "../domain/requirements.js";
import { loadClients } from "../domain/clients.js";
import { loadRequirements } from "../domain/requirements.js";
import {
  latestClientVersion,
  recordConsent,
  recordIssue,
  registerTemplateVersion,
  type VersionStore,
} from "./registry.js";
import { applyAmendment, detectAmendments, extractClauseBody, scopeAmendment, spliceClauseBody } from "./amend.js";
import type { ChatResponse } from "../types.js";

/** A real client instance with chat() stubbed — avoids the private-field
 * issues of duck-typing SuperDocsClient, and never touches the network. */
function fakeClient(replyText: string): SuperDocsClient {
  const c = new SuperDocsClient("fake-key", new Logger(), null);
  c.chat = async (): Promise<ChatResponse> => ({
    response: replyText,
    session_id: "fake-session",
    document_changes: null,
    usage: null,
  });
  return c;
}

function fakeClientRecord(id: string, name: string): Client {
  return {
    id,
    name,
    onboarded_on: "2020-01-01",
    advisory_type: "individual",
    ai_assisted: true,
    agreement_version: "v2",
    risk_profile_reviewed_on: null,
  };
}

const SAMPLE_TEMPLATE = [
  "# Agreement",
  "",
  "5. Record Keeping",
  "   The Adviser shall maintain records.",
  "",
  "6. Use of AI Tools in Advice",
  "   Where the Adviser uses AI-assisted tools, disclosure applies.",
  "",
  "Signed: ______________________   Date: ______________",
].join("\n");

test("extractClauseBody: pulls just the body text under the given heading", () => {
  const body = extractClauseBody(SAMPLE_TEMPLATE, "6. Use of AI Tools in Advice");
  assert.equal(body, "Where the Adviser uses AI-assisted tools, disclosure applies.");
});

test("extractClauseBody: an unknown heading returns an empty string, not a crash", () => {
  assert.equal(extractClauseBody(SAMPLE_TEMPLATE, "99. Nonexistent Clause"), "");
});

test("spliceClauseBody: replaces only the target clause, leaving everything else untouched", () => {
  const updated = spliceClauseBody(
    SAMPLE_TEMPLATE,
    "6. Use of AI Tools in Advice",
    "Updated clause text with the new per-model tracing requirement.",
  );

  assert.match(updated, /5\. Record Keeping\n {3}The Adviser shall maintain records\./);
  assert.match(updated, /6\. Use of AI Tools in Advice\n {3}Updated clause text with the new per-model tracing requirement\./);
  assert.match(updated, /Signed: /);
  assert.doesNotMatch(updated, /disclosure applies/);
});

function req(overrides: Partial<Requirement> = {}): Requirement {
  return {
    id: "RIA-AI-01",
    citation: "SEBI ... Regulation 15(14) and 18(9)",
    title: "AI-assisted advice documented and disclosed",
    obligation: "Original obligation text.",
    evidence_expected: ["AI usage disclosure"],
    frequency: "continuous",
    applies_to: "advisory_clients",
    ...overrides,
  };
}

test("detectAmendments: identical registers produce no events", () => {
  const baseline = [req()];
  const updated = [req()];
  assert.deepEqual(detectAmendments(baseline, updated), []);
});

test("detectAmendments: a changed obligation text is a changed_obligation event", () => {
  const baseline = [req({ obligation: "Original obligation text." })];
  const updated = [req({ obligation: "Extended obligation text with a new clause." })];

  const events = detectAmendments(baseline, updated);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.kind, "changed_obligation");
  assert.equal(events[0]!.requirement_id, "RIA-AI-01");
  assert.equal(events[0]!.previous?.obligation, "Original obligation text.");
  assert.equal(events[0]!.updated.obligation, "Extended obligation text with a new clause.");
});

test("detectAmendments: a requirement id absent from baseline is new_requirement", () => {
  const baseline = [req({ id: "RIA-AI-01" })];
  const updated = [req({ id: "RIA-AI-01" }), req({ id: "RIA-NEW-01", title: "Brand new obligation" })];

  const events = detectAmendments(baseline, updated);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.kind, "new_requirement");
  assert.equal(events[0]!.requirement_id, "RIA-NEW-01");
  assert.equal(events[0]!.previous, null);
});

test("detectAmendments: unrelated requirements produce no events even when one changes", () => {
  const baseline = [req({ id: "RIA-AI-01" }), req({ id: "RIA-FEE-01", title: "Fee disclosure" })];
  const updated = [
    req({ id: "RIA-AI-01", obligation: "Extended obligation text." }),
    req({ id: "RIA-FEE-01", title: "Fee disclosure" }),
  ];

  const events = detectAmendments(baseline, updated);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.requirement_id, "RIA-AI-01");
});

test("detectAmendments: an empty baseline (first ever run) treats every requirement as new", () => {
  const updated = [req({ id: "RIA-AI-01" }), req({ id: "RIA-FEE-01" })];
  const events = detectAmendments([], updated);
  assert.equal(events.length, 2);
  assert.ok(events.every((e) => e.kind === "new_requirement"));
});

function seededStore(): VersionStore {
  // Mirrors the real corpus shape: v1 (agreement-only) is superseded by v2
  // (agreement + AI clause); non-AI clients stayed on v1, AI-assisted
  // clients are on v2.
  const store: VersionStore = { template_versions: [], client_versions: [] };
  registerTemplateVersion(store, "ria-advisory-agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "v1 content");
  registerTemplateVersion(
    store,
    "ria-advisory-agreement",
    "v2",
    "2023-01-01",
    ["RIA-AGR-01", "RIA-AI-01"],
    "v2 content",
  );
  recordIssue(store, "CL-01", "ria-advisory-agreement", "v1", "2021-03-10"); // non-AI
  recordIssue(store, "CL-02", "ria-advisory-agreement", "v2", "2023-06-15"); // AI-assisted
  recordIssue(store, "CL-04", "ria-advisory-agreement", "v2", "2024-01-20"); // AI-assisted
  return store;
}

test("scopeAmendment: only the template referencing the changed requirement, and only its current holders", () => {
  const store = seededStore();
  const event = {
    requirement_id: "RIA-AI-01",
    kind: "changed_obligation" as const,
    previous: req(),
    updated: req({ obligation: "Extended." }),
  };

  const scope = scopeAmendment(store, event);

  assert.deepEqual(scope.affected_template_ids, ["ria-advisory-agreement"]);
  // CL-01 is on v1, which doesn't reference RIA-AI-01 at all — not in scope.
  assert.deepEqual(scope.affected_client_ids, ["CL-02", "CL-04"]);
});

test("scopeAmendment: a requirement no current template references has an empty blast radius", () => {
  const store = seededStore();
  const event = {
    requirement_id: "RIA-NW-01", // firm-level, not on any client agreement template
    kind: "changed_obligation" as const,
    previous: req({ id: "RIA-NW-01" }),
    updated: req({ id: "RIA-NW-01", obligation: "Extended." }),
  };

  const scope = scopeAmendment(store, event);
  assert.deepEqual(scope.affected_template_ids, []);
  assert.deepEqual(scope.affected_client_ids, []);
});

test("applyAmendment: issues the new version and a notice only to clients on the affected version", async () => {
  const store: VersionStore = { template_versions: [], client_versions: [] };
  registerTemplateVersion(store, "ria-advisory-agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "v1 placeholder");
  registerTemplateVersion(
    store,
    "ria-advisory-agreement",
    "v2",
    "2023-01-01",
    ["RIA-AGR-01", "RIA-AI-01"],
    "v2 placeholder",
  );

  recordIssue(store, "CL-01", "ria-advisory-agreement", "v1", "2021-03-10"); // not on the affected version
  recordIssue(store, "CL-02", "ria-advisory-agreement", "v2", "2023-06-15"); // affected
  recordIssue(store, "CL-04", "ria-advisory-agreement", "v2", "2024-01-20"); // affected

  const clients = [
    fakeClientRecord("CL-01", "Ananya Rao"),
    fakeClientRecord("CL-02", "Vikram Deshmukh"),
    fakeClientRecord("CL-04", "Kunal Sharma"),
  ];

  const event = {
    requirement_id: "RIA-AI-01",
    kind: "changed_obligation" as const,
    previous: req(),
    updated: req({ obligation: "Extended obligation requiring per-model tracing." }),
  };

  const client = fakeClient("Stub amended clause body for testing.");
  const ledger = new OpsLedger(new Logger(), 25);

  try {
    const result = await applyAmendment(client, ledger, store, clients, event, "2026-08-22", "v3-test");

    assert.equal(result.newTemplateVersions.length, 1);
    assert.equal(result.newTemplateVersions[0]!.version, "v3-test");
    assert.equal(result.notices.length, 2);
    assert.deepEqual(
      result.notices.map((n) => n.client_id).sort(),
      ["CL-02", "CL-04"],
    );

    // CL-01 (unaffected) got no new issuance at all — still on v1.
    assert.equal(latestClientVersion(store, "CL-01", "ria-advisory-agreement")?.version, "v1");

    // CL-02 (affected) now has a pending new issuance.
    const cl02 = latestClientVersion(store, "CL-02", "ria-advisory-agreement");
    assert.equal(cl02?.version, "v3-test");
    assert.equal(cl02?.consented_on, null);
    assert.equal(cl02?.consent_evidence, null);

    const notice = result.notices.find((n) => n.client_id === "CL-02")!;
    assert.equal(notice.consent_status, "pending");
    assert.ok(notice.what_did_not_change.length > 0);
    assert.match(notice.new_text, /Stub amended clause body for testing/);
  } finally {
    await rm("state/templates/ria-advisory-agreement-v3-test.md", { force: true });
  }
});

// --- The centerpiece: unaffected clients are provably untouched ---------
//
// Not "should be" untouched by inspection — this asserts it, against the
// real corpus's requirements diff and the full 8-client roster, by
// snapshotting every non-AI client's client_versions rows as JSON strings
// before the amendment and requiring byte-for-byte string equality after.

test("amendment: unaffected (non-AI) clients are byte-identical before and after; only AI-assisted clients receive notices", async () => {
  const requirements = await loadRequirements();
  const updatedRequirements = await loadRequirements("./config/requirements-v2.yaml");
  const clients = await loadClients();

  const events = detectAmendments(requirements, updatedRequirements);
  assert.equal(events.length, 1, "the real requirements diff should produce exactly one amendment event");
  const event = events[0]!;
  assert.equal(event.requirement_id, "RIA-AI-01");

  // Reconstruct the store in the same shape the real seed produces: v1
  // (agreement only, superseded) and v2 (agreement + AI clause, current),
  // every real client issued and consented at their real agreement_version.
  const store: VersionStore = { template_versions: [], client_versions: [] };
  registerTemplateVersion(store, "ria-advisory-agreement", "v1", "2015-04-01", ["RIA-AGR-01"], "v1 placeholder");
  registerTemplateVersion(
    store,
    "ria-advisory-agreement",
    "v2",
    "2023-01-01",
    ["RIA-AGR-01", "RIA-AI-01"],
    "v2 placeholder",
  );
  for (const c of clients) {
    recordIssue(store, c.id, "ria-advisory-agreement", c.agreement_version, c.onboarded_on);
    recordConsent(store, c.id, "ria-advisory-agreement", c.agreement_version, c.onboarded_on, "seed-evidence.md:1");
  }

  const scope = scopeAmendment(store, event);
  const affectedIds = new Set(scope.affected_client_ids);
  const unaffectedClients = clients.filter((c) => !affectedIds.has(c.id));

  // The scoping mechanism (template-holding), not a hardcoded ai_assisted
  // filter, is what produced this split — confirm it lines up with reality
  // rather than assuming it.
  assert.deepEqual(
    unaffectedClients.map((c) => c.id).sort(),
    clients.filter((c) => !c.ai_assisted).map((c) => c.id).sort(),
  );
  assert.ok(unaffectedClients.length > 0 && affectedIds.size > 0, "test is vacuous unless both groups are non-empty");

  // Byte-identical snapshot of every unaffected client's rows, taken before
  // anything runs.
  const before = new Map(
    unaffectedClients.map((c) => [c.id, JSON.stringify(store.client_versions.filter((r) => r.client_id === c.id))]),
  );

  const client = fakeClient("Stub amended clause body reflecting the per-model tracing requirement.");
  const ledger = new OpsLedger(new Logger(), 25);

  try {
    const result = await applyAmendment(client, ledger, store, clients, event, "2026-08-22", "v3-test");

    // Only AI-assisted clients received a notice.
    assert.deepEqual(result.notices.map((n) => n.client_id).sort(), scope.affected_client_ids);
    assert.ok(result.notices.every((n) => clients.find((c) => c.id === n.client_id)?.ai_assisted === true));

    // The proof: every unaffected client's rows serialize to the exact
    // same JSON string after the amendment as before it.
    for (const c of unaffectedClients) {
      const after = JSON.stringify(store.client_versions.filter((r) => r.client_id === c.id));
      assert.equal(after, before.get(c.id), `${c.id}'s client_versions rows changed but should be byte-identical`);
    }

    // Not vacuous: the affected clients' rows DID change, into the new
    // version with consent pending.
    for (const clientId of scope.affected_client_ids) {
      const latest = latestClientVersion(store, clientId, "ria-advisory-agreement");
      assert.equal(latest?.version, "v3-test");
      assert.equal(latest?.consented_on, null);
      assert.equal(latest?.consent_evidence, null);
    }
  } finally {
    await rm("state/templates/ria-advisory-agreement-v3-test.md", { force: true });
  }
});
