import {
  applyManagedField,
  getManagedFieldValue,
  parseManagedFieldValue,
  valuesEqual,
} from "./profile";
import { getAffectedDocuments, isManagedFieldPath } from "./registry";
import { err, ok, type Result } from "./result";
import type { ChangeSet, ChangeSetStatus, PolicyProfile } from "./types";

export function createChangeSet(
  profile: PolicyProfile,
  fieldPath: string,
  nextValue: unknown,
): Result<ChangeSet> {
  if (!isManagedFieldPath(fieldPath)) {
    return err(
      "UNMANAGED_FIELD_PATH",
      `Unknown or unmanaged field path: ${fieldPath}`,
    );
  }

  const affected = getAffectedDocuments(fieldPath);
  if (!affected.ok) {
    return affected;
  }

  const parsed = parseManagedFieldValue(fieldPath, nextValue);
  if (!parsed.ok) {
    return parsed;
  }

  const previousValue = structuredClone(
    getManagedFieldValue(profile, fieldPath),
  );

  return ok({
    id: `cs_${crypto.randomUUID()}`,
    fieldPath,
    previousValue,
    nextValue: structuredClone(parsed.value),
    affectedDocuments: [...affected.value],
    status: "pending",
  });
}

export function proposeChangeSet(changeSet: ChangeSet): Result<ChangeSet> {
  return transition(changeSet, "proposed", ["pending"]);
}

export function approveChangeSet(changeSet: ChangeSet): Result<ChangeSet> {
  return transition(changeSet, "approved", ["pending", "proposed"]);
}

export function rejectChangeSet(changeSet: ChangeSet): Result<ChangeSet> {
  return transition(changeSet, "rejected", ["pending", "proposed"]);
}

export function failChangeSet(changeSet: ChangeSet): Result<ChangeSet> {
  return transition(changeSet, "failed", ["pending", "proposed", "approved"]);
}

export function commitChangeSet(
  profile: PolicyProfile,
  changeSet: ChangeSet,
): Result<{ profile: PolicyProfile; changeSet: ChangeSet }> {
  if (changeSet.status !== "approved") {
    return err(
      "CHANGESET_NOT_APPROVED",
      `Cannot commit a changeset with status "${changeSet.status}".`,
    );
  }

  if (!isManagedFieldPath(changeSet.fieldPath)) {
    return err(
      "UNMANAGED_FIELD_PATH",
      `Unknown or unmanaged field path: ${changeSet.fieldPath}`,
    );
  }

  const currentValue = getManagedFieldValue(profile, changeSet.fieldPath);
  if (!valuesEqual(currentValue, changeSet.previousValue)) {
    return err(
      "PROFILE_VALUE_MISMATCH",
      "Canonical profile no longer matches the changeset previous value.",
    );
  }

  const parsed = parseManagedFieldValue(
    changeSet.fieldPath,
    changeSet.nextValue,
  );
  if (!parsed.ok) {
    return parsed;
  }

  return ok({
    profile: applyManagedField(profile, changeSet.fieldPath, parsed.value),
    changeSet: cloneChangeSet(changeSet),
  });
}

function transition(
  changeSet: ChangeSet,
  nextStatus: ChangeSetStatus,
  allowedFrom: readonly ChangeSetStatus[],
): Result<ChangeSet> {
  if (!allowedFrom.includes(changeSet.status)) {
    return err(
      "INVALID_STATUS_TRANSITION",
      `Cannot move changeset from "${changeSet.status}" to "${nextStatus}".`,
    );
  }

  return ok({
    ...cloneChangeSet(changeSet),
    status: nextStatus,
  });
}

function cloneChangeSet(changeSet: ChangeSet): ChangeSet {
  return {
    ...changeSet,
    previousValue: structuredClone(changeSet.previousValue),
    nextValue: structuredClone(changeSet.nextValue),
    affectedDocuments: [...changeSet.affectedDocuments],
  };
}
