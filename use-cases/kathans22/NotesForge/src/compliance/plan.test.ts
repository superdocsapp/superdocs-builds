import assert from "node:assert/strict";
import { test } from "node:test";
import { extractBalancedJson, parseJsonLoosely } from "./plan.js";

test("parseJsonLoosely: parses clean JSON directly", () => {
  const result = parseJsonLoosely<{ outlines: unknown[] }>('{"outlines": [1, 2, 3]}');
  assert.deepEqual(result, { outlines: [1, 2, 3] });
});

test("parseJsonLoosely: strips a ```json fence", () => {
  const raw = '```json\n{"outlines": []}\n```';
  assert.deepEqual(parseJsonLoosely<{ outlines: unknown[] }>(raw), { outlines: [] });
});

test("parseJsonLoosely: recovers a genuinely double-encoded payload", () => {
  // The whole object re-wrapped as a JSON string — JSON.parse once yields a
  // string, which itself is valid JSON.
  const inner = { outlines: [{ client_id: "CL-01" }] };
  const doubleEncoded = JSON.stringify(JSON.stringify(inner));
  assert.deepEqual(parseJsonLoosely(doubleEncoded), inner);
});

test("parseJsonLoosely: recovers a stray trailing artifact after otherwise-valid JSON", () => {
  // The exact shape observed live (see evidence/bugs/BUG-002): a complete,
  // valid JSON object with `"}` appended after the real closing brace.
  const inner = { outlines: [{ client_id: "CL-01", sections: [{ requirement_id: "RIA-FEE-01" }] }] };
  const withTrailingGarbage = `${JSON.stringify(inner)}"}`;
  assert.deepEqual(parseJsonLoosely(withTrailingGarbage), inner);
});

test("parseJsonLoosely: throws on genuinely malformed input", () => {
  assert.throws(() => parseJsonLoosely("not json at all, no braces"));
  assert.throws(() => parseJsonLoosely('{"outlines": [1, 2,'));
});

test("extractBalancedJson: ignores braces inside string values", () => {
  const text = '{"heading": "Fee — {see note}"}garbage-after';
  assert.equal(extractBalancedJson(text), '{"heading": "Fee — {see note}"}');
});

test("extractBalancedJson: returns null when braces never balance", () => {
  assert.equal(extractBalancedJson('{"outlines": [1, 2,'), null);
});

test("extractBalancedJson: returns null with no opening brace at all", () => {
  assert.equal(extractBalancedJson("no json here"), null);
});
