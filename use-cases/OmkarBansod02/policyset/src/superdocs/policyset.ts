import { createHash } from "node:crypto";

import {
  POLICY_DOCUMENT_TYPES,
  getAffectedDocuments,
  htmlToPolicyText,
  returnWindowValues,
  type ChangeSet,
  type PolicyDocumentType,
  type PolicyProfile,
} from "@/domain";
import {
  POLICY_DOCUMENT_FILENAMES,
  POLICY_DOCUMENT_TITLES,
  generatePolicyDocuments,
} from "@/documents";
import type {
  PolicyDocumentContentStateMap,
  SuperDocsJobView,
  SuperDocsProposal,
  SuperDocsReviewView,
  SuperDocsSessionDocumentView,
  SuperDocsSynchronizedStartView,
  SuperDocsTargetedJob,
  SuperDocsWorkspaceSession,
} from "@/app/policyset/superdocs-contract";

import { SuperDocsClient, createSessionId } from "./client";
import { getSuperDocsApiKey } from "./config";
import { SuperDocsRequestError } from "./errors";
import { evaluateReturnWindowCoverage } from "./managed-coverage";
import {
  classifyProposalTarget,
  persistPendingProposalEvidence,
  type ProposalEvidenceOptions,
} from "./proposal-evidence";
import type {
  ExportArtifact,
  ExportFormat,
  JobSnapshot,
  PendingChange,
} from "./types";

type PolicySetSuperDocsClient = Pick<
  SuperDocsClient,
  | "uploadDocx"
  | "startChat"
  | "getJob"
  | "submitReview"
  | "listSessionDocuments"
>;

type PolicySetExportClient = Pick<
  SuperDocsClient,
  "listSessionDocuments" | "exportFocusedDocument"
>;

export type PolicyDocumentExport = {
  artifact: ExportArtifact;
  filename: string;
};

export class PolicySetSuperDocsSafetyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PolicySetSuperDocsSafetyError";
  }
}

/**
 * Thrown when one targeted job started successfully but a later targeted start
 * failed. Carries the jobs SuperDocs already created so the caller can record
 * and settle them instead of losing their ids. This type performs no recovery
 * of its own: nothing is approved, denied, cancelled, or retried here.
 */
export class PolicySetSynchronizedStartError extends Error {
  readonly successfullyStartedJobs: readonly SuperDocsTargetedJob[];
  readonly failedDocumentType: PolicyDocumentType;
  readonly requestError: SuperDocsRequestError | null;

  constructor(options: {
    successfullyStartedJobs: readonly SuperDocsTargetedJob[];
    failedDocumentType: PolicyDocumentType;
    cause: unknown;
  }) {
    const started = options.successfullyStartedJobs
      .map((job) => job.documentType)
      .join(", ");
    super(
      `SuperDocs refused to start the ${options.failedDocumentType} targeted job after ${
        started || "no"
      } job(s) had already started. Nothing was approved and the canonical return window remains unchanged. Do not retry this operation automatically.`,
      { cause: options.cause },
    );
    this.name = "PolicySetSynchronizedStartError";
    this.successfullyStartedJobs = options.successfullyStartedJobs;
    this.failedDocumentType = options.failedDocumentType;
    this.requestError =
      options.cause instanceof SuperDocsRequestError ? options.cause : null;
  }
}

export function createPolicySetSuperDocsClient(): SuperDocsClient {
  return new SuperDocsClient({ apiKey: getSuperDocsApiKey() });
}

export async function initializePolicySetSession(
  profile: PolicyProfile,
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
  sessionId = createSessionId(),
): Promise<SuperDocsWorkspaceSession> {
  const generated = await generatePolicyDocuments(profile);
  const documentIds = {} as Record<PolicyDocumentType, string>;

  for (const document of generated.documents) {
    const uploaded = await client.uploadDocx({
      sessionId,
      filename: document.filename,
      bytes: document.bytes,
      openMode: document.documentType === "terms" ? "replace" : "background",
    });
    documentIds[document.documentType] = uploaded.identity.documentId;
  }

  return { sessionId, documentIds };
}

