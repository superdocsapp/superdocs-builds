import assert from "node:assert/strict";
import test from "node:test";
import {
  alignChunks,
  applyApprovedChanges,
  assertExportAgrees,
  assertNoUnownedChange,
  buildRegionDocument,
  exportedRegions,
  htmlToMarkdown,
  ownershipPrompt,
  parseOwnership,
  replaceOwnedRegions,
} from "../src/ownership";
import { renderChunks } from "./harness/superdocs-fake";
import type { PendingChange } from "../src/types";

const NOTE = [
  "# Personal knowledge dashboard",
  "",
  "Human paragraph: do not rewrite this. It has trailing spaces.  ",
  "",
  "<!-- superdocs:owned:start id=\"summary\" -->",
  "## What the vault says right now",
  "",
  "- **First** point that is out of date",
  "- Second point",
  "",
  "A closing sentence with _emphasis_ inside the owned region.",
  "<!-- superdocs:owned:end id=\"summary\" -->",
  "",
  "Another human paragraph. It stays byte for byte unchanged.",
  "",
  "<!-- superdocs:owned:start id=\"questions\" -->",
  "Nothing recorded yet.",
  "<!-- superdocs:owned:end id=\"questions\" -->",
  "",
  "Closing human words.",
].join("\n");

function prepare(note = NOTE) {
  const ownership = parseOwnership(note);
  assert.deepEqual(ownership.errors, []);
  const document = buildRegionDocument(note, ownership.regions);
  const rendered = renderChunks(document.markdown);
  const chunkIndex = alignChunks(rendered.html, document.blocks);
  return { note, ownership, document, rendered, chunkIndex };
}

function chunkFor(rendered: ReturnType<typeof renderChunks>, contains: string) {
  const chunk = rendered.chunks.find((candidate) => candidate.text.includes(contains));
  assert.ok(chunk, `no chunk containing ${contains}`);
  return chunk;
}

test("parses explicit non-overlapping ownership boundaries", () => {
  const result = parseOwnership(NOTE);
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.regions.map((region) => region.id), ["summary", "questions"]);
});

test("rejects missing, duplicate and overlapping boundaries", () => {
  assert.match(parseOwnership('<!-- superdocs:owned:start id="a" -->').errors.join(" "), /missing its end/);
  assert.match(parseOwnership('<!-- superdocs:owned:end id="a" -->').errors.join(" "), /without a start/);
  assert.match(parseOwnership([
    '<!-- superdocs:owned:start id="a" -->',
    '<!-- superdocs:owned:start id="b" -->',
    '<!-- superdocs:owned:end id="a" -->',
    '<!-- superdocs:owned:end id="b" -->',
  ].join("\n")).errors.join(" "), /nested|overlap/);
  assert.match(parseOwnership("no markers here").errors.join(" "), /no owned regions/);
});

test("gives every region a brief, from the marker or the heading above it", () => {
  const withBrief = '# Note\n\n<!-- superdocs:owned:start id="a" brief="what shipped this week" -->\nx\n<!-- superdocs:owned:end id="a" -->';
  assert.equal(parseOwnership(withBrief).regions[0].brief, "what shipped this week");
  assert.equal(parseOwnership(NOTE).regions[0].brief, "Personal knowledge dashboard");
  assert.match(ownershipPrompt(parseOwnership(withBrief).regions), /superdocs-region: a -> what shipped this week/);
});

test("rejects two regions that share an id before any network call", () => {
  const note = [
    '<!-- superdocs:owned:start id="a" -->', "one", '<!-- superdocs:owned:end id="a" -->',
    "human text between them",
    '<!-- superdocs:owned:start id="a" -->', "two", '<!-- superdocs:owned:end id="a" -->',
  ].join("\n");
  assert.match(parseOwnership(note).errors.join(" "), /declared more than once/);
});

test("rejects a reserved region heading inside an owned region", () => {
  const note = '<!-- superdocs:owned:start id="a" -->\n## superdocs-region: a\n<!-- superdocs:owned:end id="a" -->';
  assert.match(parseOwnership(note).errors.join(" "), /reserved/);
});

