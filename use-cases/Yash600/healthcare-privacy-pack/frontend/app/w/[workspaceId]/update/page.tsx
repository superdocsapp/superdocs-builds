"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, DocumentOut } from "@/lib/api";
import { IconSparkle } from "../../../icons";
import { ProgressOverlay, useStagedProgress } from "../../../ProgressOverlay";

export default function UpdatePage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = String(params.workspaceId);

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const progressUI = useStagedProgress();

  const refresh = useCallback(async () => {
    try {
      const docs = await api.listWorkspaceDocuments(workspaceId);
      setDocuments(docs);
      if (!selectedDocId && docs.length) setSelectedDocId(docs[0].id);
    } catch (e) {
      setError(String(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const selectedDoc = documents.find((d) => d.id === selectedDocId);

  const submit = async () => {
    if (!selectedDocId || !instruction.trim()) return;
    setSubmitting(true);
    setError(null);
    setSubmitted(false);
    try {
      // create_update_request itself is a fast, single request (it only
      // kicks off a SuperDocs chat/async job and writes a PENDING row --
      // see main.py) -- the actual AI drafting happens after this call
      // returns, which is why the Review tab polls for the diff rather
      // than this page waiting for it.
      await progressUI.runStaged(
        "Submitting update",
        [`Sending instruction to SuperDocs for "${selectedDoc?.title ?? "this document"}"`, "Opening a pending review entry"],
        () => api.createUpdateRequest(selectedDocId, instruction.trim()),
        { cadenceMs: 500, detail: "SuperDocs drafts the actual edit in the background — you'll see the diff appear on the Review tab." }
      );
      setInstruction("");
      setSubmitted(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="update-shell" style={{ maxWidth: 820 }}>
      <div className="eyebrow"><IconSparkle size={13} /> Update</div>
      <h1>Update a Policy or Procedure</h1>
      <p className="lede">
        Choose a document and describe the change in plain language. SuperDocs proposes the edit;
        nothing is applied until it's reviewed and approved on the Review tab. If the document is a
        policy, approving it automatically proposes matching updates to every procedure that
        references the section that changed -- each one gets its own independent review.
      </p>

      {error && <div className="error-banner">{error}</div>}
      {submitted && (
        <div className="card glass-strong row between" style={{ marginBottom: 18 }}>
          <span>Submitted -- check the Review tab once SuperDocs has proposed the edit.</span>
          <button className="btn" onClick={() => router.push(`/w/${workspaceId}/review`)}>Go to Review</button>
        </div>
      )}

      <div className="card glass-strong">
        <label className="muted" style={{ display: "block", marginBottom: 6, fontSize: 12 }}>Document</label>
        <select value={selectedDocId} onChange={(e) => setSelectedDocId(e.target.value)} disabled={submitting} style={{ marginBottom: 12 }}>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>{d.doc_type === "policy" ? "Policy" : "Procedure"} -- {d.title}</option>
          ))}
        </select>

        <label className="muted" style={{ display: "block", marginBottom: 6, fontSize: 12 }}>What would you like to change?</label>
        <div className="chat-row">
          <textarea
            value={instruction} onChange={(e) => setInstruction(e.target.value)} disabled={submitting}
            placeholder='e.g. "Update Section 4 so that claims must be reviewed before submission"'
          />
          <button className="primary" onClick={submit} disabled={submitting || !instruction.trim() || !selectedDocId}>
            <IconSparkle size={14} /> {submitting ? "Submitting..." : "Submit"}
          </button>
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
