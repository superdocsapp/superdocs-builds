import assert from "node:assert/strict";
import test from "node:test";
import { canExportAssessment, createAssessmentWorkflow, updateAssessmentWorkflow } from "./assessment-workflow.ts";

test("a generated workflow awaits explicit approval and cannot export first", () => {
  const workflow = createAssessmentWorkflow("session-1", "job-1", []);

  assert.equal(workflow.state, "PROCESSING");
  assert.equal(canExportAssessment(workflow), false);
  updateAssessmentWorkflow(workflow.id, { state: "AWAITING_APPROVAL" });
  assert.equal(canExportAssessment(workflow), false);
  updateAssessmentWorkflow(workflow.id, { state: "APPROVED" });
  assert.equal(canExportAssessment(workflow), true);
});
