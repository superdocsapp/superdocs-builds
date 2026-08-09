const html = htm.bind(React.createElement);
const { useState, useCallback, useMemo } = React;

const SESSION_ID = "triage-" + Math.random().toString(36).slice(2, 10);
const CLASSIFICATION_COLORS = { substantive: "#c2410c", stylistic: "#1d4ed8", typo: "#15803d" };

function Badge({ children, color }) {
  return html`<span class="badge" style=${{ background: color || "#666" }}>${children}</span>`;
}

function SettingsBar({ onError }) {
  const [key, setKey] = useState(SuperDocsClient.getApiKey());
  const [saved, setSaved] = useState(Boolean(SuperDocsClient.getApiKey()));

  const save = () => {
    try {
      SuperDocsClient.setApiKey(key);
      setSaved(true);
    } catch (e) {
      onError(e.message);
    }
  };

  return html`
    <details class="settings" open=${!saved}>
      <summary>SuperDocs API key ${saved ? "(saved)" : "(required)"}</summary>
      <input type="password" placeholder="sk_..." value=${key} onInput=${(e) => setKey(e.target.value)} />
      <button onClick=${save}>Save key</button>
      <p class="muted">
        Stored only in this browser's localStorage, never sent anywhere but api.superdocs.app.
        Get one at use.superdocs.app -> gear icon -> API Keys.
      </p>
    </details>
  `;
}

function orDefault(value, fallback) {
  return value === null || value === undefined ? fallback : value;
}

function UsageBadge({ usage }) {
  if (!usage) return null;
  return html`
    <div class="usage">
      SuperDocs ops this session: ${orDefault(usage.monthly_used, "?")} / ${orDefault(usage.monthly_limit, "?")}
      ${usage.was_billable === false ? html`<span class="muted"> (last call was free)</span>` : null}
    </div>
  `;
}

