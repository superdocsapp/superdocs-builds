/**
 * Thin SuperDocs API client for the triage pane.
 *
 * Deliberate design choice (see README "Architecture" section): this add-in
 * never round-trips the document itself through SuperDocs' upload/edit/export
 * pipeline for the triage feature. The brief's own honesty note says
 * multi-reviewer attribution doesn't survive that round-trip today, so the
 * actual document mutation (accepting/rejecting a tracked change, replying to
 * a comment) happens entirely through Word's native Office.js API in
 * word-changes.js. SuperDocs is used for exactly the part it's good at:
 * reasoning over text. Every call here is a plain `/v1/chat` request with no
 * `document_html` and no `approval_mode` -- confirmed live against the real
 * API (not just the docs) that this kind of analysis-only call is not
 * billed (`was_billable: false, ops_charged: 0`), which is what "budget your
 * operations" should look like when the task doesn't need document mutation
 * at all.
 *
 * Verified bug, reported separately (see README "What broke"): sync
 * POST /v1/chat with approval_mode="ask_every_time" returns
 * document_changes.pending_changes[].change_id, but
 * POST /v1/chat/{session_id}/approve requires a job_id that never appears in
 * that response -- only POST /v1/chat/async's job_id actually works with
 * approve. This add-in does not depend on that path, but it's why we don't
 * use approval_mode here even for the optional summary-memo feature.
 */
const SuperDocsClient = (() => {
  const BASE_URL = "https://api.superdocs.app";

  function getApiKey() {
    return window.localStorage.getItem("superdocs_api_key") || "";
  }

  function setApiKey(key) {
    window.localStorage.setItem("superdocs_api_key", key.trim());
  }

  async function chat({ message, sessionId }) {
    const apiKey = getApiKey();
    if (!apiKey) throw new Error("Set your SuperDocs API key first (gear icon).");
    const resp = await fetch(`${BASE_URL}/v1/chat`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
      throw new Error(`SuperDocs ${resp.status}: ${detail || resp.statusText}`);
    }
    return data; // { response, session_id, document_changes, usage, hint }
  }

  /** The model is asked for JSON-only output but real models sometimes wrap
   * it in ```json fences despite instructions -- strip those defensively
   * rather than letting JSON.parse throw on a perfectly good answer. */
  function extractJson(text) {
    const trimmed = text.trim();
    const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
    const candidate = fenced ? fenced[1] : trimmed;
    return JSON.parse(candidate);
  }

  function formatChangeDigest(changes) {
    return changes
      .map((c) => {
        const section = c.section ? ` section="${c.section}"` : "";
        const textPart =
          c.wordType === "Replaced"
            ? `changed ${JSON.stringify(c.previousText)} -> ${JSON.stringify(c.text)}`
            : c.wordType === "Deleted"
            ? `deleted ${JSON.stringify(c.text)}`
            : c.wordType === "Formatted"
            ? `reformatted ${JSON.stringify(c.text)}`
            : `inserted ${JSON.stringify(c.text)}`;
        return `- id=${c.id} reviewer="${c.author}" type=${c.wordType}${section} ${textPart}`;
      })
      .join("\n");
  }

  /** One batched call classifies every change at once -- not one call per
   * change -- to keep this within a small, predictable operations budget. */
  async function classifyChanges(changes, sessionId) {
    if (changes.length === 0) return {};
    const digest = formatChangeDigest(changes);
    const message =
      `You are analyzing a list of tracked changes from a Word document review. ` +
      `You are NOT editing a document -- only classifying text already decided by human reviewers.\n\n` +
      `Changes:\n${digest}\n\n` +
      `Classify each change as exactly one of: substantive, stylistic, typo.\n` +
      `"typo" = spelling/punctuation/whitespace fixes with no meaning change.\n` +
      `"stylistic" = wording/tone/formatting changes that don't alter obligations, rights, dates, or amounts.\n` +
      `"substantive" = changes that alter an obligation, right, date, amount, party, or condition.\n` +
      `Respond with ONLY a JSON array, no prose, no markdown fences: ` +
      `[{"id": "...", "classification": "substantive|stylistic|typo", "reason": "one short sentence"}]`;
    const result = await chat({ message, sessionId });
    const parsed = extractJson(result.response);
    const byId = {};
    for (const entry of parsed) byId[entry.id] = entry;
    return { byId, usage: result.usage };
  }

  /** Turns a free-text instruction ("accept all of the proofreader's typo
   * fixes") into a concrete list of {id, action} the UI can preview before
   * anything is touched in the document. */
  async function interpretInstruction(instruction, changes, classifications, sessionId) {
    const digest = changes
      .map((c) => {
        const cls = classifications[c.id];
        return `- id=${c.id} reviewer="${c.author}" type=${c.wordType} classification=${
          cls ? cls.classification : "unclassified"
        }${c.section ? ` section="${c.section}"` : ""} text=${JSON.stringify(c.text)}`;
      })
      .join("\n");
    const message =
      `You are matching a reviewer's instruction against a list of tracked changes from a Word document. ` +
      `You are NOT editing anything -- only deciding which listed changes the instruction refers to, and whether ` +
      `it means to accept or reject each one.\n\n` +
      `Changes:\n${digest}\n\n` +
      `Instruction: "${instruction}"\n\n` +
      `Respond with ONLY a JSON object, no prose, no markdown fences: ` +
      `{"matches": [{"id": "...", "action": "accept|reject", "reason": "one short sentence"}], ` +
      `"unmatched_note": "empty string, or a short note if nothing matched"}`;
    const result = await chat({ message, sessionId });
    const parsed = extractJson(result.response);
    return { ...parsed, usage: result.usage };
  }

  async function draftCommentReply(comment, sessionId) {
    const replies = (comment.replies || [])
      .map((r) => `  - ${r.authorName}: ${r.content}`)
      .join("\n");
    const message =
      `Draft a short, professional reply (2-3 sentences max) to this Word document comment thread, ` +
      `on behalf of the person resolving it. Do not use placeholders like [Name].\n\n` +
      `Comment by ${comment.authorName}: "${comment.content}"\n` +
      (replies ? `Existing replies:\n${replies}\n\n` : "\n") +
      `Respond with ONLY the reply text, no quotes, no markdown, no prose about your reasoning.`;
    const result = await chat({ message, sessionId });
    return { text: result.response.trim(), usage: result.usage };
  }

  return { getApiKey, setApiKey, chat, classifyChanges, interpretInstruction, draftCommentReply };
})();
