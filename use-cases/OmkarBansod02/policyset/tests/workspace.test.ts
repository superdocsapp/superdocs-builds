import { describe, expect, it } from "vitest";

import { generatePolicyWorkspace } from "@/app/policyset/generate-workspace";
import {
  intakeFromProfile,
  profileFromIntake,
} from "@/app/policyset/intake";
import {
  NORTHSTAR_GOODS_PROFILE,
  POLICY_DOCUMENT_TYPES,
  type Result,
} from "@/domain";

describe("intake to PolicyProfile", () => {
  it("builds a valid profile from Northstar intake values and field edits", () => {
    const intake = intakeFromProfile(NORTHSTAR_GOODS_PROFILE);
    expect(unwrap(profileFromIntake(intake))).toEqual(NORTHSTAR_GOODS_PROFILE);

    intake.returns.windowDays = 14;
    const edited = unwrap(profileFromIntake(intake));
    expect(edited.returns.windowDays).toBe(14);
    expect(edited.company.legalName).toBe("Northstar Goods LLC");
  });
});

describe("generated workspace", () => {
  it("contains four documents and a consistent validator result", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);

    expect(Object.keys(workspace.documents).sort()).toEqual(
      [...POLICY_DOCUMENT_TYPES].sort(),
    );
    expect(workspace.documents.terms.length).toBeGreaterThan(0);
    expect(workspace.documents.privacy.length).toBeGreaterThan(0);
    expect(workspace.documents.warranty.length).toBeGreaterThan(0);
    expect(workspace.documents.returns.length).toBeGreaterThan(0);
    expect(workspace.validation.ok).toBe(true);
  });
});

function unwrap<T>(result: Result<T>): T {
  if (!result.ok) {
    throw new Error(`${result.error.code}: ${result.error.message}`);
  }
  return result.value;
}
