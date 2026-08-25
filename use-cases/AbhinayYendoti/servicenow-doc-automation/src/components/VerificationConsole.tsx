import { Check, Lock, ShieldAlert, ShieldCheck, X } from "lucide-react";

import type { ChangeRequest, PreservationResult, ProposedChange } from "../domain";

/**
 * The guard, made visible.
 *
 * The verification rules are the reason this app is not just a document
 * generator, so they are shown as state rather than hidden until something
 * breaks: which values ServiceNow owns, what they must read, and whether the
 * document still says exactly that.
 */
export function VerificationConsole({
  change,
  proposals,
  verification
}: {
  change: ChangeRequest | null;
  proposals: ProposedChange[];
  verification: PreservationResult | null;
}) {
  if (!change) return null;

  const blocked = proposals.filter((proposal) => proposal.verification.verdict === "blocked").length;
  const advisory = proposals.filter((proposal) => proposal.verification.verdict === "advisory").length;

  const guards = [
    {
      field: "configuration_item",
      label: "Configuration item",
      expected: change.configuration_item
    },
    { field: "work_notes", label: "Work notes", expected: change.work_notes }
  ];

  return (
    <section className="panel verify-panel" data-tour="verify">
      <div className="panel-heading">
        <div className="panel-title">
          <span className="panel-icon">
            {verification?.ok === false ? <ShieldAlert size={19} /> : <ShieldCheck size={19} />}
          </span>
          <div>
            <span className="eyebrow">Verification</span>
            <h2>ServiceNow-owned values</h2>
          </div>
        </div>
        <span className={`status-pill ${verification ? (verification.ok ? "ok" : "bad") : ""}`}>
          {verification ? (verification.ok ? "all preserved" : "mismatch") : "not checked yet"}
        </span>
      </div>

      <p className="verify-intro">
        These must appear in the finished document character for character. Every proposed change is
        checked against them before you see it, and the export endpoint refuses to run if the final
        document does not carry them.
      </p>

      <div className="guard-list">
        {guards.map((guard) => {
          const check = verification?.checks.find((entry) => entry.field === guard.field);
          const state = check ? (check.found ? "ok" : "bad") : "pending";

          return (
            <article className={`guard ${state}`} key={guard.field}>
              <header>
                <span className="guard-icon">
                  {state === "ok" ? <Check size={13} /> : state === "bad" ? <X size={13} /> : <Lock size={13} />}
                </span>
                <strong>{guard.label}</strong>
                <span className="guard-state">
                  {state === "ok" ? "preserved" : state === "bad" ? "missing" : "guarded"}
                </span>
              </header>
              <p className="guard-value">{guard.expected || "—"}</p>
            </article>
          );
        })}
      </div>

      {proposals.length > 0 && (
        <div className="verify-tally">
          <span className="tally blocked">{blocked} blocked</span>
          <span className="tally advisory">{advisory} advisory</span>
          <span className="tally safe">{proposals.length - blocked - advisory} safe</span>
        </div>
      )}
    </section>
  );
}
