#!/usr/bin/env node
/**
 * Hit the live Confluence IT policy page: SuperDocs HITL → approve freeze-window edit → write back.
 */
const path = require("path");
require("dotenv").config({ path: path.join(__dirname, "../.env") });
const { handlers } = require("../src/handlers");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const pageId = process.env.CONFLUENCE_PAGE_ID;
  const spaceId = process.env.CONFLUENCE_SPACE_ID;
  if (!pageId || !process.env.SUPERDOCS_API_KEY || !process.env.CONFLUENCE_API_TOKEN) {
    throw new Error("Need SUPERDOCS_API_KEY, CONFLUENCE_API_TOKEN, CONFLUENCE_PAGE_ID in .env");
  }
  const ctx = {
    kind: "sidecar",
    apiKey: process.env.SUPERDOCS_API_KEY,
    pageId,
    spaceId,
  };

  const g = await handlers.getContext({ pageId, spaceId }, ctx);
  console.log("page", g.page.title, "id", g.page.id, "v", g.page.version, "demo", g.page.demo);
  if (g.page.demo) throw new Error("Still on demo page — Confluence env not picked up");

  const freeze = (g.sections || []).find((s) => /freeze/i.test(s.heading || ""));
  console.log("section", freeze || g.sections?.[0]);

  const started = await handlers.startEdit(
    {
      pageId: g.page.id,
      message:
        "Change the freeze window to 01:00-05:00 IST. Do not invent other policy. Leave the table and the kubectl command untouched.",
      start: freeze?.start,
      end: freeze?.end,
      role: "author",
    },
    ctx
  );
  console.log("job", started);

  let settled;
  for (let i = 0; i < 45; i += 1) {
    const p = await handlers.pollJob({ jobId: started.jobId, sessionId: started.sessionId }, ctx);
    console.log("poll", i, p.status, p.awaitingKind, (p.pendingChanges || []).length);
    if (p.status === "awaiting_approval" && p.awaitingKind === "continue_prompt") {
      await handlers.resumeLargeEdit(
        { jobId: started.jobId, sessionId: started.sessionId, continue: true },
        ctx
      );
      await sleep(2000);
      continue;
    }
    if (p.status === "awaiting_approval" || p.status === "completed" || p.status === "failed") {
      settled = p;
      break;
    }
    await sleep(2000);
  }
  if (!settled) throw new Error("Timed out waiting for SuperDocs");
  if (settled.status === "failed") throw new Error(settled.error || "job failed");

  const pending = settled.pendingChanges || [];
  console.log("pending", JSON.stringify(pending, null, 2).slice(0, 4000));

  const decisions = pending.map((c) => {
    const blob = `${c.old_html || ""} ${c.new_html || ""} ${c.ai_explanation || ""}`;
    const freezeEdit = /01:00|05:00|freeze|02:00|06:00/i.test(blob);
    return {
      change_id: c.change_id,
      chunk_id: c.chunk_id,
      operation: c.operation,
      new_html: c.new_html,
      old_html: c.old_html,
      insert_after_chunk_id: c.insert_after_chunk_id,
      approved: freezeEdit || pending.length === 1,
    };
  });

  if (decisions.length) {
    await handlers.decide(
      { sessionId: started.sessionId, jobId: started.jobId, decisions },
      ctx
    );
  }

  const written = await handlers.writeBack(
    {
      sessionId: started.sessionId,
      pageId: g.page.id,
      decisions,
      role: "author",
    },
    ctx
  );
  console.log("wrote", written);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
