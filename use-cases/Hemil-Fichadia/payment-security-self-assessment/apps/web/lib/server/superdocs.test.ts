import assert from "node:assert/strict";
import test from "node:test";
import { syntheticFintechEvidence } from "@payment-security-self-assessment/evidence";
import {
  buildAssessmentInstruction,
  extractGeneratedHtml,
  mapSuperdocsHttpError,
  parseProposedChangeContent,
  validateGeneratedDraft,
} from "./superdocs.ts";

test("assessment context preserves every evidence status", () => {
  const instruction = buildAssessmentInstruction(syntheticFintechEvidence);

  assert.match(instruction, /\[IMPLEMENTED\] Authentication: Administrator accounts currently require/);
  assert.match(instruction, /\[PLANNED\] Authentication: Multi-factor authentication will be extended/);
  assert.match(instruction, /\[UNKNOWN\] Access Control: The supplied evidence does not establish/);
});

test("planned workforce MFA is explicitly prohibited from becoming implemented", () => {
  const instruction = buildAssessmentInstruction(syntheticFintechEvidence);

  assert.match(instruction, /workforce-wide MFA is planned for Q4 2026/i);
  assert.match(instruction, /Do not state or imply that workforce-wide MFA is currently implemented/i);
});

test("draft validation rejects an unqualified workforce MFA claim", () => {
  assert.throws(
    () =>
      validateGeneratedDraft(
        "<p>Workforce MFA is currently implemented. Privileged access reviews are unknown.</p>",
        syntheticFintechEvidence,
      ),
    /did not preserve required evidence qualifiers/i,
  );
});

test("draft validation rejects a current workforce MFA claim alongside future work", () => {
  assert.throws(
    () =>
      validateGeneratedDraft(
        "<p>Workforce MFA is currently required and planned for Q4 2026. Privileged access reviews are unknown.</p>",
        syntheticFintechEvidence,
      ),
    /did not preserve required evidence qualifiers/i,
  );
});

test("unknown evidence is explicitly described as unsupported", () => {
  const instruction = buildAssessmentInstruction(syntheticFintechEvidence);

  assert.match(instruction, /limitation of the supplied evidence/i);
  assert.match(instruction, /Lack of supplied evidence is not proof that the control is absent/i);
});

const unknownBackupEncryptionEvidence = [
  {
    id: "unknown-backup-encryption",
    category: "ENCRYPTION" as const,
    statement:
      "No evidence was provided to confirm whether database backup encryption is independently verified.",
    status: "UNKNOWN" as const,
    sourceDocumentId: "05-mixed-evidence",
    sourceDocumentName: "05-mixed-evidence.txt",
  },
];

test("draft validation accepts an unknown control narrated as an evidence limitation", () => {
  assert.equal(
    validateGeneratedDraft(
      "<p>The supplied evidence does not establish whether database backup encryption is independently verified.</p>",
      unknownBackupEncryptionEvidence,
    ),
    "<p>The supplied evidence does not establish whether database backup encryption is independently verified.</p>",
  );
});

test("draft validation rejects an unknown control converted into an unsupported negative claim", () => {
  for (const unsupportedClaim of [
    "<p>The supplied evidence does not establish whether database backup encryption is independently verified. Database backup encryption verification is not implemented.</p>",
    "<p>The supplied evidence does not establish whether database backup encryption is independently verified. Database backup encryption verification is not established.</p>",
  ]) {
    assert.throws(
      () => validateGeneratedDraft(unsupportedClaim, unknownBackupEncryptionEvidence),
      /did not preserve required evidence qualifiers/i,
    );
  }
});

test("draft validation preserves the incident-response unknown as an evidence limitation", () => {
  const facts = [
    {
      id: "unknown-tabletop-exercise",
      category: "INCIDENT_RESPONSE" as const,
      statement:
        "The supplied evidence cannot establish whether a formal tabletop incident-response exercise is performed annually.",
      status: "UNKNOWN" as const,
      sourceDocumentId: "05-mixed-evidence",
      sourceDocumentName: "05-mixed-evidence.txt",
    },
  ];

  assert.doesNotThrow(() =>
    validateGeneratedDraft(
      "<p>The available evidence does not confirm whether a formal tabletop incident-response exercise is performed annually.</p>",
      facts,
    ),
  );
});

test("proposed-change content supports the documented JSON double-parse", () => {
  const change = parseProposedChangeContent(
    JSON.stringify(
      JSON.stringify({
        change_id: "change-1",
        operation: "edit",
        chunk_id: "authentication-content",
        new_html: "<p>Draft</p>",
      }),
    ),
  );

  assert.deepEqual(change, {
    change_id: "change-1",
    operation: "edit",
    chunk_id: "authentication-content",
    new_html: "<p>Draft</p>",
  });
});

test("extracts generated HTML from the documented synchronous chat response", () => {
  assert.equal(
    extractGeneratedHtml({
      response: "Draft complete",
      document_changes: { updated_html: "<h1>Assessment</h1>", changes: [] },
    }),
    "<h1>Assessment</h1>",
  );
});

test("authentication errors never expose authorization data", () => {
  const error = mapSuperdocsHttpError(401);

  assert.equal(error.code, "AUTHENTICATION");
  assert.doesNotMatch(error.message, /bearer|authorization|sk_/i);
});
