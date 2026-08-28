import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as crypto from "crypto";
import { execSync } from "child_process";
import JSZip from "jszip";
import { SuperDocsClient } from "../src/core/client";
import { BridgeSession, sessionIdFor } from "../src/core/session";
import { buildProjectZip, findLaTeXRoot } from "../src/core/zip";
import { writeBackToProject } from "../src/core/writeback-cli";
import { parseDocxTrackChanges, toChange } from "../src/core/trackchanges";

const LIVE = !!process.env.SUPERDOCS_LIVE_SMOKE;
const KEY = process.env.SUPERDOCS_API_KEY ?? "";

describe.skipIf(!LIVE)("live end-to-end smoke (SUPERDOCS_LIVE_SMOKE=1)", () => {
  it(
    "upload → chat edit with HITL → export docx → write back → compiles",
    async () => {
      expect(KEY).toBeTruthy();
      const client = new SuperDocsClient(KEY, {
        pollIntervalMs: 1500,
        maxPollSeconds: 1200,
      });
      const sampleDir = path.join(__dirname, "..", "samples", "math-paper");
      const root = findLaTeXRoot(sampleDir);
      expect(root).toBe("main.tex");
      const proj = await buildProjectZip(sampleDir, root!);

      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "lb-smoke-"));
      const copyDir = path.join(scratch, "project");
      fs.mkdirSync(copyDir);
      execSync("cp -R " + sampleDir + "/. " + copyDir + "/");

      const sid = sessionIdFor("smoke-" + crypto.randomBytes(3).toString("hex"));
      const events: string[] = [];
      const decisions = new Map<string, boolean>();
      const session = new BridgeSession(
        client,
        sid,
        { opBudget: 5, pollIntervalMs: 1500, maxPollSeconds: 1200 },
        (e) => {
          events.push(e.type);
          if (e.type === "awaiting_approval") {
            for (const c of e.changes ?? []) {
              decisions.set(c.change_id, true);
            }
            setTimeout(() => {
              session.submitDecisions(
                (e.changes ?? []).map((c) => ({ changeId: c.change_id, approved: true }))
              );
            }, 50);
          }
        }
      );

      const up = await session.uploadProject(proj.zipBytes, "main.zip", "application/zip");
      expect(up.sessionId).toBe(sid);
      expect(up.warnings).not.toContainEqual(
        expect.objectContaining({ code: expect.stringContaining("ERROR") })
      );
      expect(up.chunksCount).toBeGreaterThan(0);

      const job = await session.requestEdit(
        "Rewrite the abstract to exactly two sentences, and add one sentence to the introduction noting that the generating set is symmetric and contains no identity element."
      );
      expect(job.status).toBe("completed");
      expect(session.approvedChanges.length).toBeGreaterThan(0);

      const exportRes = await client.exportDocx(sid, { paper_size: "A4" });
      const docxPath = path.join(scratch, "edited.docx");
      fs.writeFileSync(docxPath, exportRes.body);
      expect(exportRes.body.byteLength).toBeGreaterThan(1000);

      const wb = await writeBackToProject(
        copyDir,
        root!,
        session.approvedChanges.map((c) => ({
          change_id: c.change_id,
          chunk_id: c.chunk_id,
          operation: c.operation,
          old_html: c.old_html,
          new_html: c.new_html,
        }))
      );
      console.log(
        "SMOKE approved:",
        JSON.stringify(
          session.approvedChanges.map((c) => ({
            id: c.change_id,
            op: c.operation,
            old: c.old_html.slice(0, 160),
            new: c.new_html.slice(0, 160),
          })),
          null,
          1
        )
      );
      console.log("SMOKE writeback:", JSON.stringify({ applied: wb.applied.length, unresolved: wb.unresolved.length }));
      expect(wb.applied.length).toBe(session.approvedChanges.length);
      expect(wb.unresolved.length).toBe(0);
      for (const [file, content] of wb.files) {
        fs.writeFileSync(path.join(copyDir, file), content);
      }
      const mainTex = fs.readFileSync(path.join(copyDir, "main.tex"), "utf8");
      expect(mainTex).not.toContain("LaTeX Bridge smoke");

      try {
        execSync("pdflatex -interaction=nonstopmode -halt-on-error main.tex", {
          cwd: copyDir,
          stdio: "pipe",
        });
        expect(fs.existsSync(path.join(copyDir, "main.pdf"))).toBe(true);
      } catch (err) {
        throw new Error("patched project no longer compiles: " + (err as Error).message);
      }

      fs.writeFileSync(path.join(scratch, "events.json"), JSON.stringify(events));
      console.log(
        JSON.stringify({
          scratch,
          sessionId: sid,
          jobsPolled: events.filter((e) => e === "waiting").length,
          approved: session.approvedChanges.length,
          patchedFiles: [...wb.files.keys()],
          docxBytes: exportRes.body.byteLength,
        })
      );
    },
    20 * 60 * 1000
  );

  it(
    "co-author tracked changes: inject w:ins/w:del into exported docx → import → apply → compiles",
    async () => {
      expect(KEY).toBeTruthy();
      const client = new SuperDocsClient(KEY, {
        pollIntervalMs: 1500,
        maxPollSeconds: 1200,
      });
      const sampleDir = path.join(__dirname, "..", "samples", "math-paper");
      const root = findLaTeXRoot(sampleDir);
      const proj = await buildProjectZip(sampleDir, root!);

      const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "lb-tc-"));
      const copyDir = path.join(scratch, "project");
      fs.mkdirSync(copyDir);
      execSync("cp -R " + sampleDir + "/. " + copyDir + "/");

      const sid = sessionIdFor("tc-" + crypto.randomBytes(3).toString("hex"));
      const session = new BridgeSession(
        client,
        sid,
        { opBudget: 5, pollIntervalMs: 1500, maxPollSeconds: 1200 },
        (e) => {
          if (e.type === "awaiting_approval") {
            setTimeout(() => {
              session.submitDecisions(
                (e.changes ?? []).map((c) => ({ changeId: c.change_id, approved: true }))
              );
            }, 50);
          }
        }
      );
      await session.uploadProject(proj.zipBytes, "main.zip", "application/zip");
      const job = await session.requestEdit(
        "Rewrite the abstract to exactly two sentences."
      );
      expect(job.status).toBe("completed");
      const exportRes = await client.exportDocx(sid, { paper_size: "A4" });
      fs.writeFileSync(path.join(scratch, "edited.docx"), exportRes.body);

      const zip = await JSZip.loadAsync(exportRes.body);
      const docXml = await zip.file("word/document.xml")!.async("string");
      const texts = [...docXml.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)].map((m) => m[1]);
      console.log("SMOKE tc texts:", JSON.stringify(texts.slice(0, 60)));
      const del = `<w:del w:id="9002" w:author="CoAuthor" w:date="2026-08-17T00:00:00Z"><w:r><w:delText>spectral gap estimates</w:delText></w:r></w:del>`;
      const delTarget = docXml.indexOf("spectral gap estimates");
      expect(delTarget).toBeGreaterThan(0);
      let patchedXml =
        docXml.slice(0, delTarget) +
        `</w:t></w:r>${del}<w:r><w:t>` +
        docXml.slice(delTarget + "spectral gap estimates".length);
      const cayley = patchedXml.indexOf("Cayley");
      expect(cayley).toBeGreaterThan(0);
      const runEnd = patchedXml.indexOf("</w:r>", cayley);
      expect(runEnd).toBeGreaterThan(0);
      const ins = `<w:ins w:id="9001" w:author="CoAuthor" w:date="2026-08-17T00:00:00Z"><w:r><w:t> and harmonic analysis</w:t></w:r></w:ins>`;
      patchedXml = patchedXml.slice(0, runEnd) + ins + patchedXml.slice(runEnd);
      zip.file("word/document.xml", patchedXml);
      const tcDocx = await zip.generateAsync({ type: "uint8array" });
      fs.writeFileSync(path.join(scratch, "tracked.docx"), Buffer.from(tcDocx));

      const changes = await parseDocxTrackChanges(tcDocx);
      expect(changes.length).toBeGreaterThan(0);
      const wb = await writeBackToProject(
        copyDir,
        root!,
        changes.map((c) => toChange(c))
      );
      console.log("SMOKE tc:", JSON.stringify({ found: changes.length, applied: wb.applied.length, unresolved: wb.unresolved.length }));
      expect(wb.applied.length).toBe(changes.length);
      expect(wb.unresolved.length).toBe(0);
      for (const [file, content] of wb.files) {
        fs.writeFileSync(path.join(copyDir, file), content);
      }
      const intro = fs.readFileSync(path.join(copyDir, "sections", "intro.tex"), "utf8");
      expect(intro).toContain("harmonic analysis");
      expect(intro).not.toContain("spectral gap estimates");
      try {
        execSync("pdflatex -interaction=nonstopmode -halt-on-error main.tex", {
          cwd: copyDir,
          stdio: "pipe",
        });
        expect(fs.existsSync(path.join(copyDir, "main.pdf"))).toBe(true);
      } catch (err) {
        throw new Error("tracked-changes patched project no longer compiles: " + (err as Error).message);
      }
      console.log(JSON.stringify({ scratch, sessionId: sid, docxBytes: exportRes.body.byteLength }));
    },
    20 * 60 * 1000
  );
});
