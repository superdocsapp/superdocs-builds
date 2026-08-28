import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";
import JSZip from "jszip";
import { parseDocxTrackChanges, toChange } from "../src/core/trackchanges";
import { segmentize } from "../src/core/writeback";
import { buildAlignment, planPatches, applyPatches } from "../src/core/align";

const FIX = path.join(__dirname, "fixtures");

function fixture(name: string): string {
  return fs.readFileSync(path.join(FIX, name), "utf8");
}

async function makeDocx(documentXml: string): Promise<Uint8Array> {
  const zip = new JSZip();
  zip.file("word/document.xml", documentXml);
  const buf = await zip.generateAsync({ type: "uint8array" });
  return buf;
}

const INS_PARAGRAPH = `<w:p><w:pPr><w:rPr><w:rFonts w:ascii="Times"/></w:rPr></w:pPr><w:r><w:t>Random walks on groups are studied objects</w:t></w:r><w:ins w:id="7" w:author="CoAuthor" w:date="2026-08-10T10:00:00Z"><w:r><w:t> in probability theory</w:t></w:r></w:ins><w:r><w:t>.</w:t></w:r></w:p>`;

const DEL_PARAGRAPH = `<w:p><w:del w:id="8" w:author="CoAuthor" w:date="2026-08-10T10:00:00Z"><w:r><w:delText>in probability theory </w:delText></w:r></w:del><w:r><w:t>and harmonic analysis.</w:t></w:r></w:p>`;

describe("parseDocxTrackChanges", () => {
  it("extracts ins/del paragraphs with author and both renderings", async () => {
    const docx = await makeDocx(
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${INS_PARAGRAPH}${DEL_PARAGRAPH}</w:body></w:document>`
    );
    const changes = await parseDocxTrackChanges(docx);
    expect(changes.length).toBe(2);
    const ins = changes.find((c) => c.id === "7")!;
    expect(ins.author).toBe("CoAuthor");
    expect(ins.date).toBe("2026-08-10T10:00:00Z");
    expect(ins.oldText).toBe("Random walks on groups are studied objects.");
    expect(ins.newText).toBe(
      "Random walks on groups are studied objects in probability theory."
    );
    const del = changes.find((c) => c.id === "8")!;
    expect(del.oldText).toContain("in probability theory");
    expect(del.newText).toBe("and harmonic analysis.");
  });

  it("returns [] for docx without tracked changes", async () => {
    const docx = await makeDocx(
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>plain</w:t></w:r></w:p></w:body></w:document>`
    );
    expect((await parseDocxTrackChanges(docx)).length).toBe(0);
  });

  it("survives a real docx zip (export fixture)", async () => {
    const bytes = new Uint8Array(fs.readFileSync(path.join(FIX, "export-a4.docx")));
    const changes = await parseDocxTrackChanges(bytes);
    expect(Array.isArray(changes)).toBe(true);
  });

  it("joins runs split by w:br with a space", async () => {
    const docx = await makeDocx(
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>We study random walks on Cayley</w:t><w:br/><w:t>graphs of finite groups</w:t></w:r><w:ins w:id="10" w:author="CoAuthor"><w:r><w:t>,</w:t></w:r></w:ins></w:p></w:body></w:document>`
    );
    const [tc] = await parseDocxTrackChanges(docx);
    expect(tc).toBeDefined();
    expect(tc.oldText).toBe("We study random walks on Cayley graphs of finite groups");
    expect(tc.newText).toBe("We study random walks on Cayley graphs of finite groups,");
  });
});

describe("tracked changes through the write-back planner", () => {
  it("plans and applies a co-author insertion to the source", async () => {
    const docx = await makeDocx(
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${INS_PARAGRAPH}</w:body></w:document>`
    );
    const [tc] = await parseDocxTrackChanges(docx);
    const abstract = fixture("sample-abstract.tex");
    const files = { "sections/intro.tex": abstract };
    const segments = new Map([["sections/intro.tex", segmentize(abstract)]]);
    const plan = buildAlignment(files, segments);
    const { patches, unresolved } = planPatches([toChange(tc)], plan, files);
    expect(unresolved).toEqual([]);
    expect(patches.length).toBe(1);
    const { files: patched } = applyPatches(files, patches);
    const result = patched.get("sections/intro.tex")!;
    expect(result).toContain("studied objects in probability theory.");
    expect(result.slice(result.length - 30)).toBe(abstract.slice(abstract.length - 30));
    expect(result).not.toContain("\n\n\n\n");
    expect(result).not.toContain("and harmonic analysis.\n\n\n");
  });

  it("span-edit preserves untouched bytes outside the changed run", async () => {
    const docx = await makeDocx(
      `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${DEL_PARAGRAPH}</w:body></w:document>`
    );
    const [tc] = await parseDocxTrackChanges(docx);
    const abstract = fixture("sample-abstract.tex");
    const files = { "sections/intro.tex": abstract };
    const segments = new Map([["sections/intro.tex", segmentize(abstract)]]);
    const plan = buildAlignment(files, segments);
    const { patches, unresolved } = planPatches([toChange(tc)], plan, files);
    expect(unresolved).toEqual([]);
    expect(patches.length).toBe(1);
    const p = patches[0];
    expect(p.operation).toBe("edit");
    const before = abstract.slice(p.start - 20, p.start);
    const after = abstract.slice(p.end, p.end + 30);
    expect(before).toContain("objects");
    expect(after).toContain("finitely");    const { files: patched } = applyPatches(files, patches);
    const result = patched.get("sections/intro.tex")!;
    expect(result).toContain("studied objects and harmonic analysis. Given");
    expect(result).not.toContain("studied objects in probability theory");
    const expectedTail = abstract.slice(abstract.length - 60);
    expect(result.slice(result.length - 60)).toBe(expectedTail);
  });
});
