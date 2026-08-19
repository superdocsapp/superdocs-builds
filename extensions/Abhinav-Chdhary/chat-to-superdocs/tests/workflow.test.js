import assert from "node:assert/strict";
import test from "node:test";
import { appendCapturedResponse, appendInstruction, conversationKey, createDocument, createInstruction } from "../src/shared/document.js";
import { BridgeClient, decisionsFromForm, finalHtml, focusedSessionDocument, jobState, normalizeSessionDocuments, normalizeTemplateList, parseProposedChangeBatch, pendingChanges, savedDocumentExists } from "../src/shared/superdocs.js";

test("creates a styled document without flattening structured captured HTML", () => {
  const captured = "<h2>Plan</h2><ul><li>One<ul><li>Nested</li></ul></li></ul><table><tr><th>A</th></tr></table><pre><code>const x = 1;</code></pre><span data-latex=\"x^2\">x²</span>";
  const document = createDocument({ capturedHtml: captured });
  for (const fragment of ["<ul>", "<table>", "<pre><code>", "data-latex=\"x^2\""]) assert.match(document, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.doesNotMatch(document, /<h1>/);
});

test("append instruction preserves the existing document exactly", () => {
  assert.match(appendInstruction(), /Keep the supplied document HTML exactly unchanged/);
  assert.match(appendInstruction(), /do not add a title/i);
});

test("appends captured markup without flattening the existing conversation document", () => {
  const appended = appendCapturedResponse("<html><body><h1>Notes</h1></body></html>", "<h2>Second answer</h2><pre><code>x</code></pre>");
  assert.match(appended, /<h1>Notes<\/h1>/);
  assert.match(appended, /<section data-chat-to-superdocs-capture="true"><h2>Second answer<\/h2><pre><code>x<\/code><\/pre><\/section>/);
});

test("uses a stable conversation key while ignoring query strings and fragments", () => {
  assert.equal(conversationKey("https://chatgpt.com/c/abc-123?model=fast#latest"), "https://chatgpt.com/c/abc-123");
});

test("uses a saved SuperDocs template rather than an extension-owned template", () => {
  const template = { id: "tpl_brand", name: "Acme branded memo" };
  assert.match(createInstruction(template), /Acme branded memo/);
  assert.match(createInstruction(template), /tpl_brand/);
  assert.match(createInstruction(template), /do not add a title/i);
  assert.doesNotMatch(createInstruction(template), /polished document section/i);
  assert.deepEqual(normalizeTemplateList({ templates: [template] }), [template]);
});

test("creates a clean blank document when no saved template is available", () => {
  assert.match(createInstruction(null), /Do not apply any additional styling/);
});

test("finds and verifies the durable File created by direct save", () => {
  const roster = { documents: [{ document_id: "doc_slot", durable_document_id: "doc_durable", focused: true }] };
  assert.deepEqual(normalizeSessionDocuments(roster), [{ id: "doc_slot", durableId: "doc_durable", focused: true }]);
  assert.deepEqual(focusedSessionDocument(roster), { id: "doc_slot", durableId: "doc_durable", focused: true });
  assert.equal(savedDocumentExists({ documents: [{ id: "doc_durable" }] }, "doc_durable"), true);
});

test("sends the extension identity to the local bridge when Origin is unavailable", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (_url, init) => { request = init; return new Response(JSON.stringify({ status: "completed" }), { status: 200 }); };
  try {
    await new BridgeClient("http://127.0.0.1:8787", "extension-id").getJob("job-1");
    assert.equal(request.headers["x-chat-to-superdocs-origin"], "chrome-extension://extension-id");
  } finally { globalThis.fetch = originalFetch; }
});

test("double parses a documented proposed-change batch", () => {
  const event = JSON.stringify({ content: JSON.stringify({ changes: [{ change_id: "c1", old_html: "<p>old</p>", new_html: "<p>new</p>" }] }) });
  assert.deepEqual(parseProposedChangeBatch(event), [{ change_id: "c1", old_html: "<p>old</p>", new_html: "<p>new</p>" }]);
});

test("keeps long-running jobs in processing and exposes review changes", () => {
  assert.equal(jobState({ status: "in_progress" }), "processing");
  const job = { status: "awaiting_approval", metadata: { pending_changes: [{ change_id: "c1" }] } };
  assert.equal(jobState(job), "review");
  assert.deepEqual(pendingChanges(job), [{ change_id: "c1" }]);
});

test("submits a decision for every proposed item and finds completed HTML", () => {
  const changes = [{ change_id: "yes" }, { change_id: "no" }];
  assert.deepEqual(decisionsFromForm(changes, new Set(["yes"])), [{ change_id: "yes", approved: true }, { change_id: "no", approved: false }]);
  assert.equal(finalHtml({ result: { document_changes: { updated_html: "<p>done</p>" } } }), "<p>done</p>");
});
