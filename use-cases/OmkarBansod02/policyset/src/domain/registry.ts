import { err, ok, type Result } from "./result";
import {
  DEPENDENCY_REGISTRY,
  MANAGED_FIELD_PATHS,
  type ManagedFieldPath,
  type PolicyDocumentType,
} from "./types";

export function isManagedFieldPath(value: string): value is ManagedFieldPath {
  return Object.prototype.hasOwnProperty.call(DEPENDENCY_REGISTRY, value);
}

export function getAffectedDocuments(
  fieldPath: string,
): Result<readonly PolicyDocumentType[]> {
  if (!isManagedFieldPath(fieldPath)) {
    return err(
      "UNMANAGED_FIELD_PATH",
      `Unknown or unmanaged field path: ${fieldPath}`,
    );
  }

  return ok([...DEPENDENCY_REGISTRY[fieldPath]]);
}

export function fieldsForDocument(
  documentType: PolicyDocumentType,
): readonly ManagedFieldPath[] {
  return MANAGED_FIELD_PATHS.filter((path) =>
    (DEPENDENCY_REGISTRY[path] as readonly PolicyDocumentType[]).includes(
      documentType,
    ),
  );
}
