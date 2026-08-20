"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, DocumentOut, WorkspaceOut } from "@/lib/api";
import { IconFileText, IconClipboard } from "../../icons";
import { ProgressOverlay, useStagedProgress } from "../../ProgressOverlay";
import { FlowExplainer } from "../../FlowExplainer";

function WorkspaceHubInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const workspaceId = String(params.workspaceId);
  const selectedDocId = searchParams.get("doc") || "";

  const [workspace, setWorkspace] = useState<WorkspaceOut | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<DocumentOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const progressUI = useStagedProgress();

  const refresh = useCallback(async () => {
    try {
      const ws = await api.getWorkspace(workspaceId);
      setWorkspace(ws);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedDocId) {
      setSelectedDoc(null);
      return;
    }
    api
      .getDocument(selectedDocId, true)
      .then(setSelectedDoc)
      .catch((e) => setError(String(e)));
  }, [selectedDocId]);

  const runValidate = async () => {
    setValidating(true);
    setError(null);
    try {
      await progressUI.runStaged(
        "Validating",
        ["Re-checking every reference against its current section text", "Recording pass/fail results"],
        () => api.validate(workspaceId),
        { cadenceMs: 500 }
      );
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setValidating(false);
    }
  };

  return (
    <div>
      <div className="workspace-toolbar">
        <div>
          <div className="eyebrow"><IconClipboard size={13} /> Policies &amp; Procedures</div>
          <h1>{workspace?.pack_name || "..."}</h1>
          <p className="muted" style={{ marginTop: -4 }}>{workspace?.organization_name}</p>
        </div>
        <div className="row wrap">
          <button className="btn" onClick={runValidate} disabled={validating}>
            {validating ? "Validating..." : "Validate"}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="split-view">
        <div className="split-panel glass-strong">
          <div className="split-panel-head">
            <div className="eyebrow"><IconFileText size={13} /> Preview</div>
            {selectedDoc && <span className={`badge ${selectedDoc.doc_type}`}>{selectedDoc.doc_type}</span>}
          </div>
          {!selectedDoc && <FlowExplainer />}
          {selectedDoc && (
            <>
              <h1 style={{ fontSize: 20 }}>{selectedDoc.title}</h1>
              {selectedDoc.html ? (
                <div className="doc-native-preview" dangerouslySetInnerHTML={{ __html: selectedDoc.html }} />
              ) : (
                <div className="muted">No content available for this document yet.</div>
              )}
            </>
          )}
        </div>
      </div>

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

export default function WorkspacePage() {
  return (
    <Suspense fallback={<div className="empty">Loading...</div>}>
      <WorkspaceHubInner />
    </Suspense>
  );
}
