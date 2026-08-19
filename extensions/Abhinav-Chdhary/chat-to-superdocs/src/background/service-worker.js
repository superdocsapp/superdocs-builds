import { appendCapturedResponse, appendInstruction, conversationKey, createDocument, createInstruction, newSessionId } from "../shared/document.js";
import { BridgeClient, decisionsFromForm, finalHtml, jobState, pendingChanges } from "../shared/superdocs.js";

async function storedState() {
  return chrome.storage.local.get({ bridgeUrl: "http://127.0.0.1:8787", documents: {}, jobs: {} });
}

function documentTitle(url) {
  return `${new URL(url).hostname.replace(/^www\./, "")} chat`;
}

async function addResponse(message, sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const key = conversationKey(sender.tab.url);
  const state = await storedState();
  const existing = state.documents[key];
  const sessionId = existing?.sessionId ?? newSessionId();
  const documentHtml = existing
    ? appendCapturedResponse(existing.html, message.html)
    : createDocument({ templateId: message.templateId, title: documentTitle(sender.tab.url), capturedHtml: message.html });
  const bridge = new BridgeClient(state.bridgeUrl);
  const started = await bridge.startJob({
    session_id: sessionId,
    document_html: documentHtml,
    message: existing ? appendInstruction() : createInstruction(),
    approval_mode: "ask_every_time",
  });
  state.jobs[key] = { jobId: started.job_id, sessionId, documentHtml, templateId: existing?.templateId ?? message.templateId };
  await chrome.storage.local.set({ jobs: state.jobs });
  return { state: "processing", conversationKey: key };
}

async function pollConversation(sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const key = conversationKey(sender.tab.url);
  const state = await storedState();
  const active = state.jobs[key];
  if (!active) return { state: "idle", hasDocument: Boolean(state.documents[key]) };
  const job = await new BridgeClient(state.bridgeUrl).getJob(active.jobId);
  const stateName = jobState(job);
  if (stateName === "processing") return { state: "processing" };
  if (stateName === "review") return { state: "review", changes: pendingChanges(job) };
  if (stateName === "completed") {
    const html = finalHtml(job);
    if (!html) throw new Error("The completed job did not return document HTML.");
    state.documents[key] = { sessionId: active.sessionId, html, templateId: active.templateId };
    delete state.jobs[key];
    await chrome.storage.local.set({ documents: state.documents, jobs: state.jobs });
    return { state: "complete", templateId: active.templateId };
  }
  throw new Error(job.error || `The job ended with status: ${job.status}.`);
}

async function decide(message, sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const key = conversationKey(sender.tab.url);
  const state = await storedState();
  const active = state.jobs[key];
  if (!active) throw new Error("There is no pending review for this conversation.");
  await new BridgeClient(state.bridgeUrl).decide(active.sessionId, {
    job_id: active.jobId,
    approved: true,
    changes: decisionsFromForm(message.changes, new Set(message.approvedIds)),
  });
  return { state: "processing" };
}

async function exportConversation(sender) {
  if (!sender.tab?.url) throw new Error("This action must originate from an AI chat tab.");
  const state = await storedState();
  const document = state.documents[conversationKey(sender.tab.url)];
  if (!document) throw new Error("Add and approve an answer before exporting this conversation document.");
  const response = await new BridgeClient(state.bridgeUrl).exportDocument({ html: document.html, format: "docx", filename: "chat-to-superdocs.docx" });
  const objectUrl = URL.createObjectURL(await response.blob());
  await chrome.downloads.download({ url: objectUrl, filename: "chat-to-superdocs.docx", saveAs: true });
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  return { state: "exported" };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handlers = { ADD_RESPONSE: () => addResponse(message, sender), POLL_CONVERSATION: () => pollConversation(sender), DECIDE_CHANGES: () => decide(message, sender), EXPORT_CONVERSATION: () => exportConversation(sender) };
  if (!handlers[message?.type]) return;
  handlers[message.type]().then((result) => sendResponse({ ok: true, ...result })).catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : "Extension action failed." }));
  return true;
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
