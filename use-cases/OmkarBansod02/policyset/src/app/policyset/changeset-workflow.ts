import {
  POLICY_DOCUMENT_TYPES,
  applyManagedField,
  approveChangeSet,
  commitChangeSet,
  createChangeSet,
  err,
  failChangeSet,
  proposeChangeSet,
  rejectChangeSet,
  validatePolicySet,
  validateReturnWindowTransition,
  type ChangeSet,
  type PolicyDocumentSet,
  type PolicyDocumentType,
  type Result,
  type ValidationIssue,
} from "@/domain";

import type { PolicyWorkspaceState } from "./generate-workspace";
import type {
  PolicyDocumentContentStateMap,
  SuperDocsSessionDocumentView,
} from "./superdocs-contract";

export function proposeReturnWindowChangeSet(
  workspace: PolicyWorkspaceState,
  nextValue: number,
): Result<ChangeSet> {
  const created = createChangeSet(
    workspace.profile,
    "returns.windowDays",
    nextValue,
  );
  if (!created.ok) {
    return created;
  }
  if (created.value.previousValue === created.value.nextValue) {
    return err(
      "CHANGESET_HAS_NO_CHANGE",
      "Enter a return window different from the current canonical value.",
    );
  }
  return proposeChangeSet(created.value);
}

export function rejectSynchronizedChangeSet(
  workspace: PolicyWorkspaceState,
  changeSet: ChangeSet,
): Result<{ workspace: PolicyWorkspaceState; changeSet: ChangeSet }> {
  const rejected = rejectChangeSet(changeSet);
  if (!rejected.ok) {
    return rejected;
  }
  return { ok: true, value: { workspace, changeSet: rejected.value } };
}

export function failSynchronizedChangeSet(
  workspace: PolicyWorkspaceState,
  changeSet: ChangeSet,
): Result<{ workspace: PolicyWorkspaceState; changeSet: ChangeSet }> {
  const failed = failChangeSet(changeSet);
  if (!failed.ok) {
    return failed;
  }
  return { ok: true, value: { workspace, changeSet: failed.value } };
}

export function approveSynchronizedChangeSet(
  changeSet: ChangeSet,
): Result<ChangeSet> {
  return approveChangeSet(changeSet);
}

export function commitValidatedSynchronizedChange(
  workspace: PolicyWorkspaceState,
  changeSet: ChangeSet,
  preEditState: PolicyDocumentContentStateMap,
  postEditDocuments: readonly SuperDocsSessionDocumentView[],
  documentIds: Record<PolicyDocumentType, string>,
): Result<{
  workspace: PolicyWorkspaceState;
  changeSet: ChangeSet;
  unchangedDocuments: readonly PolicyDocumentType[];
}> {
  if (changeSet.status !== "approved") {
    return err(
      "CHANGESET_NOT_APPROVED",
      "The synchronized ChangeSet must be approved before validation and commit.",
    );
  }
  if (changeSet.fieldPath !== "returns.windowDays") {
    return err(
      "UNSUPPORTED_SYNCHRONIZED_FIELD",
      "This phase only validates synchronized return-window changes.",
    );
  }

  const roster = authoritativeDocumentSet(postEditDocuments, documentIds);
  if (!roster.ok) {
    return roster;
  }

  const prospectiveProfile = applyManagedField(
    workspace.profile,
    changeSet.fieldPath,
    changeSet.nextValue,
  );
  const consistency = validatePolicySet(prospectiveProfile, roster.value.documents);
  const transition = validateReturnWindowTransition(
    changeSet.previousValue as number,
    changeSet.nextValue as number,
    roster.value.documents,
    changeSet.affectedDocuments,
  );
  const issues: ValidationIssue[] = [
    ...consistency.issues,
    ...transition.issues,
  ];
  const affected = new Set(changeSet.affectedDocuments);
  const unchangedDocuments: PolicyDocumentType[] = [];

  for (const documentType of POLICY_DOCUMENT_TYPES) {
    if (affected.has(documentType)) {
      continue;
    }
    const before = preEditState[documentType];
    const after = roster.value.states[documentType];
    if (
      !before ||
      before.documentId !== documentIds[documentType] ||
      before.sha256 !== after.sha256 ||
      before.normalizedContent !== after.normalizedContent
    ) {
      issues.push({
        code: "untouched_document_changed",
        message: `Untouched document "${documentType}" changed during the synchronized operation.`,
        documents: [documentType],
      });
    } else {
      unchangedDocuments.push(documentType);
    }
  }

  if (issues.length > 0) {
    return err(
      "POST_EDIT_VALIDATION_FAILED",
      `Canonical commit blocked: ${issues.map((issue) => issue.message).join(" ")}`,
    );
  }

  const committed = commitChangeSet(workspace.profile, changeSet);
  if (!committed.ok) {
    return committed;
  }
  const finalValidation = validatePolicySet(
    committed.value.profile,
    roster.value.documents,
  );
  if (!finalValidation.ok) {
    return err(
      "POST_EDIT_VALIDATION_FAILED",
      "Canonical commit blocked because the authoritative documents are inconsistent.",
    );
  }

  return {
    ok: true,
    value: {
      workspace: {
        profile: committed.value.profile,
        documents: roster.value.documents,
        validation: finalValidation,
      },
      changeSet: committed.value.changeSet,
      unchangedDocuments,
    },
  };
}

function authoritativeDocumentSet(
  documents: readonly SuperDocsSessionDocumentView[],
  documentIds: Record<PolicyDocumentType, string>,
): Result<{
  documents: PolicyDocumentSet;
  states: PolicyDocumentContentStateMap;
}> {
  if (documents.length !== POLICY_DOCUMENT_TYPES.length) {
    return err(
      "AUTHORITATIVE_ROSTER_INVALID",
      "The authoritative SuperDocs roster must contain exactly four documents.",
    );
  }
  const byId = new Map(documents.map((document) => [document.documentId, document]));
  const policyDocuments = {} as PolicyDocumentSet;
  const states = {} as PolicyDocumentContentStateMap;

  for (const documentType of POLICY_DOCUMENT_TYPES) {
    const document = byId.get(documentIds[documentType]);
    if (
      !document ||
      document.html === null ||
      document.normalizedContent === null ||
      document.sha256 === null
    ) {
      return err(
        "AUTHORITATIVE_ROSTER_INVALID",
        `The authoritative ${documentType} document or its normalized content is unavailable.`,
      );
    }
    policyDocuments[documentType] = document.html;
    states[documentType] = {
      documentId: document.documentId,
      normalizedContent: document.normalizedContent,
      sha256: document.sha256,
    };
  }

  if (byId.size !== POLICY_DOCUMENT_TYPES.length) {
    return err(
      "AUTHORITATIVE_ROSTER_INVALID",
      "The authoritative SuperDocs roster contains duplicate or unknown documents.",
    );
  }
  return { ok: true, value: { documents: policyDocuments, states } };
}
