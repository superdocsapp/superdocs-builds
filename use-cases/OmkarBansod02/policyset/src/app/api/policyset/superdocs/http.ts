import { NextResponse } from "next/server";

import {
  getManagedFieldValue,
  isManagedFieldPath,
  MANAGED_FIELD_PATHS,
  POLICY_DOCUMENT_TYPES,
  parseManagedFieldValue,
  type ChangeSet,
  type ChangeSetStatus,
  type PolicyDocumentType,
  type PolicyProfile,
} from "@/domain";
import {
  PolicySetSuperDocsSafetyError,
  SuperDocsInvalidResponse,
  SuperDocsRequestError,
} from "@/superdocs";
import type { ExportFormat } from "@/superdocs/types";

export class PolicySetRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PolicySetRequestError";
  }
}

export async function readJsonObject(
  request: Request,
): Promise<Record<string, unknown>> {
  let value: unknown;
  try {
    value = await request.json();
  } catch {
    throw new PolicySetRequestError("Request body must be valid JSON.");
  }
  if (!isRecord(value)) {
    throw new PolicySetRequestError("Request body must be an object.");
  }
  return value;
}

export function requiredString(
  record: Record<string, unknown>,
  key: string,
): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new PolicySetRequestError(`${key} must be a non-empty string.`);
  }
  return value;
}

export function requiredBoolean(
  record: Record<string, unknown>,
  key: string,
): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw new PolicySetRequestError(`${key} must be a boolean.`);
  }
  return value;
}

export function requiredChangeSet(value: unknown): ChangeSet {
  if (!isRecord(value)) {
    throw new PolicySetRequestError("changeSet must be an object.");
  }
  const fieldPath = value.fieldPath;
  if (typeof fieldPath !== "string" || !isManagedFieldPath(fieldPath)) {
    throw new PolicySetRequestError("changeSet has an unmanaged field path.");
  }
  const id = value.id;
  if (typeof id !== "string" || id.trim() === "") {
    throw new PolicySetRequestError("changeSet id must be provided.");
  }
  const status = value.status;
  if (!isChangeSetStatus(status)) {
    throw new PolicySetRequestError("changeSet has an invalid status.");
  }
  if (
    !Array.isArray(value.affectedDocuments) ||
    value.affectedDocuments.some((item) => !isPolicyDocumentType(item))
  ) {
    throw new PolicySetRequestError(
      "changeSet affectedDocuments must contain PolicySet document types.",
    );
  }
  const previous = parseManagedFieldValue(fieldPath, value.previousValue);
  const next = parseManagedFieldValue(fieldPath, value.nextValue);
  if (!previous.ok || !next.ok) {
    throw new PolicySetRequestError(
      !previous.ok ? previous.error.message : next.ok ? "Invalid ChangeSet." : next.error.message,
    );
  }

  return {
    id,
    fieldPath,
    previousValue: previous.value,
    nextValue: next.value,
    affectedDocuments: [...value.affectedDocuments],
    status,
  };
}

export function requiredPolicyDocumentType(value: unknown): PolicyDocumentType {
  if (!isPolicyDocumentType(value)) {
    throw new PolicySetRequestError(
      "documentType must be a PolicySet document type.",
    );
  }
  return value;
}

export function requiredExportFormat(value: unknown): ExportFormat {
  if (value !== "docx" && value !== "pdf") {
    throw new PolicySetRequestError("format must be docx or pdf.");
  }
  return value;
}

export function requiredDocumentIds(
  value: unknown,
): Record<PolicyDocumentType, string> {
  if (!isRecord(value)) {
    throw new PolicySetRequestError("documentIds must be an object.");
  }
  const documentIds = {} as Record<PolicyDocumentType, string>;
  for (const documentType of POLICY_DOCUMENT_TYPES) {
    documentIds[documentType] = requiredString(value, documentType);
  }
  return documentIds;
}

export function requiredPolicyProfile(value: unknown): PolicyProfile {
  if (!isRecord(value)) {
    throw new PolicySetRequestError("profile must be a PolicyProfile object.");
  }

  const profile = structuredClone(value) as PolicyProfile;
  try {
    for (const path of MANAGED_FIELD_PATHS) {
      const parsed = parseManagedFieldValue(
        path,
        getManagedFieldValue(profile, path),
      );
      if (!parsed.ok) {
        throw new PolicySetRequestError(parsed.error.message);
      }
    }
  } catch (error) {
    if (error instanceof PolicySetRequestError) {
      throw error;
    }
    throw new PolicySetRequestError("profile is missing required policy facts.");
  }
  return profile;
}

export function routeError(error: unknown): NextResponse {
  if (error instanceof PolicySetRequestError) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }
  if (error instanceof PolicySetSuperDocsSafetyError) {
    return NextResponse.json({ error: error.message }, { status: 409 });
  }
  if (error instanceof SuperDocsRequestError) {
    return NextResponse.json({ error: error.message }, { status: 502 });
  }
  if (error instanceof SuperDocsInvalidResponse) {
    return NextResponse.json({ error: error.message }, { status: 502 });
  }
  if (
    error instanceof Error &&
    error.message === "SUPERDOCS_API_KEY is not configured"
  ) {
    return NextResponse.json(
      { error: "SuperDocs is not configured on the server." },
      { status: 503 },
    );
  }

  console.error("PolicySet SuperDocs route failed", error);
  return NextResponse.json(
    { error: "The SuperDocs operation could not be completed." },
    { status: 500 },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPolicyDocumentType(value: unknown): value is PolicyDocumentType {
  return (
    typeof value === "string" &&
    (POLICY_DOCUMENT_TYPES as readonly string[]).includes(value)
  );
}

function isChangeSetStatus(value: unknown): value is ChangeSetStatus {
  return (
    typeof value === "string" &&
    ["pending", "proposed", "approved", "rejected", "failed"].includes(value)
  );
}