test("aligns the Markdown people actually write: tables, task lists, images, fenced code", () => {
  const note = [
    '<!-- superdocs:owned:start id="mixed" -->',
    "| Build | State |",
    "| --- | --- |",
    "| plugin | green |",
    "",
    "- [ ] record the demo",
    "- [x] fix the export check",
    "",
    "![Build chart](charts/build.png)",
    "",
    "```bash",
    "npm test",
    "",
    "npm run build",
    "```",
    "",
    "A closing line.",
    '<!-- superdocs:owned:end id="mixed" -->',
  ].join("\n");
  const { document, chunkIndex } = prepare(note);
  assert.equal(document.blocks.length, 6);
  assert.equal(chunkIndex.size, 6);
  assert.ok(document.blocks.some((block) => block.text.startsWith("```bash") && block.text.includes("npm run build")));
});

test("uploads owned-region content only, never the human paragraphs", () => {
  const { document } = prepare();
  assert.match(document.markdown, /## superdocs-region: summary/);
  assert.match(document.markdown, /## superdocs-region: questions/);
  assert.doesNotMatch(document.markdown, /Human paragraph/);
  assert.doesNotMatch(document.markdown, /Closing human words/);
  assert.doesNotMatch(document.markdown, /superdocs:owned/);
  for (const block of document.blocks) {
    if (block.synthetic) continue;
    assert.equal(NOTE.slice(block.start, block.end), block.text);
  }
});

test("refuses to write when the chunk alignment does not hold", () => {
  const { document, rendered } = prepare();
  assert.throws(() => alignChunks(rendered.html.replace(/<p data-chunk-id="chunk-6"[^>]*>[^<]*<\/p>/, ""), document.blocks), /chunks for|does not match/);
  assert.throws(() => alignChunks(rendered.html.replace("Second point", "Smuggled point"), document.blocks), /does not match/);
});

test("applies an approved edit to exactly one Markdown block", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "First");
  const updated = applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c1",
    operation: "edit",
    chunk_id: chunk.chunkId,
    old_html: chunk.html,
    new_html: '<ul data-chunk-id="chunk-3"><li><strong>First</strong> point, now current</li><li>Second point</li></ul>',
  }]);
  assert.match(updated, /\*\*First\*\* point, now current/);
  assert.match(updated, /Human paragraph: do not rewrite this\. It has trailing spaces\. {2}/);
  assert.match(updated, /Another human paragraph\. It stays byte for byte unchanged\./);
  assert.match(updated, /Closing human words\./);
  assert.equal(updated.split("<!-- superdocs:owned:start")[0], NOTE.split("<!-- superdocs:owned:start")[0]);
  assert.doesNotThrow(() => assertNoUnownedChange(NOTE, updated));
});

test("places an approved insert inside the region that anchored it", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "Nothing recorded yet");
  const updated = applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c2",
    operation: "create",
    insert_after_chunk_id: chunk.chunkId,
    new_html: "<p>Open question: who owns the changelog?</p>",
  }]);
  const region = parseOwnership(updated).regions.find((candidate) => candidate.id === "questions")!;
  assert.match(updated.slice(region.contentStart, region.contentEnd), /Open question: who owns the changelog\?/);
  assert.doesNotThrow(() => assertNoUnownedChange(NOTE, updated));
});

test("orders an insert and an edit that share an anchor", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "Nothing recorded yet");
  const updated = applyApprovedChanges(NOTE, document, chunkIndex, [
    { change_id: "insert", operation: "create", insert_before_chunk_id: chunk.chunkId, new_html: "<p>Two questions are open.</p>" },
    { change_id: "edit", operation: "edit", chunk_id: chunk.chunkId, old_html: chunk.html, new_html: "<p>Who owns the changelog?</p>" },
  ]);
  const region = parseOwnership(updated).regions.find((candidate) => candidate.id === "questions")!;
  assert.equal(updated.slice(region.contentStart, region.contentEnd).trim(), "Two questions are open.\n\nWho owns the changelog?");
  assert.doesNotThrow(() => assertNoUnownedChange(NOTE, updated));
});

test("removes a block on an approved delete", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "closing sentence");
  const updated = applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c3",
    operation: "delete",
    chunk_id: chunk.chunkId,
    old_html: chunk.html,
  }]);
  assert.doesNotMatch(updated, /closing sentence/);
  assert.doesNotThrow(() => assertNoUnownedChange(NOTE, updated));
});

test("refuses a change whose old text no longer matches the note", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "Second point");
  assert.throws(() => applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c4",
    operation: "edit",
    chunk_id: chunk.chunkId,
    old_html: "<p>text that was never in this note</p>",
    new_html: "<p>anything</p>",
  }]), /does not match the note text/);
});

