import { useEffect, useState } from "react";
import "./App.css";

async function apiFetch(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      if (body?.detail) detail = `: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`;
    } catch {
      // response wasn't JSON — the status text alone is still useful
    }
    throw new Error(`${res.status} ${res.statusText}${detail}`);
  }
  return res.json();
}

function ErrorBanner({ message }) {
  return <div className="error-banner">⚠ {message}</div>;
}

// pending_changes carries old_html/new_html as real HTML fragments (a
// <p data-chunk-id="..."> wrapper, sometimes a <mark> for the disagreement
// note) — strip tags down to plain text so the diff-chip pattern shows a
// clean "old value → new value" the same way Task 1's frontend did for
// its own (already-plain-string) conflict diffs.
function htmlToText(html) {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  return (doc.body.textContent || "").trim();
}

function ChangeCard({ change, decision, onDecide }) {
  const oldText = htmlToText(change.old_html);
  const newText = htmlToText(change.new_html);
  const decided = decision !== undefined;
  return (
    <li className={`review-item ${decided ? "decided " + (decision ? "approved" : "rejected") : "pending"}`}>
      <div className="review-item-head">
        <span className="item-type-badge">clause</span>
        <span className="chunk-code">{change.chunk_id?.slice(0, 8)}</span>
        {decided && (
          <span className={`outcome-badge ${decision ? "approved" : "rejected"}`}>
            {decision ? "will approve" : "will reject"}
          </span>
        )}
      </div>
      <div className="conflict-diff">
        <div className="conflict-diff-row">
          <span className="diff-chip diff-old">{oldText || "(none)"}</span>
          <span className="diff-arrow">→</span>
          <span className="diff-chip diff-new">{newText || "(none)"}</span>
        </div>
      </div>
      {change.ai_explanation && <p className="review-item-source">{change.ai_explanation}</p>}
      <div className="review-item-actions">
        <button
          className={`approve${decision === true ? " active" : ""}`}
          onClick={() => onDecide(change.chunk_id, true)}
        >
          Approve
        </button>
        <button
          className={`reject${decision === false ? " active" : ""}`}
          onClick={() => onDecide(change.chunk_id, false)}
        >
          Reject
        </button>
      </div>
    </li>
  );
}

const STATUS_LABELS = {
  open: "Open",
  approved: "Approved",
  rejected: "Rejected",
  reopened: "Reopened",
};

function TrackerItem({ item }) {
  return (
    <li className={`tracker-item status-${item.status}`}>
      <div className="review-item-head">
        <span className={`status-badge ${item.status}`}>{STATUS_LABELS[item.status] || item.status}</span>
        {item.status === "reopened" && <span className="reopened-flag">↻ needs re-review</span>}
      </div>
      <div className="review-item-summary">
        Clause <code className="chunk-code">{item.chunk_id?.slice(0, 8)}</code>
        {item.raised_by && item.raised_by !== "unknown" && <> — raised by {item.raised_by}</>}
      </div>
    </li>
  );
}

