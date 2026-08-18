import {
  renderPolicySet,
  validatePolicySet,
  type PolicyDocumentSet,
  type PolicyProfile,
  type ValidationResult,
} from "@/domain";

/**
 * Deterministic workspace payload produced from a PolicyProfile.
 * This is not a SuperDocs session. Later phases replace the HTML
 * preview surface with SuperDocs editing behavior.
 */
export type PolicyWorkspaceState = {
  profile: PolicyProfile;
  documents: PolicyDocumentSet;
  validation: ValidationResult;
};

export function generatePolicyWorkspace(
  profile: PolicyProfile,
): PolicyWorkspaceState {
  const documents = renderPolicySet(profile);
  const validation = validatePolicySet(profile, documents);

  return { profile, documents, validation };
}