export async function exportPolicyDocument(
  input: {
    sessionId: string;
    documentType: PolicyDocumentType;
    documentId: string;
    documentIds: Record<PolicyDocumentType, string>;
    format: ExportFormat;
    companyName: string;
  },
  client: PolicySetExportClient = createPolicySetSuperDocsClient(),
): Promise<PolicyDocumentExport> {
  assertDocumentMap(input.documentIds);

  const mappedDocumentId = input.documentIds[input.documentType];
  if (mappedDocumentId !== input.documentId) {
    throw new PolicySetSuperDocsSafetyError(
      "The requested document does not match the current PolicySet session map.",
    );
  }

  const documents = await client.listSessionDocuments(input.sessionId, {
    includeHtml: false,
  });
  const authoritativeIds = new Set(
    documents.map((document) => document.identity.documentId),
  );
  const mappedIds = POLICY_DOCUMENT_TYPES.map(
    (documentType) => input.documentIds[documentType],
  );
  if (
    documents.length !== POLICY_DOCUMENT_TYPES.length ||
    authoritativeIds.size !== POLICY_DOCUMENT_TYPES.length ||
    mappedIds.some((documentId) => !authoritativeIds.has(documentId))
  ) {
    throw new PolicySetSuperDocsSafetyError(
      "The requested document map does not match the authoritative SuperDocs session.",
    );
  }

  const target = documents.find(
    (document) => document.identity.documentId === mappedDocumentId,
  );
  if (!target) {
    throw new PolicySetSuperDocsSafetyError(
      "The requested document does not belong to the current PolicySet session.",
    );
  }

  const filename = policyDocumentExportFilename(
    input.companyName,
    input.documentType,
    input.format,
  );
  const artifact = await client.exportFocusedDocument(target.identity, {
    format: input.format,
    filename,
  });
  return { artifact, filename };
}

export function policyDocumentExportFilename(
  companyName: string,
  documentType: PolicyDocumentType,
  format: ExportFormat,
): string {
  const company =
    sanitizeFilenameComponent(
      companyName.replace(
        /\s+(?:llc|pllc|inc(?:orporated)?|corp(?:oration)?|ltd|limited)\.?$/i,
        "",
      ),
    ) || "policyset";
  const document = POLICY_DOCUMENT_FILENAMES[documentType].replace(/\.docx$/, "");
  return `${company}-${document}.${format}`;
}

export async function startPolicyDocumentEdit(
  input: {
    sessionId: string;
    documentId: string;
    instruction: string;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<SuperDocsJobView> {
  const reference = await client.startChat({
    sessionId: input.sessionId,
    message: input.instruction,
    documentId: input.documentId,
  });
  if (reference.sessionId !== input.sessionId) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs returned an edit job for a different session.",
    );
  }

  return {
    jobId: reference.jobId,
    sessionId: reference.sessionId,
    status: reference.status,
    progress: null,
    proposals: [],
    errorCode: null,
  };
}

/**
 * Starts one explicit, pinned (`document_id`-targeted) SuperDocs chat job per
 * affected document instead of a single unpinned multi-document job. Live
 * evidence showed an unpinned job can nondeterministically omit a named
 * document and pad its batch with no-op proposals — see
 * `SUPERDOCS_ISSUES.md`. The affected set always comes from
 * `changeSet.affectedDocuments`, which `assertChangeSetMatchesRegistry`
 * verifies against `DEPENDENCY_REGISTRY`.
 */
