import { useRef, useState } from "react";

import {
  uploadClaimEvidence,
  generateClaim,
  buildClaimPacket,
  generateChaser,
  approveAllChanges,
  exportFreightClaim,
} from "../api/freightClaim";

const DOCUMENT_TYPES = [
  { value: "pod", label: "POD" },
  { value: "invoice", label: "Invoice" },
  { value: "damage_photo", label: "Damage Photo" },
  { value: "repair_quote", label: "Repair Quote" },
  { value: "salvage_quote", label: "Salvage Quote" },
];

const STATUS_LABELS = {
  ready: "Ready",
  uploaded: "Evidence uploaded",
  claim_generated: "Claim generated",
  packet_generated: "Packet ready",
  chaser_generated: "Chaser ready",
  approved: "Approved",
  exported: "Exported",
};

function FileIcon({ type }) {
  const image = type?.startsWith("image/");
  return (
    <div className={`fc-file-icon ${image ? "image" : ""}`}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
      >
        {image ? (
          <>
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <circle cx="8.5" cy="9" r="1.5" />
            <path d="m4 17 5-5 3 3 2-2 6 5" />
          </>
        ) : (
          <>
            <path d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
            <path d="M14 3v5h5" />
            <path d="M8 13h8M8 17h6" />
          </>
        )}
      </svg>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 20h14a2 2 0 0 0 2-2v-3" />
      <path d="M3 15v3a2 2 0 0 0 2 2" />
    </svg>
  );
}

function Spinner() {
  return <span className="fc-spinner" aria-hidden="true" />;
}

