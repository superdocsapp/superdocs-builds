import { useState } from "react";
import { createRun, uuid } from "../api.js";
import FailureBanner from "../components/FailureBanner.jsx";

export default function Intake({ onRunCreated }) {
  const [contracts, setContracts] = useState([]);
  const [oldRateCard, setOldRateCard] = useState(null);
  const [newRateCard, setNewRateCard] = useState(null);
  const [effectiveDate, setEffectiveDate] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState(null);
  const [idempotencyKey] = useState(uuid());

  async function handleSubmit(event) {
    event.preventDefault();
    setFailure(null);
    if (!contracts.length || !newRateCard || !effectiveDate) {
      setFailure({
        what: "the intake form is incomplete",
        likely_cause: "at least one contract, a new rate card, and a proposed effective date are required",
        next_action: "fill in the missing field(s) and resubmit",
      });
      return;
    }
    setSubmitting(true);
    try {
      const run = await createRun({
        contracts,
        oldRateCard,
        newRateCard,
        effectiveDate,
        dryRun,
        idempotencyKey,
      });
      onRunCreated(run);
    } catch (error) {
      setFailure(error.detail || { what: error.message, likely_cause: "unknown", next_action: "retry" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="screen">
      <h1>1. Intake</h1>
      <p className="subtitle">Upload partner contracts and the new rate card, then choose a proposed effective date.</p>
      <FailureBanner failure={failure} />
      <form onSubmit={handleSubmit} className="intake-form">
        <label>
          Partner contracts (multiple)
          <input
            type="file"
            multiple
            accept=".md,.txt"
            onChange={(e) => setContracts(Array.from(e.target.files))}
          />
          {contracts.length > 0 && <div className="file-list">{contracts.map((f) => f.name).join(", ")}</div>}
        </label>

        <label>
          Old rate card (optional, for comparison)
          <input type="file" accept=".csv" onChange={(e) => setOldRateCard(e.target.files[0] || null)} />
        </label>

        <label>
          New rate card (required)
          <input type="file" accept=".csv" onChange={(e) => setNewRateCard(e.target.files[0] || null)} />
        </label>

        <label>
          Proposed effective date
          <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </label>

        <label>
          Amendment-letter template
          <select defaultValue="amendment_letter_template.md">
            <option value="amendment_letter_template.md">amendment_letter_template.md</option>
          </select>
        </label>

        <label className="checkbox-label">
          <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
          Dry run (analyze only; do not call SuperDocs or propose edits)
        </label>

        <button type="submit" disabled={submitting}>
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </form>
    </div>
  );
}