function ChangeRow({ change, classification }) {
  const cls = classification && classification.classification;
  return html`
    <li class="change-row">
      <div class="change-meta">
        <span class="reviewer">${change.author}</span>
        <span class="wordtype">${change.wordType}</span>
        ${change.section && html`<span class="section muted">${change.section}</span>`}
        ${cls && html`<${Badge} color=${CLASSIFICATION_COLORS[cls]}>${cls}<//>`}
      </div>
      <div class="change-text">
        ${change.wordType === "Replaced"
          ? html`<s>${change.previousText}</s> → <b>${change.text}</b>`
          : change.text}
      </div>
      ${classification && html`<div class="muted reason">${classification.reason}</div>`}
    </li>
  `;
}

function PreviewBatch({ matches, changesById, onApply, onDiscard, busy }) {
  const [decisions, setDecisions] = useState(() => Object.fromEntries(matches.map((m) => [m.id, true])));
  if (matches.length === 0) return null;

  const toggle = (id) => setDecisions((d) => ({ ...d, [id]: !d[id] }));
  const apply = () => {
    const approved = matches.filter((m) => decisions[m.id]);
    onApply(approved);
  };

  return html`
    <div class="preview-batch">
      <h4>Proposed batch (${matches.length}) — nothing has been applied yet</h4>
      <ul>
        ${matches.map((m) => {
          const change = changesById[m.id];
          return html`
            <li key=${m.id}>
              <label>
                <input type="checkbox" checked=${decisions[m.id]} onChange=${() => toggle(m.id)} />
                <b>${m.action}</b> — ${change ? change.author : "unknown"}:
                ${change ? (change.wordType === "Replaced" ? `${change.previousText} -> ${change.text}` : change.text) : m.id}
              </label>
              <div class="muted reason">${m.reason}</div>
            </li>
          `;
        })}
      </ul>
      <div class="actions">
        <button class="approve" disabled=${busy} onClick=${apply}>✓ Apply selected</button>
        <button class="reject" disabled=${busy} onClick=${onDiscard}>✗ Discard batch</button>
      </div>
    </div>
  `;
}

function CommentCard({ comment, onDraftReply, onPostReply, onResolve, busy }) {
  const [draft, setDraft] = useState("");

  return html`
    <li class="comment-card">
      <div class="comment-head">
        <b>${comment.authorName}</b>
        <span class="muted">${comment.creationDate ? new Date(comment.creationDate).toLocaleString() : ""}</span>
        ${comment.resolved && html`<${Badge} color="#15803d">resolved<//>`}
      </div>
      <div class="comment-content">${comment.content}</div>
      ${comment.replies.map(
        (r, i) => html`<div key=${i} class="comment-reply muted">↳ ${r.authorName}: ${r.content}</div>`
      )}
      <textarea rows="2" placeholder="Type a reply, or draft one with AI…" value=${draft} onInput=${(e) => setDraft(e.target.value)}></textarea>
      <div class="actions">
        <button disabled=${busy} onClick=${async () => setDraft(await onDraftReply(comment))}>✨ Draft AI reply</button>
        <button disabled=${busy || !draft.trim()} onClick=${() => onPostReply(comment.id, draft)}>Post reply</button>
        <button disabled=${busy} onClick=${() => onResolve(comment.id, !comment.resolved)}>
          ${comment.resolved ? "Reopen" : "Mark resolved"}
        </button>
      </div>
    </li>
  `;
}

function App() {
  const [changes, setChanges] = useState([]);
  const [classifications, setClassifications] = useState({});
  const [comments, setComments] = useState([]);
  const [instruction, setInstruction] = useState("");
  const [previewMatches, setPreviewMatches] = useState([]);
  const [reviewerFilter, setReviewerFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [usage, setUsage] = useState(null);
  const [tab, setTab] = useState("changes");

  const withBusy = (fn) => async (...args) => {
    setBusy(true);
    setError("");
    try {
      return await fn(...args);
    } catch (e) {
      setError(e.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };

  const loadChanges = withBusy(async () => {
    const loaded = await WordChanges.loadTrackedChanges();
    setChanges(loaded);
    setClassifications({});
    setPreviewMatches([]);
  });

  const loadComments = withBusy(async () => {
    setComments(await WordChanges.loadComments());
  });

  const classifyAll = withBusy(async () => {
    if (changes.length === 0) {
      setError("Load tracked changes first.");
      return;
    }
    if (changes.length > 60) {
      setError(`${changes.length} changes is a lot for one classification call — load a smaller selection or classify in batches (kept intentionally capped to control operations cost).`);
      return;
    }
    const { byId, usage: u } = await SuperDocsClient.classifyChanges(changes, SESSION_ID);
    setClassifications(byId);
    if (u) setUsage(u);
  });

  const runInstruction = withBusy(async () => {
    if (!instruction.trim()) return;
    const result = await SuperDocsClient.interpretInstruction(instruction, changes, classifications, SESSION_ID);
    if (result.usage) setUsage(result.usage);
    if (!result.matches || result.matches.length === 0) {
      setError(result.unmatched_note || "No changes matched that instruction.");
      setPreviewMatches([]);
      return;
    }
    setPreviewMatches(result.matches);
  });

  const applyBatch = withBusy(async (approved) => {
    await WordChanges.applyDecisions(
      approved.map((m) => ({ id: m.id, memberIds: (changesById[m.id] || {}).memberIds, action: m.action }))
    );
    setPreviewMatches([]);
    await loadChanges();
  });

  const draftReply = withBusy(async (comment) => {
    const { text, usage: u } = await SuperDocsClient.draftCommentReply(comment, SESSION_ID);
    if (u) setUsage(u);
    return text;
  });

  const postReply = withBusy(async (commentId, text) => {
    await WordChanges.replyToComment(commentId, text);
    await loadComments();
  });

  const toggleResolve = withBusy(async (commentId, resolved) => {
    await WordChanges.resolveComment(commentId, resolved);
    await loadComments();
  });

  const changesById = useMemo(() => Object.fromEntries(changes.map((c) => [c.id, c])), [changes]);
  const reviewers = useMemo(() => [...new Set(changes.map((c) => c.author))], [changes]);

  const filteredChanges = changes.filter((c) => {
    if (reviewerFilter && c.author !== reviewerFilter) return false;
    if (kindFilter) {
      const cls = classifications[c.id];
      if (!cls || cls.classification !== kindFilter) return false;
    }
    return true;
  });

  return html`
    <div class="app">
      <h1>Track-Changes Triage</h1>
      <${SettingsBar} onError=${setError} />
      ${error && html`<div class="error-banner" onClick=${() => setError("")}>${error} <span class="dismiss">(dismiss)</span></div>`}
      <${UsageBadge} usage=${usage} />

      <div class="tabs">
        <button class=${tab === "changes" ? "active" : ""} onClick=${() => setTab("changes")}>Tracked changes (${changes.length})</button>
        <button class=${tab === "comments" ? "active" : ""} onClick=${() => setTab("comments")}>Comments (${comments.length})</button>
      </div>

      ${tab === "changes" && html`
        <div>
          <div class="toolbar">
            <button disabled=${busy} onClick=${loadChanges}>↻ Load tracked changes</button>
            <button disabled=${busy} onClick=${classifyAll}>✨ Classify all (substantive/stylistic/typo)</button>
          </div>

          <div class="filters">
            <select value=${reviewerFilter} onChange=${(e) => setReviewerFilter(e.target.value)}>
              <option value="">All reviewers</option>
              ${reviewers.map((r) => html`<option key=${r} value=${r}>${r}</option>`)}
            </select>
            <select value=${kindFilter} onChange=${(e) => setKindFilter(e.target.value)}>
              <option value="">All kinds</option>
              <option value="substantive">Substantive</option>
              <option value="stylistic">Stylistic</option>
              <option value="typo">Typo</option>
            </select>
          </div>

          <div class="instruction-bar">
            <input
              placeholder="e.g. accept all of the proofreader's typo fixes"
              value=${instruction}
              onInput=${(e) => setInstruction(e.target.value)}
            />
            <button disabled=${busy || !instruction.trim()} onClick=${runInstruction}>Interpret</button>
          </div>

          <${PreviewBatch}
            matches=${previewMatches}
            changesById=${changesById}
            busy=${busy}
            onApply=${applyBatch}
            onDiscard=${() => setPreviewMatches([])}
          />

          <ul class="changes-list">
            ${filteredChanges.map(
              (c) => html`<${ChangeRow} key=${c.id} change=${c} classification=${classifications[c.id]} />`
            )}
          </ul>
          ${changes.length === 0 && html`<p class="muted">No tracked changes loaded yet.</p>`}
        </div>
      `}

      ${tab === "comments" && html`
        <div>
          <div class="toolbar">
            <button disabled=${busy} onClick=${loadComments}>↻ Load comments</button>
          </div>
          <ul class="comments-list">
            ${comments.map(
              (c) => html`<${CommentCard} key=${c.id} comment=${c} busy=${busy}
                onDraftReply=${draftReply} onPostReply=${postReply} onResolve=${toggleResolve} />`
            )}
          </ul>
          ${comments.length === 0 && html`<p class="muted">No comments loaded yet.</p>`}
        </div>
      `}
    </div>
  `;
}

Office.onReady((info) => {
  if (info.host !== Office.HostType.Word) {
    document.getElementById("root").textContent = "This add-in only runs in Microsoft Word.";
    return;
  }
  ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
});
