"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, ShieldAlert } from "lucide-react";
import type { DryRunView, SourceRegistration } from "../lib/api";
import { humanDryRunFailure, safetyFailureRecovery } from "../lib/workspace-state";
import { SourceSummary } from "./source-summary";

export function UnsupportedState({
  source,
  dryRun,
  onReturn,
}: {
  source: SourceRegistration;
  dryRun: DryRunView;
  onReturn: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const humanReason = humanDryRunFailure(dryRun.reason_code, dryRun.reason);
  const recovery = safetyFailureRecovery(dryRun.reason_code);

  return (
    <div className="space-y-5">
      <SourceSummary source={source} compact />

      <div className="bg-surface-muted rounded-lg p-6 sm:p-8">
        <div className="bg-surface rounded border border-border shadow-sm max-w-2xl mx-auto">
          <div className="px-6 py-6 sm:px-8 sm:py-8">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-lg bg-warning-soft flex items-center justify-center flex-shrink-0">
                <ShieldAlert className="w-5 h-5 text-warning" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-ink">
                  This change can&apos;t be safely written back
                </h2>
                <p className="text-xs text-muted">
                  No cloud changes were made.
                </p>
              </div>
            </div>

            <div className="px-4 py-3 bg-warning-soft/50 rounded border border-warning/15 mb-6">
              <p className="text-sm text-ink/80">{humanReason}</p>
            </div>

            <button
              onClick={() => setShowDetails((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-muted hover:text-ink transition-colors mb-4"
            >
              {showDetails ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              View technical details
            </button>

            {showDetails && (
              <div className="p-3 bg-surface-muted rounded border border-border text-xs font-mono space-y-1 mb-6">
                <p><span className="text-muted">status:</span> {dryRun.status}</p>
                <p><span className="text-muted">reason_code:</span> {dryRun.reason_code ?? "—"}</p>
                <p><span className="text-muted">reason:</span> {dryRun.reason ?? "—"}</p>
                {dryRun.candidate_count !== null && (
                  <p><span className="text-muted">candidate_count:</span> {dryRun.candidate_count}</p>
                )}
                <p><span className="text-muted">cloud_mutation_performed:</span> false</p>
              </div>
            )}

            <button
              onClick={onReturn}
              className="px-4 py-2 bg-surface-muted text-ink text-sm font-medium rounded border border-border hover:bg-border/30 transition-colors"
            >
              {recovery.kind === "refresh-source" ? recovery.label : "Return to document"}
            </button>
            {recovery.explanation ? (
              <p className="mt-4 text-xs leading-5 text-muted">{recovery.explanation}</p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
