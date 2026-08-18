import type { PolicyDocumentType } from "@/domain";
import type { PolicyWorkspaceState } from "./generate-workspace";

export type PolicyEditOutcome =
  | { kind: "rejected" }
  | {
      kind: "approved";
      documentType: PolicyDocumentType;
      html: string;
    };

export function applyPolicyEditOutcome(
  workspace: PolicyWorkspaceState,
  outcome: PolicyEditOutcome,
): PolicyWorkspaceState {
  if (outcome.kind === "rejected") {
    return workspace;
  }

  return {
    ...workspace,
    documents: {
      ...workspace.documents,
      [outcome.documentType]: outcome.html,
    },
  };
}