export default function FreightClaim() {
  const fileInputRef = useRef(null);

  const [carrier, setCarrier] = useState("FedEx");
  const [files, setFiles] = useState([]);
  const [documentTypes, setDocumentTypes] = useState([]);

  const [claimId, setClaimId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [jobId, setJobId] = useState("");
  const [pendingChanges, setPendingChanges] = useState([]);

  const [status, setStatus] = useState("ready");
  const [loadingAction, setLoadingAction] = useState("");
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("info");
  const [chaserDate, setChaserDate] = useState("");

  function showMessage(text, type = "info") {
    setMessage(text);
    setMessageType(type);
  }

  function addFiles(selected) {
    if (!selected.length) return;

    const incoming = Array.from(selected);
    const existingKeys = new Set(
      files.map((file) => `${file.name}-${file.size}-${file.lastModified}`),
    );

    const newFiles = incoming.filter(
      (file) =>
        !existingKeys.has(`${file.name}-${file.size}-${file.lastModified}`),
    );

    if (!newFiles.length) {
      showMessage("Those files are already selected.", "warning");
      return;
    }

    setFiles((current) => [...current, ...newFiles]);
    setDocumentTypes((current) => [
      ...current,
      ...newFiles.map(() => "invoice"),
    ]);
    showMessage(
      `${newFiles.length} file${newFiles.length > 1 ? "s" : ""} added. Choose the evidence type for each file.`,
      "success",
    );

    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleFilesChange(event) {
    addFiles(event.target.files || []);
  }

  function handleDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.remove("dragging");
    addFiles(event.dataTransfer.files || []);
  }

  function removeFile(index) {
    setFiles((current) => current.filter((_, i) => i !== index));
    setDocumentTypes((current) => current.filter((_, i) => i !== index));
    showMessage("File removed from the upload list.", "info");
  }

  function updateDocumentType(index, value) {
    setDocumentTypes((current) => {
      const next = [...current];
      next[index] = value;
      return next;
    });
  }

  function resetSelection() {
    setFiles([]);
    setDocumentTypes([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
    showMessage("Selected files cleared.", "info");
  }

  async function handleUpload() {
    if (!carrier.trim()) {
      showMessage("Enter the carrier name first.", "error");
      return;
    }

    if (!files.length) {
      showMessage("Select at least one evidence file.", "error");
      return;
    }

    const missingTypes = documentTypes.some((type) => !type);
    if (missingTypes) {
      showMessage("Choose an evidence type for every file.", "error");
      return;
    }

    setLoadingAction("upload");
    setMessage("");

    try {
      const result = await uploadClaimEvidence({
        carrier,
        files,
        documentTypes,
      });

      setClaimId(result.claim_id);
      setSessionId(result.session_id);
      setStatus(result.status || "uploaded");

      showMessage(
        `${files.length} evidence file${files.length > 1 ? "s" : ""} uploaded successfully.`,
        "success",
      );
    } catch (error) {
      showMessage(
        error?.response?.data?.detail || "Evidence upload failed.",
        "error",
      );
    } finally {
      setLoadingAction("");
    }
  }

  async function handleGenerate() {
    if (!sessionId) {
      showMessage("Upload your evidence first.", "error");
      return;
    }

    setLoadingAction("generate");
    setMessage("");

    try {
      const result = await generateClaim({ sessionId, carrier });
      const superdocs = result.superdocs_response || {};
      const changes =
        superdocs?.document_changes?.pending_changes ||
        superdocs?.pending_changes ||
        [];

      setJobId(superdocs.job_id || "");
      setPendingChanges(changes);
      setStatus("claim_generated");

      showMessage("Claim letter generated successfully.", "success");
    } catch (error) {
      showMessage(
        error?.response?.data?.detail || "Claim generation failed.",
        "error",
      );
    } finally {
      setLoadingAction("");
    }
  }

  async function handleBuildPacket() {
    if (!sessionId) {
      showMessage("Upload your evidence first.", "error");
      return;
    }

    setLoadingAction("packet");
    setMessage("");

    try {
      const result = await buildClaimPacket({ sessionId, carrier });
      const superdocs = result.superdocs_response || {};
      const changes =
        superdocs?.document_changes?.pending_changes ||
        superdocs?.pending_changes ||
        [];

      setJobId(superdocs.job_id || jobId);
      setPendingChanges(changes);
      setStatus("packet_generated");

      showMessage("Freight claim packet assembled.", "success");
    } catch (error) {
      showMessage(
        error?.response?.data?.detail || "Packet generation failed.",
        "error",
      );
    } finally {
      setLoadingAction("");
    }
  }

  async function handleChaser() {
    if (!sessionId) {
      showMessage("Create the claim first.", "error");
      return;
    }

    if (!chaserDate) {
      showMessage("Select a follow-up date.", "error");
      return;
    }

    setLoadingAction("chaser");
    setMessage("");

    try {
      const result = await generateChaser({
        sessionId,
        carrier,
        followUpDate: chaserDate,
      });

      const superdocs = result.superdocs_response || {};
      const changes =
        superdocs?.document_changes?.pending_changes ||
        superdocs?.pending_changes ||
        [];

      setJobId(superdocs.job_id || jobId);
      setPendingChanges(changes);
      setStatus("chaser_generated");

      showMessage(
        "Chaser generated from the existing claim packet.",
        "success",
      );
    } catch (error) {
      showMessage(
        error?.response?.data?.detail || "Chaser generation failed.",
        "error",
      );
    } finally {
      setLoadingAction("");
    }
  }

  async function handleApproveAll() {
    if (!sessionId || !jobId) {
      showMessage("No pending approval job found.", "error");
      return;
    }

    if (!pendingChanges.length) {
      showMessage("There are no pending changes.", "info");
      return;
    }

    setLoadingAction("approve");
    setMessage("");

    try {
      await approveAllChanges({
        sessionId,
        jobId,
        changes: pendingChanges.map((change) => ({
          change_id: change.change_id,
        })),
      });

      setPendingChanges([]);
      setStatus("approved");
      showMessage("All proposed changes approved.", "success");
    } catch (error) {
      showMessage(error?.response?.data?.detail || "Approval failed.", "error");
    } finally {
      setLoadingAction("");
    }
  }

  async function handleExport() {
    if (!claimId || !sessionId) {
      showMessage("Generate a claim before exporting.", "error");
      return;
    }

    if (pendingChanges.length > 0) {
      showMessage("Approve pending changes before exporting.", "warning");
      return;
    }

    setLoadingAction("export");
    setMessage("");

    try {
      const response = await exportFreightClaim({
        claimId,
        sessionId,
        format: "pdf",
      });

      const blob = response.data;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download = `freight-claim-${claimId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setStatus("exported");
      showMessage("Freight claim exported successfully.", "success");
    } catch (error) {
      showMessage(error?.response?.data?.detail || "Export failed.", "error");
    } finally {
      setLoadingAction("");
    }
  }

  const actionBusy = (action) => loadingAction === action;
  const hasFiles = files.length > 0;

  return (
    <div className="freight-page">
      <div className="freight-container">
        <header className="freight-header">
          <div>
            <div className="eyebrow">SUPERDOCS WORKFLOW</div>
            <h1>Freight Claim</h1>
            <p>
              Assemble evidence, generate a damage claim, review changes, and
              export the final packet.
            </p>
          </div>

          <div className={`claim-status ${status}`}>
            <span className="status-dot" />
            {STATUS_LABELS[status] || status}
          </div>
        </header>

        <section className="workflow-card evidence-card">
          <div className="section-heading">
            <div className="step-badge">01</div>
            <div>
              <h2>Evidence</h2>
              <p>Add the documents that support this freight claim.</p>
            </div>
          </div>

          <div className="carrier-row">
            <label>
              Carrier
              <input
                value={carrier}
                onChange={(e) => setCarrier(e.target.value)}
                placeholder="FedEx"
              />
            </label>
          </div>

          <div
            className="dropzone"
            onDragOver={(e) => {
              e.preventDefault();
              e.currentTarget.classList.add("dragging");
            }}
            onDragLeave={(e) => e.currentTarget.classList.remove("dragging")}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                fileInputRef.current?.click();
              }
            }}
          >
            <div className="upload-circle">
              <UploadIcon />
            </div>

            <div className="dropzone-copy">
              <strong>Upload evidence files</strong>
              <span>
                Click to browse or drag files here. You can add one file or
                several at once.
              </span>
              <small>
                POD · Invoice · Damage Photo · Repair Quote · Salvage Quote
              </small>
            </div>

            <span className="browse-button">Choose files</span>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFilesChange}
              onClick={(e) => e.stopPropagation()}
              hidden
            />
          </div>

          {hasFiles && (
            <div className="selected-files">
              <div className="files-header">
                <div>
                  <h3>Selected evidence</h3>
                  <span>
                    {files.length} file{files.length !== 1 ? "s" : ""} ready for
                    upload
                  </span>
                </div>

                <button
                  type="button"
                  className="text-button"
                  onClick={resetSelection}
                  disabled={loadingAction === "upload"}
                >
                  Clear all
                </button>
              </div>

              <div className="file-list">
                {files.map((file, index) => (
                  <div
                    className="file-row"
                    key={`${file.name}-${file.size}-${index}`}
                  >
                    <FileIcon type={file.type} />

                    <div className="file-main">
                      <strong title={file.name}>{file.name}</strong>
                      <span>{formatBytes(file.size)}</span>
                    </div>

                    <select
                      value={documentTypes[index] || ""}
                      onChange={(e) =>
                        updateDocumentType(index, e.target.value)
                      }
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Evidence type for ${file.name}`}
                    >
                      {DOCUMENT_TYPES.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </select>

                    <button
                      type="button"
                      className="remove-file"
                      onClick={() => removeFile(index)}
                      disabled={loadingAction === "upload"}
                      aria-label={`Remove ${file.name}`}
                      title="Remove file"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="section-actions">
            <button
              className="primary-button"
              onClick={handleUpload}
              disabled={Boolean(loadingAction)}
            >
              {actionBusy("upload") ? (
                <>
                  <Spinner /> Uploading evidence...
                </>
              ) : (
                <>
                  <UploadIcon /> Upload{" "}
                  {files.length
                    ? `${files.length} file${files.length > 1 ? "s" : ""}`
                    : "evidence"}
                </>
              )}
            </button>
          </div>
        </section>

        <div className="workflow-grid">
          <WorkflowCard
            number="02"
            title="Generate Claim"
            description="Create the first-pass claim letter from the uploaded evidence."
          >
            <button
              className="primary-button full"
              onClick={handleGenerate}
              disabled={Boolean(loadingAction) || !sessionId}
            >
              {actionBusy("generate") ? (
                <>
                  <Spinner /> Generating claim...
                </>
              ) : (
                "Generate Claim Letter"
              )}
            </button>
          </WorkflowCard>

          <WorkflowCard
            number="03"
            title="Assemble Packet"
            description="Build the complete, indexed claim packet from the evidence."
          >
            <button
              className="primary-button full"
              onClick={handleBuildPacket}
              disabled={Boolean(loadingAction) || !sessionId}
            >
              {actionBusy("packet") ? (
                <>
                  <Spinner /> Building packet...
                </>
              ) : (
                "Build Freight Claim Packet"
              )}
            </button>
          </WorkflowCard>

          <WorkflowCard
            number="04"
            title="Chaser"
            description="Prepare a follow-up request using the existing claim packet."
          >
            <label className="date-field">
              Follow-up date
              <input
                type="date"
                value={chaserDate}
                onChange={(e) => setChaserDate(e.target.value)}
              />
            </label>

            <button
              className="secondary-button full"
              onClick={handleChaser}
              disabled={Boolean(loadingAction) || !sessionId}
            >
              {actionBusy("chaser") ? (
                <>
                  <Spinner /> Generating chaser...
                </>
              ) : (
                "Generate Chaser"
              )}
            </button>
          </WorkflowCard>

          <WorkflowCard
            number="05"
            title="Human Approval"
            description={
              pendingChanges.length
                ? `${pendingChanges.length} proposed change${pendingChanges.length > 1 ? "s" : ""} waiting for review.`
                : "Review is clear. No changes are waiting for approval."
            }
          >
            {pendingChanges.length === 0 ? (
              <div className="empty-approval">
                <span className="check-icon">✓</span>
                <div>
                  <strong>No pending changes</strong>
                  <span>The current document state is ready to continue.</span>
                </div>
              </div>
            ) : (
              <>
                <div className="changes-list">
                  {pendingChanges.map((change, index) => (
                    <div
                      className="change-item"
                      key={change.change_id || index}
                    >
                      <span>Change {index + 1}</span>
                      <strong>
                        {change.ai_explanation ||
                          change.operation ||
                          "Document change proposed"}
                      </strong>
                    </div>
                  ))}
                </div>

                <button
                  className="approve-button full"
                  onClick={handleApproveAll}
                  disabled={Boolean(loadingAction)}
                >
                  {actionBusy("approve") ? (
                    <>
                      <Spinner /> Approving...
                    </>
                  ) : (
                    "Approve All Changes"
                  )}
                </button>
              </>
            )}
          </WorkflowCard>

          <WorkflowCard
            number="06"
            title="Export"
            description="Download the reviewed freight claim as a PDF."
          >
            <button
              className="secondary-button full"
              onClick={handleExport}
              disabled={
                Boolean(loadingAction) ||
                !claimId ||
                !sessionId ||
                pendingChanges.length > 0
              }
            >
              {actionBusy("export") ? (
                <>
                  <Spinner /> Exporting PDF...
                </>
              ) : (
                "Export PDF"
              )}
            </button>

            {pendingChanges.length > 0 && (
              <small className="helper-text">
                Approve pending changes before exporting.
              </small>
            )}
          </WorkflowCard>
        </div>

        {message && (
          <div className={`toast-message ${messageType}`} role="status">
            <div className="toast-icon">
              {messageType === "success"
                ? "✓"
                : messageType === "error"
                  ? "!"
                  : "i"}
            </div>
            <span>{message}</span>
            <button
              type="button"
              onClick={() => setMessage("")}
              aria-label="Dismiss message"
            >
              ×
            </button>
          </div>
        )}
      </div>

      <style>{`
        * { box-sizing: border-box; }

        .freight-page {
          min-height: 100vh;
          padding: 40px 24px 64px;
          background:
            radial-gradient(circle at 10% 0%, rgba(37, 99, 235, .08), transparent 28%),
            #f6f8fb;
          color: #172033;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .freight-container {
          width: min(1120px, 100%);
          margin: 0 auto;
        }

        .freight-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 24px;
          margin-bottom: 28px;
        }

        .eyebrow {
          margin-bottom: 8px;
          color: #64748b;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: .16em;
        }

        .freight-header h1 {
          margin: 0;
          font-size: clamp(30px, 4vw, 42px);
          line-height: 1.05;
          letter-spacing: -.04em;
        }

        .freight-header p {
          max-width: 650px;
          margin: 10px 0 0;
          color: #64748b;
          font-size: 15px;
          line-height: 1.6;
        }

        .claim-status {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          flex: 0 0 auto;
          padding: 9px 13px;
          border: 1px solid #dbe3ef;
          border-radius: 999px;
          background: #fff;
          color: #475569;
          font-size: 13px;
          font-weight: 700;
          box-shadow: 0 4px 16px rgba(15, 23, 42, .04);
        }

        .status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: #94a3b8;
        }

        .claim-status.approved .status-dot,
        .claim-status.exported .status-dot,
        .claim-status.packet_generated .status-dot,
        .claim-status.claim_generated .status-dot,
        .claim-status.uploaded .status-dot {
          background: #16a34a;
        }

        .workflow-card,
        .evidence-card {
          border: 1px solid #e1e7ef;
          border-radius: 20px;
          background: rgba(255,255,255,.96);
          box-shadow: 0 14px 38px rgba(15, 23, 42, .055);
        }

        .evidence-card {
          padding: 28px;
          margin-bottom: 18px;
        }

        .section-heading {
          display: flex;
          align-items: flex-start;
          gap: 14px;
          margin-bottom: 24px;
        }

        .step-badge {
          display: grid;
          place-items: center;
          width: 38px;
          height: 38px;
          flex: 0 0 auto;
          border-radius: 11px;
          background: #eef4ff;
          color: #2563eb;
          font-size: 12px;
          font-weight: 800;
        }

        .section-heading h2,
        .workflow-card h2 {
          margin: 0;
          font-size: 18px;
          letter-spacing: -.02em;
        }

        .section-heading p,
        .workflow-card p {
          margin: 5px 0 0;
          color: #718096;
          font-size: 13px;
          line-height: 1.5;
        }

        .carrier-row label,
        .date-field {
          display: block;
          color: #344054;
          font-size: 12px;
          font-weight: 700;
        }

        .carrier-row input,
        .date-field input {
          display: block;
          width: 100%;
          margin-top: 8px;
          padding: 11px 13px;
          border: 1px solid #d7dee9;
          border-radius: 10px;
          background: #fff;
          color: #172033;
          outline: none;
          font: inherit;
        }

        .carrier-row input { max-width: 520px; }

        .carrier-row input:focus,
        .date-field input:focus,
        .file-row select:focus {
          border-color: #7aa2f8;
          box-shadow: 0 0 0 3px rgba(37, 99, 235, .09);
        }

        .dropzone {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-top: 20px;
          padding: 20px;
          border: 1.5px dashed #b8c5d8;
          border-radius: 15px;
          background: #fbfcfe;
          cursor: pointer;
          transition: .18s ease;
        }

        .dropzone:hover,
        .dropzone.dragging {
          border-color: #4f7ff0;
          background: #f5f8ff;
          transform: translateY(-1px);
        }

        .upload-circle {
          display: grid;
          place-items: center;
          width: 48px;
          height: 48px;
          flex: 0 0 auto;
          border-radius: 14px;
          background: #eaf1ff;
          color: #2563eb;
        }

        .upload-circle svg,
        .primary-button svg {
          width: 21px;
          height: 21px;
        }

        .dropzone-copy {
          display: flex;
          min-width: 0;
          flex: 1;
          flex-direction: column;
          gap: 3px;
        }

        .dropzone-copy strong {
          font-size: 14px;
        }

        .dropzone-copy span {
          color: #64748b;
          font-size: 13px;
        }

        .dropzone-copy small {
          margin-top: 4px;
          color: #94a3b8;
          font-size: 11px;
        }

        .browse-button {
          padding: 9px 13px;
          border: 1px solid #d5deeb;
          border-radius: 9px;
          background: #fff;
          color: #334155;
          font-size: 12px;
          font-weight: 700;
        }

        .selected-files {
          margin-top: 20px;
          overflow: hidden;
          border: 1px solid #e3e8f0;
          border-radius: 14px;
        }

        .files-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 14px 16px;
          border-bottom: 1px solid #e8edf3;
          background: #fafbfc;
        }

        .files-header h3 {
          margin: 0;
          font-size: 13px;
        }

        .files-header span {
          display: block;
          margin-top: 2px;
          color: #94a3b8;
          font-size: 11px;
        }

        .text-button {
          border: 0;
          background: transparent;
          color: #64748b;
          cursor: pointer;
          font-size: 12px;
          font-weight: 700;
        }

        .text-button:hover { color: #dc2626; }

        .file-row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 14px;
          border-bottom: 1px solid #edf1f5;
        }

        .file-row:last-child { border-bottom: 0; }

        .fc-file-icon {
          display: grid;
          place-items: center;
          width: 38px;
          height: 38px;
          flex: 0 0 auto;
          border-radius: 10px;
          background: #fff0f0;
          color: #dc4c4c;
        }

        .fc-file-icon.image {
          background: #eef7ff;
          color: #2684d9;
        }

        .fc-file-icon svg {
          width: 20px;
          height: 20px;
        }

        .file-main {
          min-width: 0;
          flex: 1;
        }

        .file-main strong {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 13px;
        }

        .file-main span {
          display: block;
          margin-top: 3px;
          color: #94a3b8;
          font-size: 11px;
        }

        .file-row select {
          width: 170px;
          padding: 9px 10px;
          border: 1px solid #d7dee9;
          border-radius: 9px;
          background: #fff;
          color: #334155;
          outline: none;
          font: inherit;
          font-size: 12px;
        }

        .remove-file {
          display: grid;
          place-items: center;
          width: 31px;
          height: 31px;
          border: 0;
          border-radius: 8px;
          background: transparent;
          color: #94a3b8;
          cursor: pointer;
          font-size: 22px;
          line-height: 1;
        }

        .remove-file:hover {
          background: #fff1f2;
          color: #dc2626;
        }

        .section-actions {
          display: flex;
          justify-content: flex-end;
          margin-top: 18px;
        }

        .primary-button,
        .secondary-button,
        .approve-button {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          min-height: 42px;
          padding: 10px 16px;
          border-radius: 10px;
          cursor: pointer;
          font: inherit;
          font-size: 13px;
          font-weight: 750;
          transition: .15s ease;
        }

        .primary-button {
          border: 1px solid #2563eb;
          background: #2563eb;
          color: #fff;
          box-shadow: 0 5px 14px rgba(37, 99, 235, .16);
        }

        .primary-button:hover:not(:disabled) {
          background: #1d4ed8;
          transform: translateY(-1px);
        }

        .secondary-button {
          border: 1px solid #d5deeb;
          background: #fff;
          color: #334155;
        }

        .secondary-button:hover:not(:disabled) {
          border-color: #9fb1c9;
          background: #f8fafc;
        }

        .approve-button {
          border: 1px solid #15803d;
          background: #15803d;
          color: #fff;
        }

        .full { width: 100%; }

        button:disabled {
          cursor: not-allowed;
          opacity: .52;
          transform: none !important;
        }

        .workflow-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 18px;
        }

        .workflow-card {
          min-height: 205px;
          padding: 22px;
        }

        .workflow-card h2 {
          margin-bottom: 4px;
        }

        .workflow-card > p {
          margin-bottom: 18px;
        }

        .date-field {
          margin: 20px 0 12px;
        }

        .empty-approval {
          display: flex;
          align-items: center;
          gap: 11px;
          margin-top: 22px;
          padding: 13px;
          border: 1px solid #dbeadf;
          border-radius: 11px;
          background: #f6fbf7;
        }

        .check-icon {
          display: grid;
          place-items: center;
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: #dcfce7;
          color: #15803d;
          font-weight: 900;
        }

        .empty-approval strong,
        .empty-approval span:last-child {
          display: block;
        }

        .empty-approval strong { font-size: 12px; }
        .empty-approval span:last-child {
          margin-top: 2px;
          color: #64748b;
          font-size: 11px;
        }

        .changes-list {
          display: grid;
          gap: 8px;
          max-height: 145px;
          margin: 18px 0;
          overflow: auto;
        }

        .change-item {
          padding: 11px 12px;
          border: 1px solid #e4e9f0;
          border-radius: 9px;
          background: #fafbfc;
        }

        .change-item span {
          display: block;
          margin-bottom: 4px;
          color: #94a3b8;
          font-size: 10px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .06em;
        }

        .change-item strong {
          color: #475569;
          font-size: 12px;
          font-weight: 600;
        }

        .helper-text {
          display: block;
          margin-top: 9px;
          color: #94a3b8;
          font-size: 11px;
          text-align: center;
        }

        .toast-message {
          position: sticky;
          bottom: 20px;
          z-index: 10;
          display: flex;
          align-items: center;
          gap: 10px;
          width: fit-content;
          max-width: min(700px, 100%);
          margin: 22px auto 0;
          padding: 11px 12px;
          border: 1px solid #dce4ee;
          border-radius: 12px;
          background: #fff;
          color: #334155;
          box-shadow: 0 12px 30px rgba(15, 23, 42, .12);
          font-size: 13px;
        }

        .toast-message.success {
          border-color: #cce8d4;
          background: #f7fcf8;
        }

        .toast-message.error {
          border-color: #f1c9c9;
          background: #fff8f8;
        }

        .toast-message.warning {
          border-color: #f0dfb5;
          background: #fffaf0;
        }

        .toast-icon {
          display: grid;
          place-items: center;
          width: 24px;
          height: 24px;
          flex: 0 0 auto;
          border-radius: 50%;
          background: #eef2f7;
          color: #475569;
          font-size: 12px;
          font-weight: 900;
        }

        .toast-message.success .toast-icon {
          background: #dcfce7;
          color: #15803d;
        }

        .toast-message.error .toast-icon {
          background: #fee2e2;
          color: #dc2626;
        }

        .toast-message.warning .toast-icon {
          background: #fef3c7;
          color: #b45309;
        }

        .toast-message button {
          width: 24px;
          height: 24px;
          margin-left: 4px;
          border: 0;
          background: transparent;
          color: #94a3b8;
          cursor: pointer;
          font-size: 19px;
        }

        .fc-spinner {
          width: 16px;
          height: 16px;
          border: 2px solid rgba(255,255,255,.45);
          border-top-color: currentColor;
          border-radius: 50%;
          animation: fc-spin .7s linear infinite;
        }

        .secondary-button .fc-spinner,
        .text-button .fc-spinner {
          color: #334155;
          border-color: #cbd5e1;
          border-top-color: #334155;
        }

        @keyframes fc-spin {
          to { transform: rotate(360deg); }
        }

        @media (max-width: 760px) {
          .freight-page { padding: 24px 14px 48px; }

          .freight-header {
            flex-direction: column;
          }

          .workflow-grid {
            grid-template-columns: 1fr;
          }

          .dropzone {
            flex-wrap: wrap;
          }

          .dropzone-copy {
            min-width: calc(100% - 70px);
          }

          .browse-button {
            width: 100%;
            text-align: center;
          }

          .file-row {
            flex-wrap: wrap;
          }

          .file-main {
            min-width: calc(100% - 60px);
          }

          .file-row select {
            width: calc(100% - 44px);
            margin-left: 50px;
          }
        }
      `}</style>
    </div>
  );
}

function WorkflowCard({ number, title, description, children }) {
  return (
    <section className="workflow-card">
      <div className="section-heading">
        <div className="step-badge">{number}</div>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
