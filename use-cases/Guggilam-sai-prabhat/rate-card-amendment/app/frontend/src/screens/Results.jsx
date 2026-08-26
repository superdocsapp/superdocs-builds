import { useEffect, useState } from "react";
import { getControlReport } from "../api.js";
import StateBadge from "../components/StateBadge.jsx";

export default function Results({ run, lastExport, onBack }) {
  const [report, setReport] = useState(null);

  useEffect(() => {
    getControlReport(run.run_id).then(setReport);
  }, [run.run_id]);

  function download(filename, content) {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="screen">
      <button className="link-back" onClick={onBack}>
        ← Back to dashboard
      </button>
      <h1>4. Results</h1>

      {lastExport && (
        <div className="export-block">
          <h2>Exported artifacts — case {lastExport.case_id.slice(0, 8)}</h2>
          <div className="download-row">
            <button onClick={() => download("amended_contract.md", lastExport.exported_contract_text)}>
              Download amended contract
            </button>
            <button onClick={() => download("amendment_letter.md", lastExport.exported_letter_text)}>
              Download amendment letter
            </button>
          </div>
          <details>
            <summary>Preview amended contract</summary>
            <pre className="letter-preview">{lastExport.exported_contract_text}</pre>
          </details>
          <details>
            <summary>Preview amendment letter</summary>
            <pre className="letter-preview">{lastExport.exported_letter_text}</pre>
          </details>
        </div>
      )}

      <h2>Consolidated control report</h2>
      {!report && <p className="muted">Loading…</p>}
      {report && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Partner</th>
                <th>Contract ID</th>
                <th>State</th>
                <th>Eligibility</th>
                <th>Mechanism</th>
                <th>Exported</th>
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row) => (
                <tr key={row.case_id}>
                  <td>{row.partner_name}</td>
                  <td>{row.contract_identifier}</td>
                  <td>
                    <StateBadge state={row.state} />
                  </td>
                  <td>{row.eligibility_status}</td>
                  <td className="small">{row.amendment_mechanism || "—"}</td>
                  <td>{row.exported ? "✓" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Excluded or escalated contracts</h2>
      {report && report.excluded_or_escalated.length === 0 && <p className="muted">None.</p>}
      {report && report.excluded_or_escalated.length > 0 && (
        <ul className="excluded-list">
          {report.excluded_or_escalated.map((row) => (
            <li key={row.case_id}>
              <strong>{row.partner_name}</strong> — <StateBadge state={row.state} /> —{" "}
              {row.eligibility_status}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