export default function App() {
  const [negotiations, setNegotiations] = useState([]);
  const [selectedNegotiationId, setSelectedNegotiationId] = useState(null);
  const [activeTab, setActiveTab] = useState("negotiations");

  // create-negotiation form
  const [formName, setFormName] = useState("");
  const [cbaFile, setCbaFile] = useState(null);
  const [unionFile, setUnionFile] = useState(null);
  const [employerFile, setEmployerFile] = useState(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  // round tab
  const [round, setRound] = useState(null);
  const [roundStarting, setRoundStarting] = useState(false);
  const [roundError, setRoundError] = useState(null);
  const [pendingChanges, setPendingChanges] = useState(null); // null = not fetched yet
  const [changesLoading, setChangesLoading] = useState(false);
  const [decisions, setDecisions] = useState({}); // chunk_id -> bool
  const [submittingDecisions, setSubmittingDecisions] = useState(false);
  const [decisionsError, setDecisionsError] = useState(null);
  const [decisionsSubmitted, setDecisionsSubmitted] = useState(false);

  // tracker tab
  const [openItems, setOpenItems] = useState([]);
  const [trackerLoading, setTrackerLoading] = useState(false);
  const [trackerError, setTrackerError] = useState(null);

  // export
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);

  const selectedNegotiation = negotiations.find((n) => n.id === selectedNegotiationId) || null;

  function resetRoundState() {
    setRound(null);
    setRoundError(null);
    setPendingChanges(null);
    setDecisions({});
    setDecisionsError(null);
    setDecisionsSubmitted(false);
  }

  async function handleCreateNegotiation(e) {
    e.preventDefault();
    if (!formName || !cbaFile || !unionFile || !employerFile) return;
    setCreating(true);
    setCreateError(null);
    try {
      const fd = new FormData();
      fd.append("name", formName);
      fd.append("cba", cbaFile);
      fd.append("union_position", unionFile);
      fd.append("employer_position", employerFile);
      const res = await fetch("/negotiations", { method: "POST", body: fd });
      if (!res.ok) {
        let detail = "";
        try {
          const body = await res.json();
          if (body?.detail) detail = `: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`;
        } catch {
          // ignore — not JSON
        }
        throw new Error(`${res.status} ${res.statusText}${detail}`);
      }
      const negotiation = await res.json();
      setNegotiations((prev) => [negotiation, ...prev]);
      setSelectedNegotiationId(negotiation.id);
      setFormName("");
      setCbaFile(null);
      setUnionFile(null);
      setEmployerFile(null);
      resetRoundState();
      setActiveTab("round");
    } catch (err) {
      setCreateError(err.message);
    } finally {
      setCreating(false);
    }
  }

  async function startRound() {
    if (!selectedNegotiationId) return;
    setRoundStarting(true);
    setRoundError(null);
    setPendingChanges(null);
    setDecisions({});
    setDecisionsError(null);
    setDecisionsSubmitted(false);
    try {
      // the backend polls server-side until the round resolves (see
      // round_service.start_round) — this fetch just waits for that,
      // no client-side polling needed
      const started = await apiFetch(`/negotiations/${selectedNegotiationId}/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setRound(started);
      if (started.status === "awaiting_approval") {
        setChangesLoading(true);
        try {
          const resp = await apiFetch(`/rounds/${started.round_id}/pending-changes`);
          setPendingChanges(resp.pending_changes || []);
        } catch (err) {
          setRoundError(err.message);
        } finally {
          setChangesLoading(false);
        }
      } else {
        // completed with nothing to review, or failed — either way there's
        // no pending_changes call to make
        setPendingChanges([]);
      }
    } catch (err) {
      setRoundError(err.message);
    } finally {
      setRoundStarting(false);
    }
  }

  function setDecision(chunkId, approved) {
    setDecisions((prev) => ({ ...prev, [chunkId]: approved }));
  }

  async function submitDecisions() {
    if (!round) return;
    setSubmittingDecisions(true);
    setDecisionsError(null);
    try {
      const body = Object.entries(decisions).map(([chunk_id, approved]) => ({ chunk_id, approved }));
      const result = await apiFetch(`/rounds/${round.round_id}/decisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setRound(result);
      setPendingChanges([]);
      setDecisions({});
      setDecisionsSubmitted(true);
    } catch (err) {
      setDecisionsError(err.message);
    } finally {
      setSubmittingDecisions(false);
    }
  }

  async function loadOpenItems(negotiationId) {
    setTrackerLoading(true);
    setTrackerError(null);
    try {
      const items = await apiFetch(`/negotiations/${negotiationId}/open-items`);
      // REOPENED items float to the top — the property this card is
      // graded on shouldn't require scrolling to notice
      setOpenItems([...items].sort((a, b) => (a.status === "reopened" ? -1 : 0) - (b.status === "reopened" ? -1 : 0)));
    } catch (err) {
      setTrackerError(err.message);
    } finally {
      setTrackerLoading(false);
    }
  }

  async function handleExport(format) {
    if (!selectedNegotiationId) return;
    setExporting(true);
    setExportError(null);
    try {
      const res = await fetch(`/negotiations/${selectedNegotiationId}/export?format=${format}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedNegotiation?.name || "agreement"}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    if (!selectedNegotiationId) return;
    if (activeTab === "tracker") loadOpenItems(selectedNegotiationId);
  }, [selectedNegotiationId, activeTab]);

  const decidedCount = Object.keys(decisions).length;
  const totalChanges = pendingChanges?.length || 0;
  // "nothing to review" is specifically the completed-with-no-changes
  // case Phase 3's live test found — distinct from "completed because the
  // user just finished deciding everything" (decisionsSubmitted), which
  // hits the same completed+empty-pendingChanges shape but means something
  // different. A failed round gets its own banner below, not this message.
  const nothingToReview = round && round.status === "completed" && pendingChanges?.length === 0 && !decisionsSubmitted;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Collective Agreement Redliner</h1>
        <p className="subtitle">Redline a CBA against union and employer positions, round by round.</p>
      </header>

      <div className="layout">
        <main className="run-detail" style={{ padding: "24px 32px", flex: 1 }}>
          <nav className="tabs">
            <button
              className={activeTab === "negotiations" ? "active" : ""}
              onClick={() => setActiveTab("negotiations")}
            >
              Negotiations
            </button>
            <button
              className={activeTab === "round" ? "active" : ""}
              onClick={() => setActiveTab("round")}
              disabled={!selectedNegotiationId}
            >
              Round
            </button>
            <button
              className={activeTab === "tracker" ? "active" : ""}
              onClick={() => setActiveTab("tracker")}
              disabled={!selectedNegotiationId}
            >
              Open Items
            </button>
          </nav>

          {activeTab === "negotiations" && (
            <div className="negotiations-view">
              <form className="negotiation-form" onSubmit={handleCreateNegotiation}>
                <h3>Start a new negotiation</h3>
                {createError && <ErrorBanner message={createError} />}
                <div className="form-row">
                  <label htmlFor="neg-name">Name</label>
                  <input
                    id="neg-name"
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Northfield Manufacturing — Local 214"
                  />
                </div>
                <div className="form-row">
                  <label htmlFor="neg-cba">CBA draft</label>
                  <input id="neg-cba" type="file" onChange={(e) => setCbaFile(e.target.files?.[0] || null)} />
                </div>
                <div className="form-row">
                  <label htmlFor="neg-union">Union position</label>
                  <input id="neg-union" type="file" onChange={(e) => setUnionFile(e.target.files?.[0] || null)} />
                </div>
                <div className="form-row">
                  <label htmlFor="neg-employer">Employer position</label>
                  <input
                    id="neg-employer"
                    type="file"
                    onChange={(e) => setEmployerFile(e.target.files?.[0] || null)}
                  />
                </div>
                <button
                  className="form-submit"
                  type="submit"
                  disabled={creating || !formName || !cbaFile || !unionFile || !employerFile}
                >
                  {creating ? "Starting…" : "Start negotiation"}
                </button>
              </form>

              <h3 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-tertiary)" }}>
                This session's negotiations
              </h3>
              {negotiations.length === 0 && (
                <p className="muted">None yet — start one above to begin a round.</p>
              )}
              <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                {negotiations.map((n) => (
                  <li
                    key={n.id}
                    className={`run-row${n.id === selectedNegotiationId ? " selected" : ""}`}
                    onClick={() => {
                      setSelectedNegotiationId(n.id);
                      resetRoundState();
                      setActiveTab("round");
                    }}
                  >
                    <div className="run-row-top">
                      <span className="run-trigger">{n.name}</span>
                    </div>
                    <div className="run-id">{n.id}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeTab === "round" && (
            <div className="round-view">
              {!selectedNegotiation && <div className="empty-state">Pick or start a negotiation first.</div>}

              {selectedNegotiation && (
                <>
                  <div className="round-status-line">
                    <span className="muted">Working on: {selectedNegotiation.name}</span>
                  </div>

                  {roundError && <ErrorBanner message={roundError} />}

                  {!round && (
                    <button className="form-submit" onClick={startRound} disabled={roundStarting}>
                      {roundStarting ? "Starting round…" : "Start a round"}
                    </button>
                  )}
                  {roundStarting && (
                    <p className="muted loading" style={{ marginTop: 12 }}>
                      Waiting for SuperDocs to propose redlines — this can take up to a minute…
                    </p>
                  )}

                  {round && changesLoading && <p className="muted loading">Loading pending changes…</p>}

                  {round && !changesLoading && nothingToReview && (
                    <div className="empty-state">
                      Nothing needed review this round — the round {round.status === "completed" ? "completed" : "ended"} with no pending changes.
                      <div style={{ marginTop: 16 }}>
                        <button className="form-submit" onClick={startRound} disabled={roundStarting}>
                          Start another round
                        </button>
                      </div>
                    </div>
                  )}

                  {round && round.status === "failed" && (
                    <ErrorBanner message="This round failed on SuperDocs' side — try starting another." />
                  )}

                  {round && pendingChanges && pendingChanges.length > 0 && (
                    <div className="review-queue">
                      <section>
                        <h3>
                          Pending changes <span className="count-badge">{pendingChanges.length}</span>
                        </h3>
                        {decisionsError && <ErrorBanner message={decisionsError} />}
                        <ul className="item-list">
                          {pendingChanges.map((change) => (
                            <ChangeCard
                              key={change.chunk_id}
                              change={change}
                              decision={decisions[change.chunk_id]}
                              onDecide={setDecision}
                            />
                          ))}
                        </ul>
                        <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 12 }}>
                          <button
                            className="form-submit"
                            disabled={decidedCount < totalChanges || submittingDecisions}
                            onClick={submitDecisions}
                          >
                            {submittingDecisions
                              ? "Submitting…"
                              : `Submit ${decidedCount}/${totalChanges} decisions`}
                          </button>
                          <span className="muted">
                            SuperDocs decides a round's changes as one batch — every item needs a decision before
                            submitting.
                          </span>
                        </div>
                      </section>
                    </div>
                  )}

                  {round && round.status === "completed" && decisionsSubmitted && !changesLoading && (
                    <div className="empty-state">
                      Round complete — check the Open Items tab for the current state.
                      <div style={{ marginTop: 16 }}>
                        <button className="form-submit" onClick={startRound} disabled={roundStarting}>
                          Start another round
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {activeTab === "tracker" && (
            <div className="tracker-view">
              {!selectedNegotiation && <div className="empty-state">Pick or start a negotiation first.</div>}

              {selectedNegotiation && (
                <>
                  <div className="tracker-header">
                    <h3>
                      Open Items <span className="count-badge">{openItems.length}</span>
                    </h3>
                    <button className="form-submit" onClick={() => handleExport("docx")} disabled={exporting}>
                      {exporting ? "Exporting…" : "Export agreement (.docx)"}
                    </button>
                  </div>
                  {exportError && <ErrorBanner message={exportError} />}
                  {trackerLoading && <p className="muted loading">Loading open items…</p>}
                  {trackerError && <ErrorBanner message={trackerError} />}
                  {!trackerLoading && !trackerError && openItems.length === 0 && (
                    <p className="muted">No open items yet — start a round to propose some redlines.</p>
                  )}
                  <ul className="item-list">
                    {openItems.map((item) => (
                      <TrackerItem key={item.chunk_id} item={item} />
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
