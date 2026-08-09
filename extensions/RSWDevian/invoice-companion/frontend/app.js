const { useState } = React;

const API = "http://127.0.0.1:8000";
const TENANT = "review-ui";
const fixture = {
  schema_version: "invoice.v1",
  invoice_id: "INV-1007",
  issue_date: "2026-08-08",
  due_date: "2026-09-07",
  seller: { name: "Northwind Components", tax_id: "SYN-SELLER-01" },
  buyer: { name: "Fabrikam Labs", tax_id: "SYN-BUYER-01" },
  currency: "USD",
  line_items: [{ row_id: "row-1", description: "Sensor assembly", quantity: "4", unit_price: "125.00", line_total: "500.00", source_pointer: "payload.line_items[0]" }],
  subtotal: "500.00", tax: "50.00", total: "550.00", payment_terms: "Net 30"
};

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", "X-Tenant-ID": TENANT, ...(options.headers || {}) }
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "Request failed");
  return body;
}

function Badge({ children, tone = "neutral" }) {
  return React.createElement("span", { className: `badge ${tone}` }, children);
}

function Panel({ eyebrow, title, children, className = "" }) {
  return React.createElement("section", { className: `panel ${className}` },
    React.createElement("div", { className: "eyebrow" }, eyebrow),
    React.createElement("h2", null, title), children);
}

