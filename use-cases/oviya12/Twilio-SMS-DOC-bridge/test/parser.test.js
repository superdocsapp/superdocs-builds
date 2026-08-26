import test from "node:test";
import assert from "node:assert/strict";
import { parseSms } from "../src/parser.js";

test("parses an edit SMS", () => {
  assert.deepEqual(parseSms("EDIT PDF https://files.example.org/report.docx :: add an executive summary"), {
    action: "EDIT", format: "pdf", reference: "https://files.example.org/report.docx", instruction: "add an executive summary"
  });
});

test("rejects edit without a document reference", () => {
  assert.throws(() => parseSms("EDIT PDF :: improve this"), /needs an HTTPS/);
});
