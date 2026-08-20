"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, DocumentOut, ProposedChangeOut } from "@/lib/api";
import { IconEyeCheck, IconCheckCircle, IconX, IconAlertTriangle } from "../../../icons";
import { ProgressOverlay, useStagedProgress } from "../../../ProgressOverlay";

// A ProposedChange whose SuperDocs job is still genuinely running can
// realistically take a while -- but past this many ms without producing a
// diff, it's worth telling the reviewer that specifically, rather than
// leaving them staring at an identical spinner the whole time with no way
// to tell "still working" apart from "probably stuck".
const SLOW_WARNING_MS = 90_000;

function useNowTick(intervalMs: number) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}

export default function ReviewPage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId);

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [pending, setPending] = useState<ProposedChangeOut[]>([]);
  const [failed, setFailed] = useState<ProposedChangeOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const progressUI = useStagedProgress();
  useNowTick(15000); // re-render periodically so the "taking longer than usual" hint can appear without a fresh fetch

  const refresh = useCallback(async () => {
    try {
      const [docs, pc, failedPc] = await Promise.all([
        api.listWorkspaceDocuments(workspaceId),
        api.listProposedChanges(workspaceId, "pending"),
        api.listProposedChanges(workspaceId, "failed"),
      ]);
      setDocuments(docs);
      setPending(pc);
      setFailed(failedPc);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Submitting an update request (Update tab) only kicks off SuperDocs'
  // chat/async job -- it doesn't wait for the diff to be drafted. Each GET
  // .../proposed-changes call enriches any still-blank proposal on the
  // backend (see main.py's _enrich_pending_change), so as long as this page
  // is open with something genuinely still waiting on SuperDocs, poll for
  // it rather than making the compliance officer manually refresh to find
  // out a diff has arrived.
  const stillWaitingOnSuperDocs = pending.some((pc) => pc.old_html == null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (stillWaitingOnSuperDocs) {
      pollRef.current = setInterval(refresh, 3000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stillWaitingOnSuperDocs, refresh]);

  const resolve = async (id: string, approved: boolean) => {
    setResolvingId(id);
    setError(null);
    const pc = pending.find((p) => p.id === id);
    const doc = pc ? documents.find((d) => d.id === pc.document_id) : undefined;
    const isTopLevelPolicyEdit = approved && doc?.doc_type === "policy" && pc?.reference_id == null;

    // Mirrors the backend's real sequence in /proposed-changes/{id}/approve:
    // send the decision to SuperDocs, wait for that job to actually finish
    // (it polls SuperDocs itself, which is the genuinely slow part), save
    // the new document version, then -- only for an approved top-level
    // policy edit -- fan out a fresh proposed change to every procedure
    // that references the section that changed.
    const stageLabels = approved
      ? [
          "Applying the approved edit in SuperDocs",
          "Waiting for SuperDocs to finish the edit",
          "Saving the new document version",
          ...(isTopLevelPolicyEdit ? ["Propagating to any linked procedures"] : []),
        ]
      : ["Sending rejection to SuperDocs", "Confirming with SuperDocs"];

    try {
      await progressUI.runStaged(approved ? "Approving change" : "Rejecting change", stageLabels, () => api.approveProposedChange(id, approved), {
        cadenceMs: 900,
      });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setResolvingId(null);
    }
  };

  const docTitle = (id: string) => documents.find((d) => d.id === id)?.title || id;

  return (
    <div>
      <div className="eyebrow"><IconEyeCheck size={13} /> Review</div>
      <h1>Pending review ({pending.length})</h1>
      <p className="lede">
        Every proposed change stays here until it's approved or rejected -- nothing is applied to a
        document automatically. Approving a policy edit that has downstream procedures opens a
        matching proposed change for each one, listed here independently.
      </p>

      {error && <div className="error-banner">{error}</div>}

      {pending.length === 0 && failed.length === 0 && <div className="empty">Nothing awaiting review right now.</div>}

      {pending.map((pc) => {
        const waitingMs = Date.now() - new Date(pc.created_at).getTime();
        const isSlow = !pc.old_html && waitingMs > SLOW_WARNING_MS;
        return (
          <div key={pc.id} className="card glass-strong">
            <div className="row between">
              <div>
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>{docTitle(pc.document_id)}</div>
                {pc.ai_explanation && <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>{pc.ai_explanation}</div>}
                {isSlow && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 4, color: "var(--warn)" }}>
                    This is taking longer than usual -- SuperDocs may still be working on it.
                  </div>
                )}
              </div>
              {!pc.old_html && (
                <span className="badge stale" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span className="stage-spinner" aria-hidden="true" style={{ width: 11, height: 11, borderWidth: 1.5 }} />
                  Waiting on SuperDocs...
                </span>
              )}
            </div>

            {pc.old_html != null && pc.new_html != null && (
              <div className="diff">
                <div className="old">
                  <span className="label">Before</span>
                  <div dangerouslySetInnerHTML={{ __html: pc.old_html }} />
                </div>
                <div className="new">
                  <span className="label">Proposed</span>
                  <div dangerouslySetInnerHTML={{ __html: pc.new_html }} />
                </div>
              </div>
            )}

            <div className="row" style={{ marginTop: 12, gap: 8 }}>
              <button className="approve" disabled={resolvingId === pc.id || !pc.old_html} onClick={() => resolve(pc.id, true)}>
                <IconCheckCircle size={14} /> Approve
              </button>
              <button className="reject" disabled={resolvingId === pc.id || !pc.old_html} onClick={() => resolve(pc.id, false)}>
                <IconX size={14} /> Reject
              </button>
            </div>
          </div>
        );
      })}

      {failed.length > 0 && (
        <>
          <div className="section-head" style={{ marginTop: 28 }}>
            <div className="section-head-icon"><IconAlertTriangle size={14} /></div>
            <h2>Needs attention ({failed.length})</h2>
          </div>
          <p className="muted" style={{ marginTop: -8, marginBottom: 14, fontSize: 12.5 }}>
            SuperDocs didn't produce a proposal for these -- there's nothing to approve or reject. Go back to the
            Update tab to try the instruction again.
          </p>
          {failed.map((pc) => (
            <div key={pc.id} className="card" style={{ borderColor: "rgba(179, 69, 58, 0.35)" }}>
              <div className="row between">
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>{docTitle(pc.document_id)}</div>
                <span className="badge stale">Failed</span>
              </div>
              {pc.ai_explanation && (
                <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--danger)" }}>{pc.ai_explanation}</div>
              )}
            </div>
          ))}
        </>
      )}

      <ProgressOverlay
        visible={progressUI.visible}
        title={progressUI.title}
        labels={progressUI.labels}
        statuses={progressUI.statuses}
        detail={progressUI.detail}
        error={progressUI.error}
        onDismiss={progressUI.close}
      />
    </div>
  );
}
