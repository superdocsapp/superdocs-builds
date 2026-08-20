import { useState } from "react";

import {
  createEmailContract,
  generateEmailContract,
  exportEmailContract,
} from "../api/emailContract";
import { approveAllChanges } from "../api/freightClaim";

export default function EmailContract() {
  const [contractType, setContractType] = useState("Standard Agreement");
  const [contractHtml, setContractHtml] = useState("");
  const [thread, setThread] = useState("");

  const [contractId, setContractId] = useState("");

  const [sessionId, setSessionId] = useState("");

  const [jobId, setJobId] = useState("");

  const [pendingChanges, setPendingChanges] = useState([]);

  const [status, setStatus] = useState("ready");

  const [loading, setLoading] = useState(false);

  const [message, setMessage] = useState("");
  async function handleExport() {
    if (!contractId) {
      setMessage("Generate the contract first.");
      return;
    }

    setLoading(true);
    setMessage("");

    try {
      const response = await exportEmailContract(contractId);

      const blob = response.data;

      const url = window.URL.createObjectURL(blob);

      const link = document.createElement("a");

      link.href = url;

      link.download = `email-contract-${contractId}.pdf`;

      document.body.appendChild(link);

      link.click();

      link.remove();

      window.URL.revokeObjectURL(url);

      setStatus("exported");

      setMessage("Contract exported successfully.");
    } catch (error) {
      setMessage(error?.response?.data?.detail || "Contract export failed.");
    } finally {
      setLoading(false);
    }
  }
  async function handleGenerate() {
    if (!thread.trim()) {
      setMessage("Paste the negotiation thread first.");
      return;
    }

    setLoading(true);
    setMessage("");
    setContractHtml("");

    try {
      const created = await createEmailContract({
        negotiationThread: thread,
        contractType,
      });

      setContractId(created.contract_id);
      setSessionId(created.session_id);
      const generated = await generateEmailContract({
        contractId: created.contract_id,
        negotiationThread: thread,
        contractType,
      });

      const findUpdatedHtml = (value) => {
        if (!value) {
          return "";
        }

        if (
          typeof value === "object" &&
          typeof value.document_changes?.updated_html === "string"
        ) {
          return value.document_changes.updated_html;
        }

        if (typeof value === "object") {
          for (const key of Object.keys(value)) {
            const result = findUpdatedHtml(value[key]);

            if (result) {
              return result;
            }
          }
        }

        if (typeof value === "string") {
          try {
            const parsed = JSON.parse(value);

            return findUpdatedHtml(parsed);
          } catch {
            return "";
          }
        }

        return "";
      };

      console.log(
        "FULL GENERATED RESPONSE:",
        JSON.stringify(generated, null, 2),
      );

      const updatedHtml = findUpdatedHtml(generated);

      console.log("FOUND CONTRACT HTML:", updatedHtml);

      console.log("CONTRACT HTML LENGTH:", updatedHtml.length);

      setContractHtml(updatedHtml);

      const superdocs = generated?.superdocs_response ?? generated;

      const changes =
        superdocs?.document_changes?.pending_changes ||
        superdocs?.pending_changes ||
        [];

      setJobId(superdocs?.job_id || generated?.job_id || "");

      setPendingChanges(changes);

      setStatus("generated");

      setMessage(
        updatedHtml
          ? "Contract draft generated successfully."
          : "Contract generated, but document HTML was not found.",
      );
    } catch (error) {
      console.error("EMAIL CONTRACT ERROR:", error);

      setMessage(
        error?.response?.data?.detail || "Contract generation failed.",
      );
    } finally {
      setLoading(false);
    }
  }
  async function handleApprove() {
    if (!sessionId || !jobId) {
      setMessage("No approval job is available.");
      return;
    }

    if (!pendingChanges.length) {
      setMessage("There are no pending changes.");
      return;
    }

    setLoading(true);
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

      setMessage("Contract changes approved.");
    } catch (error) {
      setMessage(error?.response?.data?.detail || "Approval failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="email-contract-page">
      <div className="email-contract-header">
        <div>
          <h1>Email → Contract</h1>

          <p>Turn a negotiation thread into a first-pass contract.</p>
        </div>

        <span className="contract-status">{status}</span>
      </div>

      <div className="contract-grid">
        <section className="contract-card">
          <div className="card-heading">
            <span className="step-number">01</span>

            <div>
              <h2>Negotiation Thread</h2>

              <p>Paste the fictional email conversation below.</p>
            </div>
          </div>

          <textarea
            value={thread}
            onChange={(e) => setThread(e.target.value)}
            placeholder={`From: Sarah
To: John

Hi John,

We can agree to the following:

Payment: $50,000
Contract term: 12 months
Termination notice: 30 days

Please confirm.

From: John
To: Sarah

Confirmed. We agree to all three terms.`}
            rows={18}
          />

          <div className="contract-options">
            <label>Contract type</label>

            <select
              value={contractType}
              onChange={(e) => setContractType(e.target.value)}
            >
              <option>Standard Agreement</option>

              <option>Service Agreement</option>

              <option>Sales Agreement</option>
            </select>
          </div>

          <button
            className="primary-action"
            onClick={handleGenerate}
            disabled={loading}
          >
            {loading ? "Generating..." : "Generate Contract"}
          </button>
        </section>

        <section className="contract-card">
          <div className="card-heading">
            <span className="step-number">02</span>

            <div>
              <h2>Contract Review</h2>

              <p>Proposed changes require human approval.</p>
            </div>
          </div>

          {contractId && (
            <>
              <div className="contract-info">
                <div>
                  <span>Contract ID</span>
                  <strong>{contractId}</strong>
                </div>

                <div>
                  <span>Session</span>
                  <strong>{sessionId}</strong>
                </div>
              </div>

              <div className="terms-section">
                <h3>Generated Contract</h3>

                {contractHtml ? (
                  <div
                    className="generated-contract"
                    dangerouslySetInnerHTML={{
                      __html: contractHtml,
                    }}
                  />
                ) : (
                  <div className="contract-empty">
                    <h3>Contract content unavailable</h3>
                    <p>
                      The contract was generated, but no document HTML was
                      returned.
                    </p>
                  </div>
                )}
              </div>

              <div className="terms-section">
                <h3>Approval</h3>

                {pendingChanges.length === 0 ? (
                  <div className="approved-state">
                    <span>✓</span>

                    <div>
                      <strong>No pending changes</strong>

                      <p>SuperDocs returned this document as auto-approved.</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* your existing changes list */}

                    <button
                      className="approve-action"
                      onClick={handleApprove}
                      disabled={loading}
                    >
                      Approve Contract
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </section>
        <div className="terms-section">
          <h3>Export</h3>

          <button
            className="primary-action"
            onClick={handleExport}
            disabled={loading || !contractId}
          >
            Export Contract PDF
          </button>
        </div>
      </div>

      {message && <div className="contract-message">{message}</div>}
    </div>
  );
}
