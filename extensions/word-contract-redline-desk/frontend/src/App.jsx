import { useEffect, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function App() {
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  async function loadReview() {
    try {
      const response = await fetch(`${API}/review`);

      if (!response.ok) {
        throw new Error("Failed to load review");
      }

      const data = await response.json();
      setProposals(data.proposals);
    } catch (error) {
      setMessage("Could not connect to SuperDocs backend.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadReview();
  }, []);

  function decide(id, decision) {
    setProposals((current) =>
      current.map((proposal) =>
        proposal.id === id
          ? { ...proposal, status: decision }
          : proposal
      )
    );

    setMessage(
      decision === "approved"
        ? "Change approved."
        : "Change rejected."
    );
  }

  async function exportDocument() {
    const pending = proposals.some(
      (proposal) => proposal.status === "pending"
    );

    if (pending) {
      setMessage(
        "Every proposal must be approved or rejected before export."
      );
      return;
    }

    try {
      const response = await fetch(`${API}/export`, {
        method: "POST",
      });

      if (!response.ok) {
        const error = await response.json();
        setMessage(error.detail || "Export failed.");
        return;
      }

      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download = "redlined_contract.docx";

      document.body.appendChild(link);
      link.click();
      link.remove();

      window.URL.revokeObjectURL(url);

      setMessage("Redlined DOCX exported successfully.");
    } catch (error) {
      setMessage("Could not connect to the backend.");
    }
  }

  if (loading) {
    return (
      <div className="container">
        <h1>SuperDocs Contract Redline Desk</h1>
        <p>Loading contract review...</p>
      </div>
    );
  }

  return (
    <div className="container">
      <header>
        <h1>SuperDocs Contract Redline Desk</h1>
        <p>
          Review proposed contract changes before they are applied.
        </p>
      </header>

      {proposals.length === 0 && (
        <div className="card">
          <h2>No proposed changes</h2>
          <p>
            SuperDocs did not identify any changes requiring review.
          </p>
        </div>
      )}

      {proposals.map((proposal) => (
        <div className="card" key={proposal.id}>
          <div className="card-header">
            <h2>{proposal.clause}</h2>

            <span className={`status ${proposal.status}`}>
              {proposal.status}
            </span>
          </div>

          <div className="section">
            <h3>BEFORE</h3>

            <div className="before">
              {proposal.before}
            </div>
          </div>

          <div className="section">
            <h3>AFTER</h3>

            <div className="after">
              {proposal.after}
            </div>
          </div>

          <div className="reason">
            <strong>Reason:</strong>{" "}
            {proposal.reason}
          </div>

          <div className="actions">
            <button
              className="approve"
              onClick={() =>
                decide(proposal.id, "approved")
              }
              disabled={proposal.status === "approved"}
            >
              ✓ Approve
            </button>

            <button
              className="reject"
              onClick={() =>
                decide(proposal.id, "rejected")
              }
              disabled={proposal.status === "rejected"}
            >
              ✕ Reject
            </button>
          </div>
        </div>
      ))}

      <div className="footer">
        <button
          className="export"
          onClick={exportDocument}
          disabled={
            proposals.length === 0 ||
            proposals.some(
              (proposal) =>
                proposal.status === "pending"
            )
          }
        >
          Export Redlined DOCX
        </button>

        {message && (
          <p className="message">{message}</p>
        )}
      </div>
    </div>
  );
}

export default App;