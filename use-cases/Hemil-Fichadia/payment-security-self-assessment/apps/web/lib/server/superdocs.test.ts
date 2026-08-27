import assert from "node:assert/strict";
import test from "node:test";
import { syntheticFintechEvidence } from "@payment-security-self-assessment/evidence";
import {
  buildApprovalRequest,
  buildExportRequest,
  buildAssessmentInstruction,
  extractGeneratedHtml,
  mapSuperdocsHttpError,
  parseAsyncChatResponse,
  parseJobResponse,
  parseProposedChangeContent,
  parseUploadedDocument,
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

test("draft validation accepts an unknown control when evidence is insufficient to determine it", () => {
  const draft =
    "<p>The supplied evidence is insufficient to determine whether database backup encryption is independently verified.</p>";

  assert.equal(validateGeneratedDraft(draft, unknownBackupEncryptionEvidence), draft);
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

test("parses the documented uploaded-document response and carries its session into async chat", () => {
  assert.deepEqual(
    parseUploadedDocument({
      html: '<h1 data-chunk-id="title">Assessment</h1>',
      session_id: "assessment-session-1",
      filename: "assessment-template.html",
    }),
    {
      html: '<h1 data-chunk-id="title">Assessment</h1>',
      sessionId: "assessment-session-1",
    },
  );
  assert.deepEqual(
    parseAsyncChatResponse({ job_id: "job-1", session_id: "assessment-session-1", status: "pending" }),
    { jobId: "job-1", sessionId: "assessment-session-1" },
  );
});

test("parses pending review changes without treating them as approved HTML", () => {
  const job = parseJobResponse({
    job_id: "job-1",
    session_id: "assessment-session-1",
    status: "awaiting_approval",
    metadata: {
      pending_changes: [{
        change_id: "change-1",
        operation: "edit",
        chunk_id: "authentication-content",
        old_html: "<p>Draft pending.</p>",
        new_html: "<p>Administrator MFA is required.</p>",
      }],
    },
  });

  assert.equal(job.status, "awaiting_approval");
  assert.equal(job.pendingChanges?.[0]?.change_id, "change-1");
  assert.equal(job.updatedHtml, undefined);
});

test("approval explicitly approves the pending change batch", () => {
  assert.deepEqual(buildApprovalRequest("job-1", ["change-1", "change-2"]), {
    job_id: "job-1",
    approved: true,
    changes: [
      { change_id: "change-1", approved: true },
      { change_id: "change-2", approved: true },
    ],
  });
});

test("export is a DOCX session export and can only be requested by an approved workflow", () => {
  assert.deepEqual(buildExportRequest("assessment-session-1"), {
    session_id: "assessment-session-1",
    format: "docx",
    options: { filename: "payment-security-self-assessment.docx" },
  });
});
