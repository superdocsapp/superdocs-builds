import type { ProposedChange } from "./superdocs";
import type { EvidenceFact } from "@payment-security-self-assessment/evidence";

export type AssessmentWorkflowState = "PROCESSING" | "AWAITING_APPROVAL" | "APPROVING" | "APPROVED" | "FAILED";

export interface AssessmentWorkflow {
  id: string;
  sessionId: string;
  jobId: string;
  facts: EvidenceFact[];
  state: AssessmentWorkflowState;
  proposedChanges: ProposedChange[];
  draftHtml?: string;
  error?: string;
}

const workflows = new Map<string, AssessmentWorkflow>();

export function createAssessmentWorkflow(sessionId: string, jobId: string, facts: EvidenceFact[]): AssessmentWorkflow {
  const workflow: AssessmentWorkflow = {
    id: crypto.randomUUID(),
    sessionId,
    jobId,
    facts,
    state: "PROCESSING",
    proposedChanges: [],
  };
  workflows.set(workflow.id, workflow);
  return workflow;
}

export function getAssessmentWorkflow(id: string): AssessmentWorkflow | undefined {
  return /^[0-9a-f-]{36}$/i.test(id) ? workflows.get(id) : undefined;
}

export function updateAssessmentWorkflow(id: string, updates: Partial<Omit<AssessmentWorkflow, "id" | "sessionId" | "jobId" | "facts">>): AssessmentWorkflow | undefined {
  const workflow = getAssessmentWorkflow(id);
  if (!workflow) return undefined;
  Object.assign(workflow, updates);
  return workflow;
}

export function canExportAssessment(workflow: AssessmentWorkflow): boolean {
  return workflow.state === "APPROVED";
}
