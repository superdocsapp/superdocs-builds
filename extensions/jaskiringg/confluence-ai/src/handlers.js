const {
  adfToHtml,
  listSections,
  sliceSectionHtml,
  applyAcceptedChanges,
  ensureLocalIds,
} = require("./lib/adf");
const {
  startHitlEdit,
  getJob,
  approveChanges,
  continueJob,
  exportPdf,
  HOUSE_STRUCTURE_PROMPT,
  LETTERHEAD,
} = require("./lib/superdocs");
const {
  getPage,
  updatePage,
  listSpacePages,
  searchUsers,
  getReviewState,
  setReviewState,
  DEMO_PAGE_ID,
  DEMO_SPACE_ID,
} = require("./lib/confluence");

const sessions = new Map();
const reviewMemory = new Map();

function envFrom(ctx) {
  return {
    SUPERDOCS_API_KEY: ctx.apiKey || process.env.SUPERDOCS_API_KEY,
    SUPERDOCS_API_BASE: process.env.SUPERDOCS_API_BASE,
    CONFLUENCE_BASE_URL: process.env.CONFLUENCE_BASE_URL,
    CONFLUENCE_EMAIL: process.env.CONFLUENCE_EMAIL,
    CONFLUENCE_API_TOKEN: process.env.CONFLUENCE_API_TOKEN,
    useForgeApi: ctx.kind === "forge",
  };
}

function isDemoId(id) {
  return !id || String(id).startsWith("demo");
}

function resolvePageId(payload, ctx) {
  if (!isDemoId(payload.pageId)) return String(payload.pageId);
  if (!isDemoId(ctx.pageId)) return String(ctx.pageId);
  if (process.env.CONFLUENCE_PAGE_ID) return String(process.env.CONFLUENCE_PAGE_ID);
  return payload.pageId || ctx.pageId || DEMO_PAGE_ID;
}

function resolveSpaceId(payload, ctx) {
  if (!isDemoId(payload.spaceId)) return String(payload.spaceId);
  if (!isDemoId(ctx.spaceId)) return String(ctx.spaceId);
  if (process.env.CONFLUENCE_SPACE_ID) return String(process.env.CONFLUENCE_SPACE_ID);
  return payload.spaceId || ctx.spaceId || DEMO_SPACE_ID;
}

function sessionKey(pageId) {
  return `conf-${pageId}`;
}

async function getContext(payload, ctx) {
  const env = envFrom(ctx);
  const pageId = resolvePageId(payload, ctx);
  const spaceId = resolveSpaceId(payload, ctx);

  if (env.useForgeApi && isDemoId(pageId) && !isDemoId(spaceId)) {
    const pages = await listSpacePages(env, spaceId);
    const first =
      pages.find((p) => /IT Change Policy/i.test(p.title || "")) ||
      pages.find((p) => !/^Overview$/i.test(p.title || "")) ||
      pages[0];
    if (first) return getContext({ ...payload, pageId: first.id, spaceId }, ctx);
    return {
      page: { id: null, title: "Space queue", version: 1, spaceId, demo: false },
      sections: [],
      review: { status: "draft" },
      hasSuperDocsKey: !!env.SUPERDOCS_API_KEY,
    };
  }

  const page = await getPage(env, pageId);
  const { sections } = listSections(page.adf);
  const review = await getReviewState(env, pageId, reviewMemory);
  return {
    page: {
      id: page.id,
      title: page.title,
      version: page.version?.number || 1,
      spaceId: page.spaceId || spaceId,
      demo: !!page.demo,
    },
    sections,
    review,
    hasSuperDocsKey: !!env.SUPERDOCS_API_KEY,
  };
}

async function loadPageHtml(payload, ctx) {
  const env = envFrom(ctx);
  const page = await getPage(env, resolvePageId(payload, ctx));
  const { start, end } = payload;
  if (start != null && end != null) {
    const sliced = sliceSectionHtml(page.adf, start, end);
    sessions.set(sessionKey(page.id), { adf: sliced.doc, page, range: { start, end } });
    return { html: sliced.html, title: page.title, version: page.version?.number || 1 };
  }
  const full = adfToHtml(page.adf);
  sessions.set(sessionKey(page.id), { adf: full.doc, page, range: null });
  return { html: full.html, title: page.title, version: page.version?.number || 1 };
}

async function startEdit(payload, ctx) {
  const env = envFrom(ctx);
  const page = await getPage(env, resolvePageId(payload, ctx));
  const review = await getReviewState(env, page.id, reviewMemory);
  if (review.status === "awaiting_approver" && payload.role !== "approver") {
    throw new Error("This page is waiting on the named approver. Publish is blocked.");
  }

  let html;
  let storedAdf;
  if (payload.start != null && payload.end != null) {
    const sliced = sliceSectionHtml(page.adf, payload.start, payload.end);
    html = sliced.html;
    storedAdf = sliced.doc;
  } else {
    const full = adfToHtml(page.adf);
    html = full.html;
    storedAdf = full.doc;
  }

  const sid = `${sessionKey(page.id)}-${Date.now()}`;
  const instruction = payload.house
    ? HOUSE_STRUCTURE_PROMPT
    : payload.message;
  if (!instruction || !String(instruction).trim()) {
    throw new Error("Write an instruction, or use house structure.");
  }

  const job = await startHitlEdit({
    apiKey: env.SUPERDOCS_API_KEY,
    sessionId: sid,
    documentHtml: html,
    message: String(instruction).trim(),
    modelTier: payload.modelTier || "core",
  });

  sessions.set(sid, {
    adf: ensureLocalIds(storedAdf),
    page,
    range: payload.start != null ? { start: payload.start, end: payload.end } : null,
    jobId: job.job_id,
    sessionId: sid,
    html,
  });

  return { jobId: job.job_id, sessionId: sid, status: job.status };
}

