const { useState } = React;
const API = "http://127.0.0.1:8001";
const mermaid = `flowchart TD
step_1["step_1 | Receive work order"]
step_2["step_2 | Inspect incoming material"]
step_4["step_4 | Release approved batch"]
step_1 --> step_2
step_2 --> step_4`;
const updatedMermaid = `flowchart TD
step_1["step_1 | Receive work order"]
step_2["step_2 | Inspect incoming material"]
step_3["step_3 | Verify release checks"]
step_4["step_4 | Release approved batch"]
step_1 --> step_2
step_2 --> step_3
step_3 --> step_4`;
const manual = { manual_id: "manual-001", title: "Northwind Quality Manual", organization: "Northwind Components", revision: 1, status: "review-ready", effective_date: "2026-08-09", sections: [{ section_id: "process-control", clause_ref: "8.5", title: "Process Control", body_blocks: [{ type: "step", step_id: "step_1", text: "Receive work order." }, { type: "step", step_id: "step_2", text: "Inspect incoming material." }, { type: "step", step_id: "step_4", text: "Release approved batch." }], diagram_ref: "diagram-control", source_refs: ["fixture.process"] }], diagrams: [{ diagram_id: "diagram-control", source_kind: "mermaid", source_text: mermaid, nodes: {}, edges: [], rendered_asset_hash: "" }], revision_history: [] };

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "Request failed");
  return body;
}
function Badge({ children, tone = "neutral" }) { return React.createElement("span", { className: `badge ${tone}` }, children); }
function Panel({ eyebrow, title, children, className = "" }) { return React.createElement("section", { className: `panel ${className}` }, React.createElement("div", { className: "eyebrow" }, eyebrow), React.createElement("h2", null, title), children); }

