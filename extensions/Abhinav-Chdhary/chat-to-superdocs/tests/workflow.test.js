import assert from "node:assert/strict";
import test from "node:test";
import { appendInstruction, createDocument } from "../src/shared/document.js";
import { decisionsFromForm, finalHtml, jobState, parseProposedChangeBatch, pendingChanges } from "../src/shared/superdocs.js";

test("creates a styled document without flattening structured captured HTML", () => {
  const captured = "<h2>Plan</h2><ul><li>One<ul><li>Nested</li></ul></li></ul><table><tr><th>A</th></tr></table><pre><code>const x = 1;</code></pre><span data-latex=\"x^2\">x²</span>";
  const document = createDocument({ templateId: "brief", title: "Weekly update", capturedHtml: captured });
  for (const fragment of ["<h1>Weekly update</h1>", "<h2>Context</h2>", "<ul>", "<table>", "<pre><code>", "data-latex=\"x^2\""]) assert.match(document, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

test("append instruction protects existing content and requests review", () => {
  assert.match(appendInstruction(), /Do not rewrite existing content/);
  assert.match(appendInstruction(), /Propose every insertion for review/);
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