async function pollJob(payload, ctx) {
  const env = envFrom(ctx);
  const job = await getJob({ apiKey: env.SUPERDOCS_API_KEY, jobId: payload.jobId });
  if (job.status === "awaiting_approval" && job.metadata?.awaiting_kind === "continue_prompt") {
    return {
      status: job.status,
      awaitingKind: "continue_prompt",
      continuePrompt: job.metadata.continue_prompt,
      pendingChanges: [],
    };
  }
  return {
    status: job.status,
    awaitingKind: job.metadata?.awaiting_kind || (job.pending_changes?.length ? "hitl" : null),
    pendingChanges: job.pending_changes || [],
    error: job.error || null,
    result: job.status === "completed" ? job.result : null,
  };
}

async function decide(payload, ctx) {
  const env = envFrom(ctx);
  const sess = sessions.get(payload.sessionId);
  if (!sess) throw new Error("Session expired. Start the edit again.");

  const out = await approveChanges({
    apiKey: env.SUPERDOCS_API_KEY,
    sessionId: payload.sessionId,
    jobId: payload.jobId,
    decisions: payload.decisions,
  });

  sess.decisions = payload.decisions;
  sessions.set(payload.sessionId, sess);
  return out;
}

async function resumeLargeEdit(payload, ctx) {
  const env = envFrom(ctx);
  return continueJob({
    apiKey: env.SUPERDOCS_API_KEY,
    sessionId: payload.sessionId,
    jobId: payload.jobId,
    shouldContinue: payload.continue !== false,
  });
}

async function writeBack(payload, ctx) {
  const env = envFrom(ctx);
  const sess = sessions.get(payload.sessionId);
  if (!sess) throw new Error("Session expired. Start the edit again.");

  const review = await getReviewState(env, sess.page.id, reviewMemory);
  if (review.status === "awaiting_approver") {
    const actor = payload.actorAccountId || payload.role;
    if (review.approverAccountId && actor !== review.approverAccountId && payload.role !== "approver") {
      throw new Error("Named approver has not accepted yet. Write-back is blocked.");
    }
  }

  const accepted = (payload.decisions || sess.decisions || []).filter((d) => d.approved !== false);
  const nextAdf = applyAcceptedChanges(sess.adf, accepted.map((d) => ({
    ...d,
    operation: d.operation || "edit",
    chunk_id: d.chunk_id,
    new_html: d.new_html,
    insert_after_chunk_id: d.insert_after_chunk_id,
    approved: true,
  })));

  const updated = await updatePage(env, {
    pageId: sess.page.id,
    title: sess.page.title,
    adf: nextAdf,
    versionNumber: sess.page.version?.number || 1,
    message: "SuperDocs AI edit (single approved batch)",
  });

  await setReviewState(env, sess.page.id, { status: "approved", approvedAt: new Date().toISOString() }, reviewMemory);
  sess.adf = nextAdf;
  sess.page.version = updated.version;
  return {
    version: updated.version?.number || (sess.page.version?.number || 1) + 1,
    demo: !!updated.demo,
    title: sess.page.title,
  };
}

async function sendToApprover(payload, ctx) {
  const env = envFrom(ctx);
  const pageId = payload.pageId;
  const value = {
    status: "awaiting_approver",
    approverAccountId: payload.approverAccountId,
    approverName: payload.approverName || payload.approverAccountId,
    sessionId: payload.sessionId,
    jobId: payload.jobId,
    requestedAt: new Date().toISOString(),
  };
  await setReviewState(env, pageId, value, reviewMemory);
  return value;
}

async function listPages(payload, ctx) {
  const env = envFrom(ctx);
  const spaceId = resolveSpaceId(payload, ctx);
  const pages = await listSpacePages(env, spaceId);
  return { spaceId, pages };
}

async function findUsers(payload, ctx) {
  const env = envFrom(ctx);
  return { users: await searchUsers(env, payload.query || "") };
}

async function exportBrandedPdf(payload, ctx) {
  const env = envFrom(ctx);
  const sess = payload.sessionId ? sessions.get(payload.sessionId) : null;
  const page = await getPage(env, payload.pageId || sess?.page?.id || DEMO_PAGE_ID);
  const { html } = adfToHtml(sess?.adf || page.adf);
  const wrapped = `${LETTERHEAD}${html}`;
  return exportPdf({
    apiKey: env.SUPERDOCS_API_KEY,
    html: wrapped,
    filename: (page.title || "confluence-page").replace(/[^\w.-]+/g, "-").slice(0, 80),
  });
}

const handlers = {
  getContext,
  loadPageHtml,
  startEdit,
  pollJob,
  decide,
  resumeLargeEdit,
  writeBack,
  sendToApprover,
  listPages,
  findUsers,
  exportBrandedPdf,
};

module.exports = { handlers };
