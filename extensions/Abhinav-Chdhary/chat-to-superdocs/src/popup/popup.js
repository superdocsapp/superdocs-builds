import { appendInstruction, createDocument, createInstruction, newSessionId } from "../shared/document.js";
import { BridgeClient, decisionsFromForm, finalHtml, jobState, pendingChanges } from "../shared/superdocs.js";

const $ = (selector) => document.querySelector(selector);
const state = { capture: null, job: null, activeDocument: null };

function setStatus(message) { $("#status").textContent = message; }
function client() { return new BridgeClient(state.bridgeUrl); }
function selectedMode() { return document.querySelector("input[name='mode']:checked").value; }

async function loadState() {
  const stored = await chrome.storage.local.get({ bridgeUrl: "http://127.0.0.1:8787", activeDocument: null, activeJob: null });
  state.bridgeUrl = stored.bridgeUrl;
  state.activeDocument = stored.activeDocument;
  state.job = stored.activeJob;
  if (state.job) await refreshJob();
}

async function capture() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active tab is available.");
  const response = await chrome.tabs.sendMessage(tab.id, { type: "CAPTURE_LATEST_ANSWER" });
  if (!response?.ok) throw new Error(response?.error ?? "The page did not return a capturable answer.");
  state.capture = response;
  $("#capture-card").hidden = false;
  $("#capture-meta").textContent = `Captured from ${response.source}.`;
  $("#preview").innerHTML = response.html;
  $("#start").disabled = false;
  setStatus("Captured rich content. Choose a destination and send it for review.");
}

async function startReview() {
  if (!state.capture) return;
  const mode = selectedMode();
  if (mode === "append" && !state.activeDocument) throw new Error("There is no active document yet. Create one first.");
  const sessionId = state.activeDocument?.sessionId ?? newSessionId();
  const documentHtml = mode === "append"
    ? state.activeDocument.html
    : createDocument({ templateId: $("#template").value, title: $("#title").value, capturedHtml: state.capture.html });
  const job = await client().startJob({ session_id: sessionId, document_html: documentHtml, message: mode === "append" ? appendInstruction() : createInstruction(), approval_mode: "ask_every_time" });
  state.job = { jobId: job.job_id, sessionId, documentHtml };
  await chrome.storage.local.set({ activeJob: state.job });
  setStatus("SuperDocs is processing the document…");
  await refreshJob();
}

function renderChanges(changes) {
  const form = $("#decisions"); form.replaceChildren();
  for (const change of changes) {
    const card = document.createElement("label"); card.className = "change";
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.name = "change"; checkbox.value = change.change_id; checkbox.checked = true;
    const explanation = document.createElement("span"); explanation.textContent = change.ai_explanation || `${change.operation ?? "edit"} a document section`;
    const before = document.createElement("code"); before.textContent = `Before: ${change.old_html || "(new content)"}\nAfter: ${change.new_html || ""}`;
    card.append(checkbox, explanation, before); form.append(card);
  }
  $("#review").hidden = false;
}

async function refreshJob() {
  if (!state.job) return;
  const job = await client().getJob(state.job.jobId);
  const status = jobState(job);
  if (status === "processing") { setStatus("SuperDocs is still processing. This can take a little while for long answers."); window.setTimeout(() => refreshJob().catch(showError), 1200); return; }
  if (status === "review") { setStatus("Review each proposed change before it is applied."); renderChanges(pendingChanges(job)); return; }
  if (status === "completed") {
    const html = finalHtml(job);
    if (!html) throw new Error("The completed job did not return document HTML.");
    state.activeDocument = { sessionId: state.job.sessionId, html };
    state.job = null;
    await chrome.storage.local.set({ activeDocument: state.activeDocument, activeJob: null });
    $("#review").hidden = true; $("#export").hidden = false;
    setStatus("Approved changes are now in the active document.");
    return;
  }
  throw new Error(job.error || `The job ended with status: ${job.status}.`);
}

async function applyChanges() {
  const changes = [...document.querySelectorAll("input[name='change']")].map((input) => ({ change_id: input.value }));
  const selected = new Set([...document.querySelectorAll("input[name='change']:checked")].map((input) => input.value));
  await client().decide(state.job.sessionId, { job_id: state.job.jobId, approved: true, changes: decisionsFromForm(changes, selected) });
  $("#review").hidden = true; setStatus("Decision submitted. Continuing processing…"); window.setTimeout(() => refreshJob().catch(showError), 900);
}

async function exportDocument() {
  const response = await client().exportDocument({ html: state.activeDocument.html, format: "docx", filename: "chat-to-superdocs.docx" });
  const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "chat-to-superdocs.docx"; link.click(); URL.revokeObjectURL(url);
  setStatus("DOCX export downloaded.");
}

function showError(error) { setStatus(error instanceof Error ? error.message : String(error)); }
$("#capture").addEventListener("click", () => capture().catch(showError));
$("#start").addEventListener("click", () => startReview().catch(showError));
$("#apply").addEventListener("click", (event) => { event.preventDefault(); applyChanges().catch(showError); });
$("#export").addEventListener("click", () => exportDocument().catch(showError));
$("#settings").addEventListener("click", (event) => { event.preventDefault(); chrome.runtime.openOptionsPage(); });
loadState().catch(showError);
