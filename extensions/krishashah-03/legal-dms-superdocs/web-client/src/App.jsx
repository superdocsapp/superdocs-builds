import { useState } from "react";
import * as api from "./api";
import MatterDocumentList from "./components/MatterDocumentList";
import CheckoutPanel from "./components/CheckoutPanel";
import EditForm from "./components/EditForm";
import RedlineCard from "./components/RedlineCard";
import CheckinForm from "./components/CheckinForm";
import VersionHistory from "./components/VersionHistory";
import UploadForm from "./components/UploadForm";

export default function App() {
  const [matterId, setMatterId] = useState("matter-acme-nda");
  const [userId, setUserId] = useState("attorney-priya");
  const [documents, setDocuments] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [checkedOut, setCheckedOut] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [pendingChanges, setPendingChanges] = useState([]);
  const [versions, setVersions] = useState([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function reportError(err) {
    setError(err.message || String(err));
    setStatus("");
  }

  async function refreshVersions(documentId) {
    try {
      setVersions(await api.listVersions(matterId, documentId, userId));
    } catch (err) {
      reportError(err);
    }
  }

  async function handleLoadDocuments() {
    setError("");
    setBusy(true);
    try {
      const docs = await api.listDocuments(matterId, userId);
      setDocuments(docs);
      setStatus(`Loaded ${docs.length} document(s) in ${matterId}.`);
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleSelectDocument(doc) {
    setSelectedDoc(doc);
    setCheckedOut(false);
    setPendingChanges([]);
    setJobId(null);
    setError("");
    await refreshVersions(doc.document_id);
  }

  async function handleCheckout() {
    if (!selectedDoc) return;
    setError("");
    setBusy(true);
    try {
      const result = await api.checkoutDocument(matterId, selectedDoc.document_id, userId);
      setCheckedOut(true);
      setStatus(`Checked out - version ${result.version_loaded} loaded.`);
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleDiscardCheckout() {
    if (!selectedDoc) return;
    setBusy(true);
    try {
      await api.discardCheckout(matterId, selectedDoc.document_id, userId);
      setCheckedOut(false);
      setPendingChanges([]);
      setJobId(null);
      setStatus("Checkout discarded - no version created.");
      await handleLoadDocuments();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleProposeEdit(instruction) {
    if (!selectedDoc) return;
    setError("");
    setBusy(true);
    setStatus("Asking SuperDocs to propose an edit - this can take a while on larger documents. That's normal, not a crash.");
    try {
      const result = await api.proposeEdit(matterId, selectedDoc.document_id, userId, instruction);
      setJobId(result.job_id);
      setPendingChanges(result.pending_changes);
      setStatus(
        result.pending_changes.length === 0
          ? "No changes proposed - the AI may not have understood the instruction, or the content already exists."
          : `${result.pending_changes.length} change(s) proposed - review below.`
      );
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleDecision(change, approved) {
    if (!selectedDoc || !jobId) return;
    setBusy(true);
    try {
      const result = await api.reviewChanges(matterId, selectedDoc.document_id, userId, jobId, [
        { change_id: change.change_id, approved },
      ]);
      // Trust the server's remaining_pending_changes as the new full list,
      // rather than just removing the one just decided from local state.
      // SuperDocs can surface a change that was never part of the original
      // edit response - filtering locally silently drops it, and nothing
      // then stops check-in from proceeding as if review were complete.
      const remaining = result.remaining_pending_changes || [];
      setPendingChanges(remaining);
      if (remaining.length > 0) {
        setStatus(
          `${remaining.length} more change(s) to review - SuperDocs proposed additional edits.`
        );
      } else {
        setStatus(approved ? "Change approved." : "Change rejected - document untouched.");
      }
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleCheckin(versionComment) {
    if (!selectedDoc) return;
    setBusy(true);
    try {
      const result = await api.checkinDocument(matterId, selectedDoc.document_id, userId, versionComment);
      setStatus(`Checked in as version ${result.new_version}.`);
      setCheckedOut(false);
      setPendingChanges([]);
      setJobId(null);
      await refreshVersions(selectedDoc.document_id);
      await handleLoadDocuments();
    } catch (err) {
      if (err.detail?.pending_changes) {
        // The server refused because SuperDocs still has undecided changes
        // on this session - show them instead of just an error string.
        setPendingChanges(err.detail.pending_changes);
      }
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(title, file) {
    setError("");
    setBusy(true);
    try {
      const result = await api.uploadDocument(matterId, userId, title, file);
      setStatus(`Uploaded - new document at version ${result.version_number}.`);
      await handleLoadDocuments();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="border-b border-slate/30 px-8 py-6">
        <h1 className="font-doc text-3xl">Legal DMS</h1>
        <p className="text-slate text-sm">SuperDocs integration - matter-scoped review and versioning</p>
      </header>

      <main className="mx-auto max-w-5xl px-8 py-8 grid grid-cols-1 lg:grid-cols-[1.1fr_1.4fr] gap-8">
        <div className="space-y-6">
          <MatterDocumentList
            matterId={matterId}
            userId={userId}
            documents={documents}
            selectedDocumentId={selectedDoc?.document_id}
            busy={busy}
            onMatterIdChange={setMatterId}
            onUserIdChange={setUserId}
            onLoad={handleLoadDocuments}
            onSelect={handleSelectDocument}
          />
          <UploadForm busy={busy} onUpload={handleUpload} />
          {selectedDoc && (
            <VersionHistory
              matterId={matterId}
              documentId={selectedDoc.document_id}
              userId={userId}
              versions={versions}
            />
          )}
        </div>

        <div className="space-y-6">
          {(status || error) && (
            <div
              className={`rounded-lg border px-4 py-3 text-sm ${
                error ? "border-redline/40 bg-redline/5 text-redline" : "border-slate/30 bg-slate/5 text-slate"
              }`}
            >
              {error || status}
            </div>
          )}

          {selectedDoc && (
            <CheckoutPanel
              document={selectedDoc}
              checkedOut={checkedOut}
              busy={busy}
              onCheckout={handleCheckout}
              onDiscard={handleDiscardCheckout}
            />
          )}

          {selectedDoc && checkedOut && <EditForm busy={busy} onSubmit={handleProposeEdit} />}

          {pendingChanges.length > 0 && (
            <div className="space-y-4">
              {pendingChanges.map((change) => (
                <RedlineCard key={change.change_id} change={change} busy={busy} onDecision={handleDecision} />
              ))}
            </div>
          )}

          {selectedDoc && checkedOut && <CheckinForm busy={busy} onSubmit={handleCheckin} />}
        </div>
      </main>
    </div>
  );
}