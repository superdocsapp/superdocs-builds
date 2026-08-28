import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";
import { segmentize, normalize, htmlToLatex } from "../src/core/writeback";
import { visibleWords, planPatches, buildAlignment, subsequenceScore } from "../src/core/align";

const FIX = path.join(__dirname, "fixtures");

function fixture(name: string): string {
  return fs.readFileSync(path.join(FIX, name), "utf8");
}

describe("segmentize", () => {
  it("splits at blank lines with splice-safe offsets", () => {
    const content = "first line\nsecond line\n\nthird line\n\n\nfourth";
    const segs = segmentize(content);
    expect(segs.length).toBe(3);
    expect(segs[0].text).toBe("first line\nsecond line");
    expect(segs[0].start).toBe(0);
    expect(segs[0].end).toBe(22);
    expect(content.slice(segs[0].start, segs[0].end)).toBe("first line\nsecond line");
    expect(segs[1].text).toBe("third line");
    expect(content.slice(segs[1].start, segs[1].end)).toBe("third line");
    expect(segs[2].text).toBe("fourth");
    expect(content.slice(segs[2].start, segs[2].end)).toBe("fourth");
  });

  it("covers the whole document when concatenated", () => {
    const content = fixture("sample-abstract.tex");
    const segs = segmentize(content);
    let rebuilt = "";
    for (const s of segs) rebuilt += content.slice(s.start, s.end) + "\n\n";
    expect(rebuilt.trim()).toBe(content.trim());
  });
});

describe("htmlToLatex", () => {
  it("round-trips math losslessly", () => {
    const html =
      '<p><span data-latex="P(x, y) = \\frac{1}{|S|} \\, \\mathbf{1}_{y \\in x S}," data-type="block-math">P(x, y) = frac...</span></p>';
    const latex = htmlToLatex(html, []);
    expect(latex).toContain("\\frac{1}{|S|}");
    expect(latex).toContain("\\mathbf{1}_{y \\in x S}");
  });

  it("replaces citations with \\cite", () => {
    const html = '<p>see <span data-citation="Kesten1959,Woess2000">(Kesten 1959; Woess 2000)</span>.</p>';
    expect(htmlToLatex(html, [])).toContain("\\cite{Kesten1959,Woess2000}");
  });

  it("inlines footnotes", () => {
    const html = '<p>text.<sup data-footnote-ref="1">1</sup></p>';
    const latex = htmlToLatex(html, ["the footnote body"]);
    expect(latex).toContain("\\footnote{the footnote body}");
  });

  it("turns headings into sections and strips rendered numbers", () => {
    const html = '<h1 data-chunk-id="x" id="sec:main">3  Main Results</h1>';
    expect(htmlToLatex(html, []).trim()).toBe("\\section{Main Results}");
  });
});

describe("alignment", () => {
  const files = {
    "sections/intro.tex": fixture("sample-abstract.tex"),
  };
  const segments = new Map(
    Object.entries(files).map(([f, c]) => [f, segmentize(c)] as [string, ReturnType<typeof segmentize>])
  );
  const plan = buildAlignment(files, segments);

  it("aligns a chunk whose text exists in the source", () => {
    const chunk = plan.align({
      change_id: "c1",
      chunk_id: "74c123ae-7a80-44ec-a535-d216fcb42efd",
      operation: "edit",
      old_html: "<p><strong>Abstract</strong></p>",
      new_html: "<p><strong>Abstract</strong></p>",
    });
    expect(chunk).toBeDefined();
    expect(chunk!.file).toBe("sections/intro.tex");
    expect(files[chunk!.file].slice(chunk!.start, chunk!.end)).toContain("abstract");
  });

  it("leaves unmatched chunks unresolved", () => {
    const chunk = plan.align({
      change_id: "c2",
      chunk_id: "zzz",
      operation: "edit",
      old_html: "<p>this text does not exist anywhere in the document at all</p>",
      new_html: "<p>whatever</p>",
    });
    expect(chunk).toBeUndefined();
  });
});

describe("planPatches (fixture-driven)", () => {
  const abstract = fixture("sample-abstract.tex");
  const files = { "sections/intro.tex": abstract };
  const segments = new Map([["sections/intro.tex", segmentize(abstract)]]);
  const plan = buildAlignment(files, segments);

  it("detects append-after-heading inserts from real job fixture", () => {
    const job = JSON.parse(fixture("job-awaiting.json"));
    const pc = job.metadata.pending_changes[0];
    const { patches, unresolved } = planPatches(
      [
        {
          change_id: pc.change_id,
          chunk_id: pc.chunk_id,
          operation: pc.operation,
          old_html: pc.old_html,
          new_html: pc.new_html,
        },
      ],
      plan,
      files
    );
    expect(unresolved).toEqual([]);
    expect(patches.length).toBe(1);
    const p = patches[0];
    expect(p.operation).toBe("insert");
    expect(p.file).toBe("sections/intro.tex");
    expect(p.start).toBe(p.end);
    expect(files[p.file].slice(p.start, p.start + 20)).toContain("tableofcontents");
  });

  it("patches range-by-range leaving untouched bytes identical", async () => {
    const job = JSON.parse(fixture("job-awaiting.json"));
    const pc = job.metadata.pending_changes[0];
    const { applyPatches } = await import("../src/core/align");
    const { patches } = planPatches(
      [
        {
          change_id: pc.change_id,
          chunk_id: pc.chunk_id,
          operation: pc.operation,
          old_html: pc.old_html,
          new_html: pc.new_html,
        },
      ],
      plan,
      files
    );
    const { files: patched } = applyPatches(files, patches);
    const original = files["sections/intro.tex"];
    const result = patched.get("sections/intro.tex")!;
    expect(result.length).toBeGreaterThan(original.length);
    expect(result).toContain("This abstract presents the core information of the document in a concise manner");
    // untouched region (tail) byte-identical
    const originalTail = original.slice(original.length - 40);
    const resultTail = result.slice(result.length - 40);
    expect(resultTail).toBe(originalTail);
  });

  it("visibleWords ignores tags and math", () => {
    const html = '<p><strong>Abstract</strong> <span data-latex="x">x</span></p>';
    expect(visibleWords(html)).toEqual(["abstract"]);
  });

  it("subsequenceScore measures ordered overlap", () => {
    expect(subsequenceScore(["a", "b", "c"], ["a", "b", "c"])).toBe(1);
    expect(subsequenceScore(["a", "b", "c"], ["a", "x", "b", "y", "c"])).toBe(1);
    expect(subsequenceScore(["a", "b", "c"], ["x", "y"])).toBe(0);
  });
});

describe("normalize", () => {
  it("strips latex commands and braces", () => {
    expect(normalize("\\section{Introduction}")).toBe("introduction");
    expect(normalize("$\\lambda_1$")).toBe("1");
  });
});