export async function startPolicySynchronizedEdit(
  input: {
    sessionId: string;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<SuperDocsSynchronizedStartView> {
  assertChangeSetMatchesRegistry(input.changeSet);
  const authoritative = await getPolicySetSessionDocuments(
    input.sessionId,
    client,
  );
  const preEditState = capturePolicyDocumentState(
    authoritative,
    input.documentIds,
  );

  const targetedDocumentTypes = POLICY_DOCUMENT_TYPES.filter((documentType) =>
    input.changeSet.affectedDocuments.includes(documentType),
  );

  const jobs: SuperDocsTargetedJob[] = [];
  for (const documentType of targetedDocumentTypes) {
    let reference;
    try {
      reference = await client.startChat({
        sessionId: input.sessionId,
        documentId: input.documentIds[documentType],
        message: buildTargetedSynchronizedInstruction(
          input.changeSet,
          documentType,
        ),
      });
    } catch (error) {
      // Jobs SuperDocs already created must not be lost with the stack. The
      // caller decides what to do with them; we only preserve them.
      if (jobs.length > 0) {
        throw new PolicySetSynchronizedStartError({
          successfullyStartedJobs: jobs,
          failedDocumentType: documentType,
          cause: error,
        });
      }
      throw error;
    }
    if (reference.sessionId !== input.sessionId) {
      throw new PolicySetSuperDocsSafetyError(
        "SuperDocs returned a synchronized edit job for a different session.",
      );
    }
    jobs.push({
      documentType,
      job: {
        jobId: reference.jobId,
        sessionId: reference.sessionId,
        status: reference.status,
        progress: null,
        proposals: [],
        errorCode: null,
      },
    });
  }

  return { jobs, preEditState };
}

/**
 * Polls one targeted job. When it reaches `awaiting_approval` with proposals,
 * runs that document's own targeting-safety and coverage gate before the
 * caller is allowed to treat the batch as reviewable. A gate failure denies
 * every pending change on THIS job only; orchestrating the sibling job (deny
 * it too, mark the whole ChangeSet failed) is the caller's job, since only
 * the caller knows about every job in the synchronized batch.
 */
export async function getPolicyTargetedSynchronizedJob(
  input: {
    jobId: string;
    sessionId: string;
    documentType: PolicyDocumentType;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
  evidenceOptions: ProposalEvidenceOptions = {},
): Promise<SuperDocsJobView> {
  const snapshot = await client.getJob(input.jobId);
  assertJobSession(snapshot, input.sessionId);

  if (
    snapshot.reference.status === "awaiting_approval" &&
    snapshot.pendingChanges.length > 0
  ) {
    await captureProposalEvidence(snapshot, evidenceOptions);
    try {
      await assertTargetedProposalGate(
        {
          sessionId: input.sessionId,
          documentType: input.documentType,
          pendingChanges: snapshot.pendingChanges,
          changeSet: input.changeSet,
          documentIds: input.documentIds,
        },
        client,
      );
    } catch (error) {
      try {
        await denyEveryPendingChange(snapshot, input.sessionId, client);
      } catch {
        throw new PolicySetSuperDocsSafetyError(
          `Safety gate blocked the ${input.documentType} batch, but SuperDocs did not confirm the explicit denials. Nothing was approved and the canonical return window remains unchanged. Do not retry this operation automatically.`,
        );
      }
      throw error;
    }
  }

  return jobView(snapshot);
}

/**
 * Submits an approve/deny decision for one targeted job's pending changes.
 * On approval this re-runs the targeted gate as a defense-in-depth check
 * before submitting. Callers are responsible for only calling this with
 * `approved: true` once every job in the synchronized batch has independently
 * passed its own gate.
 */
export async function submitPolicyTargetedSynchronizedReview(
  input: {
    jobId: string;
    sessionId: string;
    documentType: PolicyDocumentType;
    documentIds: Record<PolicyDocumentType, string>;
    changeSet: ChangeSet;
    approved: boolean;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
  evidenceOptions: ProposalEvidenceOptions = {},
): Promise<SuperDocsReviewView> {
  const snapshot = await client.getJob(input.jobId);
  assertJobSession(snapshot, input.sessionId);
  if (snapshot.reference.status !== "awaiting_approval") {
    throw new PolicySetSuperDocsSafetyError(
      "This synchronized SuperDocs job is not awaiting a review decision.",
    );
  }
  if (snapshot.pendingChanges.length === 0) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs has not provided a reviewable synchronized change batch yet.",
    );
  }
  await captureProposalEvidence(snapshot, evidenceOptions);
  if (input.approved) {
    try {
      await assertTargetedProposalGate(
        {
          sessionId: input.sessionId,
          documentType: input.documentType,
          pendingChanges: snapshot.pendingChanges,
          changeSet: input.changeSet,
          documentIds: input.documentIds,
        },
        client,
      );
    } catch (error) {
      try {
        await denyEveryPendingChange(snapshot, input.sessionId, client);
      } catch {
        throw new PolicySetSuperDocsSafetyError(
          `Safety gate blocked the ${input.documentType} batch, but SuperDocs did not confirm the explicit denials. Nothing was approved and the canonical return window remains unchanged. Do not retry this operation automatically.`,
        );
      }
      throw error;
    }
  }

  const decisions = snapshot.pendingChanges.map((change) => ({
    changeId: change.changeId,
    approved: input.approved,
  }));
  const receipt = await client.submitReview({
    sessionId: input.sessionId,
    jobId: input.jobId,
    decisions,
  });
  return { ...receipt, decisionCount: decisions.length };
}

export async function getPolicyDocumentEditJob(
  input: { jobId: string; sessionId: string; selectedDocumentId: string },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<SuperDocsJobView> {
  const snapshot = await client.getJob(input.jobId);
  assertJobSession(snapshot, input.sessionId);
  assertPendingChangesTargetDocument(
    snapshot.pendingChanges,
    input.selectedDocumentId,
  );
  return jobView(snapshot);
}

export async function submitPolicyDocumentReview(
  input: {
    jobId: string;
    sessionId: string;
    selectedDocumentId: string;
    approved: boolean;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<SuperDocsReviewView> {
  const snapshot = await client.getJob(input.jobId);
  assertJobSession(snapshot, input.sessionId);
  if (snapshot.reference.status !== "awaiting_approval") {
    throw new PolicySetSuperDocsSafetyError(
      "This SuperDocs job is not awaiting a review decision.",
    );
  }
  if (snapshot.pendingChanges.length === 0) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs has not provided a reviewable change batch yet.",
    );
  }
  assertPendingChangesTargetDocument(
    snapshot.pendingChanges,
    input.selectedDocumentId,
  );

  const decisions = snapshot.pendingChanges.map((change) => ({
    changeId: change.changeId,
    approved: input.approved,
  }));
  const receipt = await client.submitReview({
    sessionId: input.sessionId,
    jobId: input.jobId,
    decisions,
  });

  return { ...receipt, decisionCount: decisions.length };
}

export async function getPolicySetSessionDocuments(
  sessionId: string,
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<readonly SuperDocsSessionDocumentView[]> {
  const documents = await client.listSessionDocuments(sessionId, {
    includeHtml: true,
  });
  return documents.map((document) => {
    const normalizedContent =
      document.html === null ? null : normalizePolicyContent(document.html);
    return {
      documentId: document.identity.documentId,
      title: document.title,
      html: document.html,
      normalizedContent,
      sha256:
        normalizedContent === null ? null : sha256Hex(normalizedContent),
    };
  });
}

/**
 * Builds the chat instruction for one pinned, per-document targeted job.
 * Every job still names the other PolicySet documents and asks SuperDocs not
 * to touch them; pinning via `document_id` is the actual enforcement, this
 * is defense-in-depth guidance for the model plus a readable audit trail.
 */
export function buildTargetedSynchronizedInstruction(
  changeSet: ChangeSet,
  documentType: PolicyDocumentType,
): string {
  assertChangeSetMatchesRegistry(changeSet);
  if (changeSet.fieldPath !== "returns.windowDays") {
    throw new PolicySetSuperDocsSafetyError(
      "This phase only supports synchronized return-window changes.",
    );
  }
  if (!changeSet.affectedDocuments.includes(documentType)) {
    throw new PolicySetSuperDocsSafetyError(
      `"${documentType}" is not an affected document for this ChangeSet.`,
    );
  }

  const title = POLICY_DOCUMENT_TITLES[documentType];
  const otherTitles = POLICY_DOCUMENT_TYPES
    .filter((type) => type !== documentType)
    .map((type) => POLICY_DOCUMENT_TITLES[type]);
  const previous = changeSet.previousValue;
  const next = changeSet.nextValue;

  return [
    `Change the managed return window from ${previous} days to ${next} days in ${title}.`,
    `Update every occurrence of the return window in ${title}'s body policy prose, including "within ${previous} days of delivery" and "${previous}-day window".`,
    `Leave no ${previous}-day return window anywhere in ${title}.`,
    ...otherTitles.map((otherTitle) => `Do not modify ${otherTitle}.`),
    "Do not change any other numeric value, including refund processing days and warranty duration.",
    "Do not modify unrelated terms.",
    "Do not modify headers or footers.",
  ].join("\n");
}

/**
 * Checks that a proposal batch's documents, operations, and values are safe.
 * `changeSet.affectedDocuments` is the exact expected document set for this
 * check — callers that want a single-document check pass a `changeSet`
 * narrowed to that one document (see `assertTargetedProposalGate`); the
 * dependency-registry match itself is validated separately by
 * `assertChangeSetMatchesRegistry`, once, against the real (unnarrowed)
 * ChangeSet.
 */
export function assertSynchronizedProposalSafety(
  pendingChanges: readonly PendingChange[],
  changeSet: ChangeSet,
  documentIds: Record<PolicyDocumentType, string>,
): void {
  assertDocumentMap(documentIds);
  if (pendingChanges.length === 0) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs returned no synchronized proposals. Nothing was approved.",
    );
  }

  const documentTypeById = new Map(
    POLICY_DOCUMENT_TYPES.map((documentType) => [
      documentIds[documentType],
      documentType,
    ]),
  );
  const proposedTypes = new Set<PolicyDocumentType>();
  const previousValue = requireWindowValue(
    changeSet.previousValue,
    "previous",
  );
  const nextValue = requireWindowValue(changeSet.nextValue, "next");

  for (const change of pendingChanges) {
    const documentType = documentTypeById.get(change.documentId);
    if (!change.documentId || !documentType) {
      throw new PolicySetSuperDocsSafetyError(
        "Safety gate blocked the batch because a proposal has an unknown document identity. Every pending proposal was denied; the canonical return window remains unchanged.",
      );
    }
    proposedTypes.add(documentType);
    if (change.operation !== "edit") {
      throw new PolicySetSuperDocsSafetyError(
        "Safety gate blocked a create/delete proposal. Every pending proposal was denied; the canonical return window remains unchanged.",
      );
    }
    const target = classifyProposalTarget(change);
    if (target.target === "header" || target.target === "footer") {
      throw new PolicySetSuperDocsSafetyError(
        `Safety gate blocked a structurally identified ${target.target} proposal: ${target.reason} Every pending proposal was denied; the canonical return window remains unchanged.`,
      );
    }
    const oldValues = returnWindowValues(change.oldHtml ?? "");
    const newValues = returnWindowValues(change.newHtml ?? "");
    if (
      !oldValues.includes(previousValue) ||
      !newValues.includes(nextValue) ||
      newValues.includes(previousValue)
    ) {
      throw new PolicySetSuperDocsSafetyError(
        `Safety gate could not verify a ${previousValue}-day to ${nextValue}-day return-window edit. Every pending proposal was denied; the canonical return window remains unchanged.`,
      );
    }
  }

  const expectedTypes = new Set(changeSet.affectedDocuments);
  if (!setsEqual(proposedTypes, expectedTypes)) {
    throw new PolicySetSuperDocsSafetyError(
      "Safety gate blocked the batch because proposals did not exactly cover every affected PolicySet document. Every pending proposal was denied; the canonical return window remains unchanged.",
    );
  }
}

/**
 * The full approval gate: targeting safety (which documents and structural
 * parts the batch touches) plus completeness (every required managed occurrence
 * of the fact is updated). Both must pass before any change_id is approved.
 */
export async function assertSynchronizedProposalGate(
  input: {
    sessionId: string;
    pendingChanges: readonly PendingChange[];
    changeSet: ChangeSet;
    documentIds: Record<PolicyDocumentType, string>;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<void> {
  assertChangeSetMatchesRegistry(input.changeSet);
  assertSynchronizedProposalSafety(
    input.pendingChanges,
    input.changeSet,
    input.documentIds,
  );
  const documents = await getPolicySetSessionDocuments(input.sessionId, client);
  assertSynchronizedProposalCoverage(
    input.pendingChanges,
    input.changeSet,
    input.documentIds,
    documents,
  );
}

/**
 * The per-document approval gate for one targeted job: validates the real
 * ChangeSet against the dependency registry, then narrows both the safety
 * and coverage checks to `documentType` only. A pinned job's proposals
 * should already all target this one document — narrowing makes that an
 * enforced property (any proposal for another document fails the safety
 * check) rather than an assumption.
 */
export async function assertTargetedProposalGate(
  input: {
    sessionId: string;
    documentType: PolicyDocumentType;
    pendingChanges: readonly PendingChange[];
    changeSet: ChangeSet;
    documentIds: Record<PolicyDocumentType, string>;
  },
  client: PolicySetSuperDocsClient = createPolicySetSuperDocsClient(),
): Promise<void> {
  assertChangeSetMatchesRegistry(input.changeSet);
  if (!input.changeSet.affectedDocuments.includes(input.documentType)) {
    throw new PolicySetSuperDocsSafetyError(
      `"${input.documentType}" is not an affected document for this ChangeSet.`,
    );
  }
  const scopedChangeSet: ChangeSet = {
    ...input.changeSet,
    affectedDocuments: [input.documentType],
  };
  assertSynchronizedProposalSafety(
    input.pendingChanges,
    scopedChangeSet,
    input.documentIds,
  );
  const documents = await getPolicySetSessionDocuments(input.sessionId, client);
  assertSynchronizedProposalCoverage(
    input.pendingChanges,
    scopedChangeSet,
    input.documentIds,
    documents,
  );
}

/**
 * Completeness gate. `documents` is the authoritative pre-approval roster:
 * SuperDocs has not applied anything yet, so it still carries the previous
 * managed value and the chunk ids a proposal must target.
 * `changeSet.affectedDocuments` defines the exact scope checked here too —
 * pass a narrowed ChangeSet for a single-document check (see
 * `assertTargetedProposalGate`).
 */
export function assertSynchronizedProposalCoverage(
  pendingChanges: readonly PendingChange[],
  changeSet: ChangeSet,
  documentIds: Record<PolicyDocumentType, string>,
  documents: readonly SuperDocsSessionDocumentView[],
): void {
  assertDocumentMap(documentIds);

  const byId = new Map(
    documents.map((document) => [document.documentId, document]),
  );
  const documentHtml: Partial<Record<PolicyDocumentType, string>> = {};
  for (const documentType of changeSet.affectedDocuments) {
    documentHtml[documentType] =
      byId.get(documentIds[documentType])?.html ?? undefined;
  }

  const coverage = evaluateReturnWindowCoverage({
    pendingChanges,
    changeSet,
    documentIds,
    documentHtml,
  });
  if (!coverage.ok) {
    throw new PolicySetSuperDocsSafetyError(
      coverage.message ?? "The proposed managed-fact update is incomplete.",
    );
  }
}

export function assertPendingChangesTargetDocument(
  pendingChanges: readonly Pick<PendingChange, "documentId">[],
  selectedDocumentId: string,
): void {
  if (!selectedDocumentId) {
    throw new PolicySetSuperDocsSafetyError(
      "The selected PolicySet document is missing its SuperDocs identity.",
    );
  }
  const foreign = pendingChanges.find(
    (change) => change.documentId !== selectedDocumentId,
  );
  if (foreign) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs proposed a change to another PolicySet document. Nothing was approved; select the intended document and try again.",
    );
  }
}

function assertJobSession(snapshot: JobSnapshot, sessionId: string): void {
  if (snapshot.reference.sessionId !== sessionId) {
    throw new PolicySetSuperDocsSafetyError(
      "SuperDocs returned a job for a different PolicySet session.",
    );
  }
}

function jobView(snapshot: JobSnapshot): SuperDocsJobView {
  return {
    jobId: snapshot.reference.jobId,
    sessionId: snapshot.reference.sessionId,
    status: snapshot.reference.status,
    progress: snapshot.progress,
    proposals: snapshot.pendingChanges.map(proposalView),
    errorCode: snapshot.errorCode,
  };
}

function proposalView(change: PendingChange): SuperDocsProposal {
  return {
    changeId: change.changeId,
    operation: change.operation,
    documentId: change.documentId,
    chunkId: change.chunkId,
    beforeHtml: change.oldHtml,
    afterHtml: change.newHtml,
    explanation: change.aiExplanation,
  };
}

function capturePolicyDocumentState(
  documents: readonly SuperDocsSessionDocumentView[],
  documentIds: Record<PolicyDocumentType, string>,
): PolicyDocumentContentStateMap {
  assertDocumentMap(documentIds);
  if (documents.length !== POLICY_DOCUMENT_TYPES.length) {
    throw new PolicySetSuperDocsSafetyError(
      "The authoritative SuperDocs roster must contain exactly four PolicySet documents.",
    );
  }

  const byId = new Map(documents.map((document) => [document.documentId, document]));
  const state = {} as PolicyDocumentContentStateMap;
  for (const documentType of POLICY_DOCUMENT_TYPES) {
    const document = byId.get(documentIds[documentType]);
    if (
      !document ||
      document.html === null ||
      document.normalizedContent === null ||
      document.sha256 === null
    ) {
      throw new PolicySetSuperDocsSafetyError(
        `The authoritative ${POLICY_DOCUMENT_TITLES[documentType]} HTML is unavailable. No synchronized edit was started.`,
      );
    }
    state[documentType] = {
      documentId: document.documentId,
      normalizedContent: document.normalizedContent,
      sha256: document.sha256,
    };
  }
  if (byId.size !== POLICY_DOCUMENT_TYPES.length) {
    throw new PolicySetSuperDocsSafetyError(
      "The authoritative SuperDocs roster contains duplicate or unknown documents.",
    );
  }
  return state;
}

function assertChangeSetMatchesRegistry(changeSet: ChangeSet): void {
  const affected = getAffectedDocuments(changeSet.fieldPath);
  if (!affected.ok) {
    throw new PolicySetSuperDocsSafetyError(affected.error.message);
  }
  if (!setsEqual(new Set(affected.value), new Set(changeSet.affectedDocuments))) {
    throw new PolicySetSuperDocsSafetyError(
      "The ChangeSet affected documents do not match the dependency registry.",
    );
  }
}

function assertDocumentMap(
  documentIds: Record<PolicyDocumentType, string>,
): void {
  const ids = POLICY_DOCUMENT_TYPES.map((type) => documentIds[type]);
  if (ids.some((id) => typeof id !== "string" || id.trim() === "")) {
    throw new PolicySetSuperDocsSafetyError(
      "The PolicySet document map is incomplete.",
    );
  }
  if (new Set(ids).size !== POLICY_DOCUMENT_TYPES.length) {
    throw new PolicySetSuperDocsSafetyError(
      "The PolicySet document map contains duplicate SuperDocs identities.",
    );
  }
}

function sanitizeFilenameComponent(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
    .replace(/-+$/g, "");
}

function normalizePolicyContent(html: string): string {
  return htmlToPolicyText(html);
}

function sha256Hex(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function requireWindowValue(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new PolicySetSuperDocsSafetyError(
      `The ChangeSet ${label} return-window value is invalid.`,
    );
  }
  return value;
}

function setsEqual<T>(left: Set<T>, right: Set<T>): boolean {
  return left.size === right.size && [...left].every((value) => right.has(value));
}

async function denyEveryPendingChange(
  snapshot: JobSnapshot,
  sessionId: string,
  client: PolicySetSuperDocsClient,
): Promise<void> {
  await client.submitReview({
    sessionId,
    jobId: snapshot.reference.jobId,
    decisions: snapshot.pendingChanges.map((change) => ({
      changeId: change.changeId,
      approved: false,
    })),
  });
}

async function captureProposalEvidence(
  snapshot: JobSnapshot,
  options: ProposalEvidenceOptions,
): Promise<void> {
  try {
    await persistPendingProposalEvidence(snapshot, options);
  } catch {
    throw new PolicySetSuperDocsSafetyError(
      "PolicySet could not persist the sanitized proposal evidence snapshot. No review decision was submitted and the canonical return window remains unchanged.",
    );
  }
}