function App() {
  const [run, setRun] = useState(null);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mutated, setMutated] = useState(false);
  const [exported, setExported] = useState(null);

  async function start() {
    setBusy(true); setError(""); setExported(null);
    try {
      const invoice = structuredClone(fixture);
      const created = await request("/v1/builds/invoice", { method: "POST", body: JSON.stringify({ invoice }) });
      setRun(created);
      setReview(await request(`/v1/runs/${created.run_id}/review`));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function mutateTotal() {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const current = await request(`/v1/runs/${run.run_id}`);
      const document = { ...current.document };
      document.fields = { ...current.document.fields, total: "650.00" };
      const updated = await request(`/v1/runs/${run.run_id}/chat`, { method: "POST", body: JSON.stringify({ document }) });
      setRun(updated); setReview(await request(`/v1/runs/${run.run_id}/review`)); setMutated(true);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function decide(itemId, decision) {
    setBusy(true); setError("");
    try {
      const updated = await request(`/v1/runs/${run.run_id}/review/${itemId}`, { method: "POST", body: JSON.stringify({ decision, approver: "reviewer-ui" }) });
      setRun(updated); setReview(await request(`/v1/runs/${run.run_id}/review`));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function exportInvoice(format) {
    setBusy(true); setError("");
    try { setExported(await request(`/v1/runs/${run.run_id}/export`, { method: "POST", body: JSON.stringify({ format }) })); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const stateTone = run?.state === "passed" ? "good" : run ? "bad" : "neutral";
  return React.createElement("main", null,
    React.createElement("header", { className: "topbar" },
      React.createElement("div", { className: "brand-mark" }, "IC"),
      React.createElement("div", null, React.createElement("div", { className: "eyebrow" }, "FINANCE WORKFLOW"), React.createElement("h1", null, "Invoice Companion")),
      React.createElement("div", { className: "header-actions" }, React.createElement(Badge, { tone: stateTone }, run?.state || "no active run"), React.createElement("button", { className: "primary", onClick: start, disabled: busy }, busy ? "Working..." : "Start fixture"))
    ),
    error && React.createElement("div", { className: "alert" }, React.createElement("strong", null, "Action refused: "), error),
    !run && React.createElement("div", { className: "empty" }, React.createElement("div", { className: "empty-icon" }, "01"), React.createElement("h2", null, "Start a reviewable invoice run"), React.createElement("p", null, "The fixture uses one immutable source record. Start it to inspect facts, provenance, findings, and export gates.")),
    run && React.createElement("div", { className: "workspace" },
      React.createElement(Panel, { eyebrow: "01 / SOURCE OF TRUTH", title: "Source facts", className: "facts" },
        React.createElement("div", { className: "fact-grid" },
          ["invoice_id", "issue_date", "due_date", "currency", "subtotal", "tax", "total", "payment_terms"].map(key => React.createElement("div", { className: "fact", key }, React.createElement("span", null, key.replaceAll("_", " ")), React.createElement("strong", null, run.reconciliation.status === "failed" && key === "total" ? "550.00" : fixture[key])))
        ), React.createElement("div", { className: "hash" }, "SOURCE HASH ", run.source_hash)
      ),
      React.createElement(Panel, { eyebrow: "02 / DOCUMENT", title: "Human-readable invoice", className: "document" },
        React.createElement("div", { className: "paper" }, React.createElement("div", { className: "paper-head" }, React.createElement("span", null, "INVOICE"), React.createElement("strong", null, run.reconciliation.status === "failed" && mutated ? "INV-1007" : "INV-1007")), React.createElement("h3", null, "Northwind Components"), React.createElement("p", null, "Bill to: Fabrikam Labs"), React.createElement("table", null, React.createElement("thead", null, React.createElement("tr", null, ["Description", "Qty", "Unit", "Total"].map(x => React.createElement("th", { key: x }, x)))), React.createElement("tbody", null, fixture.line_items.map(row => React.createElement("tr", { key: row.row_id }, React.createElement("td", null, row.description), React.createElement("td", null, row.quantity), React.createElement("td", null, `$${row.unit_price}`), React.createElement("td", null, `$${row.line_total}`))))), React.createElement("div", { className: "paper-total" }, "TOTAL ", React.createElement("strong", null, mutated ? "$650.00" : "$550.00"))), React.createElement("button", { className: "danger-outline", onClick: mutateTotal, disabled: busy || mutated }, mutated ? "Deliberate mismatch applied" : "Demo failure: change total to $650.00")
      ),
      React.createElement(Panel, { eyebrow: "03 / VERIFICATION", title: "Reconciliation findings", className: "findings" },
        run.reconciliation.findings.length === 0 ? React.createElement("div", { className: "clean" }, React.createElement("span", null, "✓"), React.createElement("div", null, React.createElement("strong", null, "No findings"), React.createElement("p", null, "Every checked value resolves to the canonical source."))) : React.createElement("div", { className: "finding-list" }, run.reconciliation.findings.map((finding, index) => React.createElement("div", { className: "finding", key: index }, React.createElement(Badge, { tone: "bad" }, finding.severity), React.createElement("strong", null, finding.location), React.createElement("p", null, finding.message), React.createElement("code", null, `${finding.expected ?? "not supported"}  →  ${finding.observed ?? "missing"}`), React.createElement("small", null, finding.source_pointer || "No source pointer"))))
      ),
      React.createElement(Panel, { eyebrow: "04 / DECISION", title: "Review and audit history", className: "audit" },
        review?.items?.length ? review.items.map(item => React.createElement("div", { className: "decision", key: item.item_id }, React.createElement("div", null, React.createElement("strong", null, item.item_id), React.createElement("span", null, item.decision)), item.decision === "pending" && React.createElement("div", { className: "decision-actions" }, React.createElement("button", { onClick: () => decide(item.item_id, "approved"), disabled: busy }, "Approve disposition"), React.createElement("button", { className: "quiet", onClick: () => decide(item.item_id, "accepted_exception"), disabled: busy }, "Accept exception")))) : React.createElement("p", { className: "muted" }, "No review decisions required for this clean run."),
        React.createElement("div", { className: "export-row" }, React.createElement("span", null, "Verified export"), React.createElement("button", { onClick: () => exportInvoice("docx"), disabled: busy || run.state !== "passed" }, "DOCX"), React.createElement("button", { onClick: () => exportInvoice("pdf"), disabled: busy || run.state !== "passed" }, "PDF")),
        exported && React.createElement("div", { className: "certificate" }, React.createElement(Badge, { tone: "good" }, "EXPORTED"), ` artifact ${exported.artifact_hash}`)
      )
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
