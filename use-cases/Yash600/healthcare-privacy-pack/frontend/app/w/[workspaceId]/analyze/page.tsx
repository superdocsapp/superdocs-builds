"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  api, AnalysisRunResult, DocumentOut, ReferenceOut, SectionOut,
  REFERENCE_STATUS_COLORS, REFERENCE_STATUS_LABELS,
} from "@/lib/api";
import { IconWorkflow, IconCheckCircle } from "../../../icons";
import { ProgressOverlay, useStagedProgress } from "../../../ProgressOverlay";

export default function AnalyzePage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId);

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [references, setReferences] = useState<ReferenceOut[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [lastRun, setLastRun] = useState<AnalysisRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedProcId, setSelectedProcId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, refs] = await Promise.all([
        api.listWorkspaceDocuments(workspaceId),
        api.listReferences(workspaceId),
      ]);
      setDocuments(docs);
      setReferences(refs);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const progressUI = useStagedProgress();

  const policies = documents.filter((d) => d.doc_type === "policy");
  const procedures = documents.filter((d) => d.doc_type === "procedure");
  // Mirrors the backend's own pairing rule exactly (main.py's analyze
  // endpoint: one AnalysisJob per procedure whose parent_policy_id points
  // at a policy already in this workspace) so the stage narration below
  // states the real number of pairs the request is about to process, not a
  // guess.
  const pairCount = procedures.filter((p) => p.parent_policy_id && policies.some((pol) => pol.id === p.parent_policy_id)).length;

  const docTitle = (id: string) => documents.find((d) => d.id === id)?.title || id;

  // Keep each procedure's references separate rather than one flat merged
  // list -- default to the first procedure (not an "all" view) as soon as
  // procedures are available, and fall back to it again if the previously
  // selected one disappears (e.g. a fresh workspace still loading).
  useEffect(() => {
    if (procedures.length === 0) {
      if (selectedProcId !== null) setSelectedProcId(null);
      return;
    }
    if (!selectedProcId || !procedures.some((p) => p.id === selectedProcId)) {
      setSelectedProcId(procedures[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documents]);

  const referenceCountByProc = new Map<string, number>();
  for (const r of references) {
    referenceCountByProc.set(r.procedure_document_id || "", (referenceCountByProc.get(r.procedure_document_id || "") || 0) + 1);
  }
  const visibleReferences = selectedProcId ? references.filter((r) => r.procedure_document_id === selectedProcId) : [];

  // The references endpoint embeds the actual policy_section/procedure_section
  // objects on every ReferenceOut (see backend's _reference_out) -- use those
  // directly rather than re-looking them up via documents[].sections, which
  // listWorkspaceDocuments never populates (only GET /documents/{id} does).
  // That mismatch was why this list was showing raw UUIDs instead of titles.
  const sectionLabel = (section: SectionOut | undefined, docId: string | undefined, fallbackId: string) => {
    if (!section) return fallbackId;
    const title = docId ? docTitle(docId) : undefined;
    return title ? `${title} §${section.section_number} -- ${section.title}` : `§${section.section_number} -- ${section.title}`;
  };

  const runAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      // The backend runs every pair's LLM call inside one blocking request
      // (see main.py's /analyze), so there's no incremental signal to show
      // mid-flight -- the overlay narrates the real pairing count up front,
      // then holds honestly on "running" for as long as the request
      // actually takes, rather than pretending to tick off individual
      // pairs it has no way to know the real status of yet.
      const result = await progressUI.runStaged(
        "Analyzing references",
        [
          `Batching ${pairCount} policy/procedure pair${pairCount === 1 ? "" : "s"} for Groq`,
          `Running LLM reference discovery across ${pairCount} pair${pairCount === 1 ? "" : "s"}`,
        ],
        () => api.analyzeReferences(workspaceId),
        { cadenceMs: 700, detail: "Each pair's sections are sent to Groq together; matches are confidence-gated before being saved." }
      );
      setLastRun(result);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div>
      <div className="eyebrow"><IconWorkflow size={13} /> Analyze</div>
      <h1>Analyze References</h1>
      <p className="lede">
        A direct LLM call reads every policy section alongside each grouped procedure and reports
        which procedure sections implement which policy sections, with a confidence score and
        evidence for each pair. Matches at or above 85% confidence are marked valid automatically;
        matches between 50-85% are flagged for review; anything lower is discarded.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="card glass-strong row between">
        <div className="muted">
          {policies.length} polic{policies.length === 1 ? "y" : "ies"}, {procedures.length} procedure{procedures.length === 1 ? "" : "s"} grouped
        </div>
        <button className="primary" onClick={runAnalyze} disabled={analyzing || policies.length === 0}>
          <IconWorkflow size={14} /> {analyzing ? "Analyzing..." : "Run Analyze References"}
        </button>
      </div>

      {lastRun && (
        <div className="card glass-strong">
          <h3>Last run</h3>
          <div className="col" style={{ gap: 10 }}>
            {lastRun.jobs.map((j) => (
              <div key={j.id}>
                <div className="row between" style={{ fontSize: 13 }}>
                  <span>{docTitle(j.policy_document_id)} &rarr; {docTitle(j.procedure_document_id)}</span>
                  <span className={`badge ${j.status === "complete" ? "synced" : j.status === "failed" ? "stale" : "pending_review"}`}>
                    {j.status}
                  </span>
                </div>
                {j.status === "failed" && j.error_message && (
                  <div className="error-banner" style={{ marginTop: 6, marginBottom: 0, fontSize: 12.5 }}>
                    {j.error_message}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="section-head">
        <div className="section-head-icon"><IconCheckCircle size={14} /></div>
        <h2>References ({references.length})</h2>
      </div>

      {procedures.length === 0 && (
        <div className="empty">
          No references yet -- upload policies and procedures, group them, then run Analyze References.
        </div>
      )}

      {procedures.length > 0 && (
        <>
          {/* One procedure's references at a time -- selecting a tab is what
              decides what's visible below, rather than merging every
              procedure's references into a single flat list. */}
          <div className="proc-tabs">
            {procedures.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`proc-tab ${selectedProcId === p.id ? "active" : ""}`}
                onClick={() => setSelectedProcId(p.id)}
              >
                {p.title}
                <span className="count">{referenceCountByProc.get(p.id) || 0}</span>
              </button>
            ))}
          </div>

          {visibleReferences.length === 0 && (
            <div className="empty">
              No references discovered for this procedure yet -- run Analyze References.
            </div>
          )}
          {visibleReferences.map((r) => (
            <div key={r.id} className="card row between">
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {sectionLabel(r.procedure_section, r.procedure_document_id, r.procedure_section_id)}
                </div>
                <div className="faint">implements {sectionLabel(r.policy_section, r.policy_document_id, r.policy_section_id)}</div>
                {r.evidence && <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>{r.evidence}</div>}
              </div>
              <div style={{ textAlign: "right" }}>
                <span className="badge" style={{ background: `${REFERENCE_STATUS_COLORS[r.status]}22`, color: REFERENCE_STATUS_COLORS[r.status] }}>
                  {REFERENCE_STATUS_LABELS[r.status]}
                </span>
                {r.confidence != null && <div className="faint" style={{ marginTop: 4 }}>{Math.round(r.confidence * 100)}% confidence</div>}
              </div>
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
