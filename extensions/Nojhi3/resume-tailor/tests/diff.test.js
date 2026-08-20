import { test } from "node:test";
import assert from "node:assert/strict";
import { computeRegions } from "../server/lib/diff.js";

// Applying every region's newText at its offsets must rebuild the revised
// text from the original.
function apply(oldText, regions) {
  let out = "";
  let pos = 0;
  for (const r of regions) {
    assert.ok(r.start >= pos, "regions are ordered and non-overlapping");
    out += oldText.slice(pos, r.start) + r.newText;
    pos = r.end;
  }
  out += oldText.slice(pos);
  return out;
}

test("no change: empty region list", () => {
  const text = "Unchanged line stays untouched.";
  assert.deepEqual(computeRegions(text, text), []);
});

test("replacement: one region per changed word group", () => {
  const oldText = "Senior Engineer at Acme, led the platform team.";
  const newText = "Staff Engineer at Acme, led the platform org.";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 2);
  assert.equal(oldText.slice(regions[0].start, regions[0].end), "Senior ");
  assert.equal(regions[0].newText, "Staff ");
  assert.equal(oldText.slice(regions[1].start, regions[1].end), "team.");
  assert.equal(regions[1].newText, "org.");
  assert.equal(apply(oldText, regions), newText);
});

test("insertion: a region where old and new share the leading word", () => {
  const oldText = "Built workflows using YOLOv5 and CNN architectures.";
  const newText = "Built workflows using YOLOv5, TensorRT, and CNN architectures.";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(oldText.slice(regions[0].start, regions[0].end), "YOLOv5 ");
  assert.equal(regions[0].newText, "YOLOv5, TensorRT, ");
  assert.equal(apply(oldText, regions), newText);
});

test("deletion: replacement with empty text", () => {
  const oldText = "Improving reliability and reproducibility across datasets.";
  const newText = "Improving reliability across datasets.";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(oldText.slice(regions[0].start, regions[0].end), "and reproducibility ");
  assert.equal(regions[0].newText, "");
  assert.equal(apply(oldText, regions), newText);
});

test("mid-word rephrase stays a single word-level region", () => {
  const oldText = "end-to-end model serving workflows using YOLOv5";
  const newText = "end-to-end model serving workflows utilizing YOLOv5";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(oldText.slice(regions[0].start, regions[0].end), "using ");
  assert.equal(regions[0].newText, "utilizing ");
  assert.equal(apply(oldText, regions), newText);
});

test("neighboring edits merge into one region, not adjacent fragments", () => {
  const oldText = "suite of 30 runs. demonstrating robust system validation";
  const newText = "suite, demonstrating robust system validation";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(oldText.slice(regions[0].start, regions[0].end), "suite of 30 runs. ");
  assert.equal(regions[0].newText, "suite, ");
  assert.equal(apply(oldText, regions), newText);
});

test("total rewrite: single region covering the whole block", () => {
  const oldText = "Old line entirely rewritten.";
  const newText = "Completely different replacement text.";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(regions[0].start, 0);
  assert.equal(regions[0].end, oldText.length);
  assert.equal(apply(oldText, regions), newText);
});

test("insertions at both ends: the whole line becomes one rewrite region", () => {
  const oldText = "middle";
  const newText = "start middle end";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(regions[0].start, 0);
  assert.equal(regions[0].end, oldText.length);
  assert.equal(regions[0].newText, newText);
  assert.equal(apply(oldText, regions), newText);
});

test("punctuation-only change stays a single region", () => {
  const oldText = "Led the platform team";
  const newText = "Led the platform team,";
  const regions = computeRegions(oldText, newText);
  assert.equal(regions.length, 1);
  assert.equal(regions[0].newText, "team,");
  assert.equal(apply(oldText, regions), newText);
});