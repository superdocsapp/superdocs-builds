import { appendCapturedResponse, appendInstruction, conversationKey, createDocument, createInstruction, newSessionId } from "../shared/document.js";
import { BridgeClient, decisionsFromForm, finalHtml, focusedSessionDocument, jobState, pendingChanges, savedDocumentExists } from "../shared/superdocs.js";

function log(event, details = {}) {
  console.info(`[Chat to SuperDocs] ${event}`, details);
}

async function storedState() {
  return chrome.storage.local.get({ bridgeUrl: "http://127.0.0.1:8787", documents: {}, jobs: {} });
}

function bridge(state) {
  return new BridgeClient(state.bridgeUrl, chrome.runtime.id);
}

async function addResponse(message, sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const key = conversationKey(sender.tab.url);
  const state = await storedState();
  const existing = state.documents[key];
  if (!existing && message.template && (typeof message.template.id !== "string" || typeof message.template.name !== "string")) throw new Error("The selected template is invalid.");
  if (!message.template && (!existing || existing.mode === "direct")) return saveDirectDocument({ key, existing, message, state });
  const sessionId = existing?.sessionId ?? newSessionId();
  const documentHtml = existing
    ? appendCapturedResponse(existing.html, message.html)
    : createDocument({ capturedHtml: message.html });
  const started = await bridge(state).startJob({
    session_id: sessionId,
    document_html: documentHtml,
    message: existing ? appendInstruction() : createInstruction(message.template),
    approval_mode: "approve_all",
  });
  state.jobs[key] = { jobId: started.job_id, sessionId, documentHtml, template: existing?.template ?? message.template, mode: "template" };
  await chrome.storage.local.set({ jobs: state.jobs });
  log("template job started", { conversationKey: key, sessionId, jobId: started.job_id, templateId: message.template?.id ?? existing?.template?.id ?? null, htmlBytes: documentHtml.length });
  return { state: "processing", conversationKey: key };
}

async function saveDirectDocument({ key, existing, message, state }) {
  const sessionId = existing?.sessionId ?? newSessionId();
  const html = existing ? appendCapturedResponse(existing.html, message.html) : createDocument({ capturedHtml: message.html });
  const client = bridge(state);
  let documentId = existing?.documentId;
  log("direct save started", { conversationKey: key, sessionId, existingDocumentId: documentId ?? null, htmlBytes: html.length });
  if (!documentId) {
    await client.openBlankDocument(sessionId);
    const opened = focusedSessionDocument(await client.listSessionDocuments(sessionId));
    if (!opened) throw new Error("SuperDocs did not return a blank document for this conversation.");
    documentId = opened.id;
    log("blank document opened", { conversationKey: key, sessionId, documentId });
  }
  await client.saveDocument(sessionId, documentId, html);
  const saved = focusedSessionDocument(await client.listSessionDocuments(sessionId));
  const durableDocumentId = saved?.durableId ?? existing?.durableDocumentId ?? null;
  const files = durableDocumentId ? await client.listDocuments() : null;
  const verified = durableDocumentId ? savedDocumentExists(files, durableDocumentId) : false;
  state.documents[key] = { mode: "direct", sessionId, documentId, durableDocumentId, html, template: null };
  await chrome.storage.local.set({ documents: state.documents });
  log("direct save completed", { conversationKey: key, sessionId, documentId, durableDocumentId, verified });
  return { state: "complete", mode: "direct", durableDocumentId, verified };
}

async function pollConversation(sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const key = conversationKey(sender.tab.url);
  const state = await storedState();
  const active = state.jobs[key];
  if (!active) return { state: "idle", hasDocument: Boolean(state.documents[key]) };
  const job = await bridge(state).getJob(active.jobId);
  const stateName = jobState(job);
  if (stateName === "processing") return { state: "processing" };
  if (stateName === "review") {
    const changes = pendingChanges(job);
    await bridge(state).decide(active.sessionId, {
      job_id: active.jobId,
      approved: true,
      changes: decisionsFromForm(changes, new Set(changes.map((change) => change.change_id))),
    });
    return { state: "processing" };
  }
  if (stateName === "completed") {
    const html = finalHtml(job);
    if (!html) throw new Error("The completed job did not return document HTML.");
    state.documents[key] = { mode: "template", sessionId: active.sessionId, html, template: active.template };
    delete state.jobs[key];
    await chrome.storage.local.set({ documents: state.documents, jobs: state.jobs });
    log("template job completed", { conversationKey: key, sessionId: active.sessionId, jobId: active.jobId, htmlBytes: html.length });
    return { state: "complete", template: active.template };
  }
  throw new Error(job.error || `The job ended with status: ${job.status}.`);
}

async function listTemplates() {
  const state = await storedState();
  return { templates: await bridge(state).listTemplates() };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handlers = { ADD_RESPONSE: () => addResponse(message, sender), LIST_TEMPLATES: () => listTemplates(), POLL_CONVERSATION: () => pollConversation(sender) };
  if (!handlers[message?.type]) return;
  handlers[message.type]().then((result) => sendResponse({ ok: true, ...result })).catch((error) => {
    log("extension action failed", { type: message.type, error: error instanceof Error ? error.message : "Extension action failed." });
    sendResponse({ ok: false, error: error instanceof Error ? error.message : "Extension action failed." });
  });
  return true;
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
