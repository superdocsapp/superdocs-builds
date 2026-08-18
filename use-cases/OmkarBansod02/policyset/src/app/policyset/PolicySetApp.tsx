"use client";

import { useState } from "react";
import {
  clonePolicyProfile,
  NORTHSTAR_GOODS_PROFILE,
} from "@/domain";
import { TooltipProvider } from "@/components/ui/tooltip";
import { generatePolicyWorkspace, type PolicyWorkspaceState } from "./generate-workspace";
import { intakeFromProfile, profileFromIntake, type IntakeFormState } from "./intake";
import { IntakeView } from "./IntakeView";
import { WorkspaceView } from "./WorkspaceView";

export function PolicySetApp() {
  const [view, setView] = useState<"intake" | "workspace">("intake");
  const [intake, setIntake] = useState<IntakeFormState>(() =>
    intakeFromProfile(NORTHSTAR_GOODS_PROFILE),
  );
  const [workspace, setWorkspace] = useState<PolicyWorkspaceState | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleGenerate() {
    const parsed = profileFromIntake(intake);
    if (!parsed.ok) {
      setError(parsed.error.message);
      return;
    }

    setError(null);
    const next = generatePolicyWorkspace(parsed.value);
    setWorkspace(next);
    setView("workspace");
  }

  if (view === "workspace" && workspace) {
    return (
      <TooltipProvider delayDuration={200}>
        <WorkspaceView
          workspace={workspace}
          onWorkspaceChange={setWorkspace}
          onEditIntake={() => {
            setIntake(intakeFromProfile(clonePolicyProfile(workspace.profile)));
            setView("intake");
          }}
        />
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <IntakeView
        value={intake}
        error={error}
        canCancel={workspace !== null}
        onChange={(next) => {
          setError(null);
          setIntake(next);
        }}
        onGenerate={handleGenerate}
        onCancel={() => {
          setError(null);
          setView("workspace");
        }}
      />
    </TooltipProvider>
  );
}
