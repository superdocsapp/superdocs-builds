import { Router } from "express";
import multer from "multer";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { SuperDocSession } from "../lib/superdocCli.js";
import { getResumeRevisions } from "../lib/llm.js";

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024 },
});

// Flag revisions whose length changed drastically vs. the original block —
// worth a second look even though tracked changes never touch layout XML,
// since a much longer/shorter block can still shift where lines wrap.
const LENGTH_FLAG_RATIO = 0.4;

// Best-effort page estimate: ~28 resume lines per Word page at 11pt with
// 1" margins. Real page numbers need a layout engine; this is an anchor for
// review, not a pagination guarantee.
const BLOCKS_PER_PAGE = 28;

export function createTailorRouter({
  sessionFactory = () => new SuperDocSession(),
  llm = getResumeRevisions,
} = {}) {
  const router = Router();

  router.post("/", upload.single("resume"), async (req, res) => {
  const jdText = req.body.jobDescription;
  if (!req.file || !jdText) {
    return res
      .status(400)
      .json({ error: "Upload a .docx resume and paste a job description." });
  }

  const tmpPath = path.join(os.tmpdir(), `resume-${crypto.randomUUID()}.docx`);
  const session = sessionFactory();

  try {
    await fs.writeFile(tmpPath, req.file.buffer);
    await session.open(tmpPath);

    const blocks = await session.listBlocks();
    const revisions = await llm(jdText, blocks);

    const byId = new Map(blocks.map((b) => [b.nodeId, b]));
    const blockOrder = new Map(blocks.map((b, i) => [b.nodeId, i]));
    const applied = [];

    for (const rev of revisions) {
      const block = byId.get(rev.nodeId);
      if (!block) continue; // model referenced an id that doesn't exist — skip, don't guess

      await session.replaceBlockTracked(block, rev.revisedText);

      const ratio = rev.revisedText.length / Math.max(block.text.length, 1);
      const idx = blockOrder.get(rev.nodeId) ?? 0;
      applied.push({
        ...rev,
        original: block.text,
        line: idx + 1,
        page: Math.floor(idx / BLOCKS_PER_PAGE) + 1,
        lengthFlag: ratio < LENGTH_FLAG_RATIO || ratio > 1 / LENGTH_FLAG_RATIO,
      });
    }

    await session.save();
    const editedBuffer = await fs.readFile(tmpPath);

    res.json({
      docx: editedBuffer.toString("base64"),
      revisions: applied,
    });
  } catch (err) {
    console.error(err);
    res
      .status(500)
      .json({ error: "Tailoring failed. Check server logs for details." });
  } finally {
    await session.close().catch(() => {});
    await fs.unlink(tmpPath).catch(() => {});
  }
  });

  return router;
}

export default createTailorRouter();