function App() {
  const [manualState, setManualState] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [exported, setExported] = useState(null);
  async function createManual() { setBusy(true); setError(""); try { setManualState(await request("/v1/builds/manual", { method: "POST", body: JSON.stringify(manual) })); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  async function propose() {
    setBusy(true); setError("");
    const plan = { section_id: "process-control", diagram_id: "diagram-control", changed_sections: ["process-control"], changed_diagrams: ["diagram-control"], reason: "Add release verification before approval", body_blocks: [{ type: "step", step_id: "step_1", text: "Receive work order." }, { type: "step", step_id: "step_2", text: "Inspect incoming material." }, { type: "step", step_id: "step_3", text: "Verify release checks." }, { type: "step", step_id: "step_4", text: "Release approved batch." }], diagram_source: updatedMermaid };
    try { setProposal(await request(`/v1/manuals/${manual.manual_id}/chat`, { method: "POST", body: JSON.stringify({ change_plan: plan }) })); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function decide(decision) { setBusy(true); setError(""); try { const result = await request(`/v1/proposals/${proposal.proposal_id}/decision`, { method: "POST", body: JSON.stringify({ decision, approver: "quality-manager-ui" }) }); setProposal({ ...proposal, state: result.state, decision: result }); if (result.applied) setManualState({ ...manualState, revision: result.revision, status: "review-ready", content_hash: result.content_hash }); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  async function exportManual(format) { setBusy(true); setError(""); try { setExported(await request(`/v1/manuals/${manual.manual_id}/export`, { method: "POST", body: JSON.stringify({ proposal_id: proposal.proposal_id, format }) })); } catch (e) { setError(e.message); } finally { setBusy(false); } }
  const state = proposal?.state || manualState?.status || "not started";
  const header = React.createElement("header", { className: "topbar" },
    React.createElement("div", { className: "mark" }, "QM"),
    React.createElement("div", null, React.createElement("div", { className: "eyebrow" }, "QUALITY SYSTEMS"), React.createElement("h1", null, "Manual Review")),
    React.createElement("div", { className: "actions" }, React.createElement(Badge, { tone: state === "approved" ? "good" : state === "blocked" || state === "rejected" ? "bad" : "neutral" }, state), React.createElement("button", { className: "primary", onClick: createManual, disabled: busy }, busy ? "Working..." : "Open fixture")));
  const metadata = React.createElement(Panel, { eyebrow: "01 / MANUAL", title: "Revision record", className: "metadata" },
    React.createElement("div", { className: "facts" }, [["Manual", manual.manual_id], ["Organization", manual.organization], ["Revision", manualState.revision], ["Effective", manual.effective_date], ["Status", manualState.status || "review-ready"]].map(([key, value]) => React.createElement("div", { className: "fact", key }, React.createElement("span", null, key), React.createElement("strong", null, value)))),
    React.createElement("code", { className: "hash" }, manualState.content_hash));
  const before = React.createElement("div", null, React.createElement("label", null, "Before / prose"), React.createElement("ol", null, manual.sections[0].body_blocks.map(block => React.createElement("li", { key: block.step_id }, React.createElement("b", null, block.step_id), " ", block.text))));
  const after = proposal && React.createElement("div", { className: "after" }, React.createElement("label", null, "After / prose"), React.createElement("ol", null, proposal.proposed.sections[0].body_blocks.map(block => React.createElement("li", { key: block.step_id }, React.createElement("b", null, block.step_id), " ", block.text))));
  const proposalPanel = React.createElement(Panel, { eyebrow: "02 / PROPOSAL", title: "Paired process change", className: "proposal" },
    React.createElement("p", null, "One declared scope: ", React.createElement("strong", null, "Process Control"), " + ", React.createElement("strong", null, "diagram-control")),
    !proposal && React.createElement("button", { className: "primary wide", onClick: propose, disabled: busy }, "Propose step 3 update"),
    proposal && React.createElement("div", { className: "proposal-body" }, React.createElement("div", { className: "columns" }, before, after), React.createElement("label", null, "Canonical Mermaid source after proposal"), React.createElement("pre", null, updatedMermaid)));
  const consistency = React.createElement(Panel, { eyebrow: "03 / CONSISTENCY", title: "Prose and diagram contract", className: "consistency" }, proposal ? React.createElement("div", { className: proposal.state === "blocked" ? "status bad" : "status good" }, proposal.state === "blocked" ? "! Proposal blocked" : "✓ Same stable step IDs in both representations", React.createElement("p", null, proposal.refusal || "Every diagram edge resolves to a declared node.")) : React.createElement("p", { className: "muted" }, "Submit a proposal to run deterministic node, edge, scope, and step-ID checks."));
  const decision = proposal ? React.createElement(React.Fragment, null, React.createElement("div", { className: "decision-line" }, React.createElement("span", null, "Proposal decision"), React.createElement(Badge, { tone: proposal.state === "approved" ? "good" : proposal.state === "rejected" ? "bad" : "neutral" }, proposal.state)), proposal.state === "awaiting_review" && React.createElement("div", { className: "buttons" }, React.createElement("button", { onClick: () => decide("approved"), disabled: busy }, "Approve and create revision"), React.createElement("button", { className: "quiet", onClick: () => decide("rejected"), disabled: busy }, "Reject")), React.createElement("div", { className: "export" }, React.createElement("span", null, "Export revision"), React.createElement("button", { onClick: () => exportManual("docx"), disabled: busy || proposal.state !== "approved" }, "DOCX"), React.createElement("button", { onClick: () => exportManual("pdf"), disabled: busy || proposal.state !== "approved" }, "PDF")), exported && React.createElement("p", { className: "certificate" }, "Exported with disclaimer: ", exported.disclaimer)) : React.createElement("p", { className: "muted" }, "No proposal is ready for review.");
  return React.createElement("main", null, header, error && React.createElement("div", { className: "alert" }, React.createElement("strong", null, "Action refused: "), error), !manualState && React.createElement("div", { className: "empty" }, React.createElement("div", { className: "number" }, "02"), React.createElement("h2", null, "Open the quality manual"), React.createElement("p", null, "Review a paired process update and see why the prose and Mermaid diagram must move together.")), manualState && React.createElement("div", { className: "grid" }, metadata, proposalPanel, consistency, React.createElement(Panel, { eyebrow: "04 / DECISION", title: "Review and export", className: "decision" }, decision)));
}
ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
