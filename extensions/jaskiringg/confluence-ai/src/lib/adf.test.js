const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const {
  adfToHtml,
  listSections,
  applyAcceptedChanges,
  htmlFragmentToAdf,
  isOpaque,
} = require("./adf");
const { normalizePendingChanges, parseTwice } = require("./superdocs");

const demo = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../fixtures/demo-page.adf.json"), "utf8")
);

describe("adf mapping", () => {
  it("assigns chunk ids and keeps opaque placeholders", () => {
    const { html, doc } = adfToHtml(demo);
    assert.match(html, /data-chunk-id=/);
    assert.match(html, /data-adf-opaque="true"/);
    assert.equal(doc.content.some((n) => isOpaque(n.type)), true);
    assert.doesNotMatch(html, /kubectl rollout undo/);
    assert.doesNotMatch(html, /Order API/);
  });

  it("lists heading sections", () => {
    const { sections } = listSections(demo);
    assert.ok(sections.length >= 3);
    assert.equal(sections[0].heading.includes("IT Change Policy"), true);
  });

  it("writeback replaces only accepted non-opaque blocks", () => {
    const { doc } = adfToHtml(demo);
    const freeze = doc.content.find((n) => n.type === "paragraph" && JSON.stringify(n).includes("02:00"));
    const table = doc.content.find((n) => n.type === "table");
    const next = applyAcceptedChanges(doc, [
      {
        operation: "edit",
        chunk_id: freeze.attrs.localId,
        new_html: "<p>North region freeze is 01:00-05:00 IST on release nights.</p>",
        approved: true,
      },
      {
        operation: "delete",
        chunk_id: table.attrs.localId,
        approved: true,
      },
    ]);
    const texts = JSON.stringify(next);
    assert.match(texts, /01:00-05:00/);
    assert.equal(next.content.some((n) => n.type === "table"), true);
    assert.equal(next.content.some((n) => n.type === "codeBlock"), true);
  });

  it("html fragment becomes heading + paragraph", () => {
    const frag = htmlFragmentToAdf("<h2>Purpose</h2><p>Not stated in source.</p>");
    assert.equal(frag[0].type, "heading");
    assert.equal(frag[1].type, "paragraph");
  });
});

describe("superdocs pending parse", () => {
  it("parses twice when payload is a JSON string", () => {
    const inner = [{ change_id: "ch_1", operation: "edit", chunk_id: "a", old_html: "<p>x</p>", new_html: "<p>y</p>" }];
    const wrapped = JSON.stringify(JSON.stringify(inner));
    const once = parseTwice(JSON.parse(wrapped));
    assert.equal(Array.isArray(once), true);
    const pending = normalizePendingChanges(JSON.stringify(inner));
    assert.equal(pending[0].change_id, "ch_1");
  });
});