test("refuses a change that points outside the owned regions", () => {
  const { document, chunkIndex } = prepare();
  assert.throws(() => applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c5",
    operation: "edit",
    chunk_id: "chunk-from-another-document",
    old_html: "<p>Human paragraph: do not rewrite this.</p>",
    new_html: "<p>rewritten</p>",
  }]), /not part of an owned region/);
});

test("refuses a change aimed at a region heading", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "superdocs-region: summary");
  assert.throws(() => applyApprovedChanges(NOTE, document, chunkIndex, [{
    change_id: "c6",
    operation: "edit",
    chunk_id: chunk.chunkId,
    old_html: chunk.html,
    new_html: "<h2>hijacked boundary</h2>",
  }]), /region heading/);
});

test("refuses two approved changes that fight over one paragraph", () => {
  const { document, rendered, chunkIndex } = prepare();
  const chunk = chunkFor(rendered, "Second point");
  const change: PendingChange = { change_id: "c7", operation: "edit", chunk_id: chunk.chunkId, old_html: chunk.html, new_html: "<p>one</p>" };
  assert.throws(() => applyApprovedChanges(NOTE, document, chunkIndex, [change, { ...change, change_id: "c8", new_html: "<p>two</p>" }]), /same paragraph/);
});

test("keeps every byte outside the markers, including CRLF notes", () => {
  const note = NOTE.replace(/\n/g, "\r\n");
  const { document, rendered, chunkIndex } = prepare(note);
  const chunk = chunkFor(rendered, "Nothing recorded yet");
  const updated = applyApprovedChanges(note, document, chunkIndex, [{
    change_id: "c9",
    operation: "edit",
    chunk_id: chunk.chunkId,
    old_html: chunk.html,
    new_html: "<p>Three questions are open.</p>",
  }]);
  const before = (text: string) => text.slice(0, text.indexOf("<!-- superdocs:owned:start"));
  const after = (text: string) => text.slice(text.lastIndexOf("<!-- superdocs:owned:end"));
  assert.equal(before(updated), before(note));
  assert.equal(after(updated), after(note));
});

test("refuses a candidate that changed unowned bytes", () => {
  const original = 'human\n<!-- superdocs:owned:start id="a" -->\na\n<!-- superdocs:owned:end id="a" -->';
  const updated = 'rewritten human\n<!-- superdocs:owned:start id="a" -->\na\n<!-- superdocs:owned:end id="a" -->';
  assert.throws(() => assertNoUnownedChange(original, updated), /outside owned/);
  assert.throws(() => replaceOwnedRegions(original, "# a response with no markers at all"), /omitted|no owned regions/);
});

test("checks the local result against the SuperDocs export", () => {
  const exportText = [
    "## superdocs-region: summary",
    "",
    "## What the vault says right now",
    "",
    "- **First** point that is out of date",
    "- Second point",
    "",
    "A closing sentence with _emphasis_ inside the owned region.",
    "",
    "## superdocs-region: questions",
    "",
    "Nothing recorded yet.",
  ].join("\n");
  assert.deepEqual([...exportedRegions(exportText).keys()], ["summary", "questions"]);
  assert.doesNotThrow(() => assertExportAgrees(NOTE, exportText));
  assert.throws(() => assertExportAgrees(NOTE, exportText.slice(0, exportText.indexOf("## superdocs-region: questions"))), /lost region 'questions'/);
  assert.throws(() => assertExportAgrees(NOTE, exportText.replace("Second point", "A point nobody approved")), /does not match the approved document/);
});

test("converts proposed HTML back into readable Markdown", () => {
  assert.equal(htmlToMarkdown("<p>Plain <strong>bold</strong> and <em>italic</em>.</p>"), "Plain **bold** and *italic*.");
  assert.equal(htmlToMarkdown("<ul><li>one</li><li>two</li></ul>"), "- one\n- two");
  assert.equal(htmlToMarkdown("<ol><li>one</li><li>two</li></ol>"), "1. one\n2. two");
  assert.equal(htmlToMarkdown('<h3>Title</h3><p>Body with <a href="https://superdocs.app">a link</a>.</p>'), "### Title\n\nBody with [a link](https://superdocs.app).");
  assert.equal(htmlToMarkdown("<p>5 &lt; 7 &amp; 9 &gt; 2</p>"), "5 < 7 & 9 > 2");
});
