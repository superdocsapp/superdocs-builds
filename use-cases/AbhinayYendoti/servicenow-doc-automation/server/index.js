/**
 * ServiceFlow Docs — workflow API.
 *
 * Three things this server is strict about:
 *
 *   1. The ServiceNow record is authoritative. Every decision is re-verified
 *      here against the record the session was opened with, never against
 *      values the browser sends back.
 *   2. SuperDocs failures surface as themselves. Nothing falls back to a
 *      locally generated document, because a fake document would prove nothing.
 *   3. The reviewer is a real gate. Export is refused until a human has signed
 *      off on a document that still matches ServiceNow.
 */

import "dotenv/config";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ConfigError, describeConfig, loadConfig } from "./config.js";
import { configureLogging, log } from "./log.js";
import { AppError, errors, toEnvelope } from "./errors.js";
import { RunStore } from "./runStore.js";
import { createChangeSource } from "./servicenow/source.js";
import { createMockServiceNowApi } from "./servicenow/mockApi.js";
import { ServiceNowError } from "./servicenow/client.js";
import { httpCompression, staticCacheHeaders } from "./httpCache.js";
import { singleFlight, staleWhileRevalidate } from "./cache.js";
import {
  buildEditInstruction,
  buildWriteBackNote,
  createFilename,
  documentChecksum,
  mapChangeToSections,
  renderSourceDocument,
  sourceFilename,
  validateChange,
  verifyPreservedValues,
  verifyProposedChange
} from "./documentMapping.js";
import {
  SuperDocsError,
  approveChange,
  approveChanges,
  configureSuperDocs,
  continueJob,
  exportDocument,
  getJob,
  health,
  reEditChunk,
  requestEdit,
  streamChat,
  superDocsConfig,
  uploadDocument,
  whoami
} from "./superdocs.js";
import { describeJob } from "./workflow.js";

let config;
try {
  config = loadConfig();
} catch (error) {
  if (error instanceof ConfigError) {
    console.error(error.message);
    process.exit(1);
  }
  throw error;
}

configureLogging({ level: config.logLevel, env: config.env });
configureSuperDocs(config.superDocs);

const app = express();
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");

const changeSource = createChangeSource(config);
const runs = new RunStore({
  ttlMs: config.runTtlMs,
  limit: config.runLimit,
  statePath: config.runStatePath
});

app.disable("x-powered-by");
app.use(httpCompression());
app.use(express.json({ limit: "2mb" }));

/* ---------------------------------------------------------------- plumbing */

/** Every request gets an id, and it travels back in the error envelope. */
app.use((request, response, next) => {
  request.id = `req_${crypto.randomUUID().slice(0, 8)}`;
  request.log = log.child({ requestId: request.id });
  response.set("X-Request-Id", request.id);

  const startedAt = Date.now();
  response.on("finish", () => {
    if (request.path.startsWith("/api/")) {
      request.log.info("request", {
        method: request.method,
        path: request.path,
        status: response.statusCode,
        ms: Date.now() - startedAt
      });
    }
  });

  next();
});

/**
 * A small token bucket per client on mutating routes. SuperDocs operations are
 * metered and billable; an accidental retry loop in a browser tab should not be
 * able to spend the month's quota.
 */
const buckets = new Map();

function rateLimit({ capacity, refillPerSecond }) {
  return (request, response, next) => {
    const key = `${request.ip}:${request.path}`;
    const now = Date.now();
    const bucket = buckets.get(key) ?? { tokens: capacity, at: now };

    bucket.tokens = Math.min(capacity, bucket.tokens + ((now - bucket.at) / 1000) * refillPerSecond);
    bucket.at = now;

    if (bucket.tokens < 1) {
      buckets.set(key, bucket);
      next(errors.rateLimited("Too many requests. Give it a moment and try again."));
      return;
    }

    bucket.tokens -= 1;
    buckets.set(key, bucket);
    next();
  };
}

/** Async handlers, without a try/catch in every route. */
const route = (handler) => (request, response, next) =>
  Promise.resolve(handler(request, response, next)).catch(next);

function requireRun(request) {
  const sessionId = String(request.body?.sessionId ?? request.query?.sessionId ?? "");
  if (!sessionId) throw errors.invalid("A session id is required.");

  const run = runs.get(sessionId);
  if (!run) throw errors.gone("That document session is no longer active.");

  return run;
}

/* ------------------------------------------------- the mock ServiceNow tenant */

/**
 * Mounted only when ServiceNow is in mock mode. It is a real Table API, and the
 * app reaches it over HTTP through the same client that would talk to a live
 * instance — see servicenow/mockApi.js for why that matters.
 */
if (config.serviceNow.mode === "mock") {
  app.use(
    "/mock/servicenow",
    createMockServiceNowApi({
      username: config.serviceNow.username,
      password: config.serviceNow.password,
      latencyMs: config.serviceNow.latencyMs,
      failureRate: config.serviceNow.failureRate,
      instanceUrl: config.serviceNow.instanceUrl
    })
  );
}

/* -------------------------------------------------------------- health/quota */

/**
 * Upstream reads the UI depends on but must never wait on.
 *
 * Health and quota are read on every page load, change rarely, and each costs a
 * ~1s round trip; jobs are read constantly by several watchers at once. See
 * cache.js for the two shapes that fixes.
 */
const readUpstreamHealth = staleWhileRevalidate({
  ttlMs: config.healthCacheMs,
  onError: (error) => log.warn("could not refresh health", { detail: String(error.message ?? error) }),
  load: async () => {
    if (!superDocsConfig().configured && !superDocsConfig().replaying) return null;

    try {
      return await health();
    } catch (error) {
      return { status: "unreachable", detail: String(error.message ?? error) };
    }
  }
});

const readQuota = staleWhileRevalidate({
  ttlMs: config.quotaCacheMs,
  onError: (error) => log.warn("could not read SuperDocs quota", { detail: String(error.message ?? error) }),
  load: async () => {
    if (!superDocsConfig().configured) return null;

    const account = await whoami();
    return {
      tier: account?.tier ?? null,
      used: account?.quota?.used ?? null,
      remaining: account?.quota?.remaining ?? null,
      limit: account?.quota?.monthly_limit ?? null,
      resetsAt: account?.quota?.resets_at ?? null
    };
  }
});

/**
 * Is ServiceNow answering?
 *
 * Probed rather than assumed, so the status the reviewer sees means something.
 * A cheap single-row query against the same client the workflow uses — if this
 * succeeds, the queue will load.
 */
const readServiceNowStatus = staleWhileRevalidate({
  ttlMs: config.healthCacheMs,
  onError: (error) => log.warn("ServiceNow probe failed", { detail: String(error.message ?? error) }),
  load: async () => {
    try {
      await changeSource.listChanges({ limit: 1 });
      return { connected: true };
    } catch (error) {
      return { connected: false, detail: String(error.message ?? error) };
    }
  }
});

/** One upstream read per job, however many watchers want it at that moment. */
const jobReads = singleFlight();
const readJob = (jobId) => jobReads(jobId, () => getJob(jobId));

/** A run that dies halfway through for quota is worse than one that never started. */
async function assertQuota() {
  const quota = await readQuota();
  if (quota && typeof quota.remaining === "number" && quota.remaining <= 0) {
    throw errors.quota(
      "This SuperDocs account has no operations left this month, so the run was not started.",
      quota
    );
  }
  return quota;
}

app.get(
  "/api/health",
  route(async (_request, response) => {
    const superDocs = superDocsConfig();
    const [upstream, quota, serviceNow] = await Promise.all([
      readUpstreamHealth(),
      readQuota(),
      readServiceNowStatus()
    ]);

    // Deliberately narrow. This is reached by every browser tab, so it reports
    // whether the systems are answering and nothing about how they are wired —
    // no base URLs, no instance addresses, no deployment topology. Operators
    // get that from the boot log, which is not public.
    response.json({
      ok: true,
      serviceNow: {
        connected: Boolean(serviceNow?.connected),
        writeBack: config.writeBack
      },
      superDocs: {
        connected: Boolean(
          (superDocs.configured || superDocs.replaying) && upstream?.status === "healthy"
        ),
        // Kept: a replayed run must never be presentable as a live one.
        replaying: superDocs.replaying,
        quota
      },
      runs: runs.size
    });
  })
);

/* -------------------------------------------------------------- the queue */

app.get(
  "/api/changes",
  route(async (_request, response) => {
    const changes = await changeSource.listChanges();

    response.json({
      changes: changes.map((change) => ({ ...change, validation: validateChange(change) }))
    });
  })
);

/* ------------------------------------------------------- step 1: upload */

app.post(
  "/api/documents/upload",
  rateLimit({ capacity: 6, refillPerSecond: 0.2 }),
  route(async (request, response) => {
    const number = String(request.body?.number ?? "");
    if (!number) throw errors.invalid("A change number is required.");

    const change = await changeSource.getChange(number);
    if (!change) throw errors.notFound(`Change ${number} was not found in ServiceNow.`);

    const validation = validateChange(change);
    if (!validation.ok) {
      throw errors.invalid("This change is missing information required for the document.", {
        validation
      });
    }

    const quota = await assertQuota();

    // SuperDocs constrains session ids to [A-Za-z0-9_.-].
    const sessionId = `svcflow-${change.number.toLowerCase()}-${Date.now().toString(36)}`;
    const uploaded = await uploadDocument({
      sessionId,
      filename: sourceFilename(change),
      content: renderSourceDocument(change)
    });

    const run = runs.create(sessionId, {
      change,
      sourceHtml: uploaded?.html ?? null,
      filename: createFilename(change),
      chunksCount: uploaded?.chunks_count ?? null,
      versionId: uploaded?.version_id ?? null
    });

    runs.record(run, "uploaded", {
      change: change.number,
      filename: sourceFilename(change),
      chunks: run.chunksCount
    });

    response.json({
      sessionId,
      change,
      sections: mapChangeToSections(change),
      filename: run.filename,
      sourceHtml: run.sourceHtml,
      versionId: run.versionId,
      chunksCount: run.chunksCount,
      quota
    });
  })
);

/* --------------------------------------------------------- step 2: edit */

app.post(
  "/api/documents/edit",
  rateLimit({ capacity: 6, refillPerSecond: 0.2 }),
  route(async (request, response) => {
    const run = requireRun(request);
    await assertQuota();

    const job = await requestEdit({
      sessionId: run.sessionId,
      message: buildEditInstruction(run.change),
      documentHtml: run.sourceHtml ?? undefined,
      modelTier: request.body?.modelTier,
      thinkingDepth: request.body?.thinkingDepth
    });

    runs.update(run, (draft) => {
      draft.jobId = job.job_id;
      // The source document has been handed to SuperDocs, which holds it for
      // the rest of the session, and the browser already has its own copy for
      // the preview. Keeping a second copy here only makes every subsequent
      // persist of this run larger.
      draft.sourceHtml = null;
    });
    runs.record(run, "edit_started", { jobId: job.job_id });

    response.json({ jobId: job.job_id, status: job.status });
  })
);

/* ----------------------------------------------- step 2b: job state (poll) */

app.get(
  "/api/documents/job/:jobId",
  route(async (request, response) => {
    const run = requireRun(request);
    const job = await readJob(request.params.jobId);

    const state = describeJob(run, job);
    runs.update(run, () => {});

    response.json(state);
  })
);

/* --------------------------------------------- step 2c: job state (stream) */

/**
 * One SSE connection carrying the whole run.
 *
 * SuperDocs streams its own progress events; those are forwarded as `activity`
 * so the reviewer can watch the model work. Whenever something structural
 * happens the job is re-read and the full derived state goes out as `state`, so
 * the client never has to merge partial updates. A slow poll runs inside the
 * same connection as a safety net, because a dropped stream must not strand a
 * review.
 */
app.get(
  "/api/documents/stream",
  route(async (request, response) => {
    const run = requireRun(request);
    const jobId = String(request.query.jobId ?? run.jobId ?? "");
    if (!jobId) throw errors.invalid("A job id is required.");

    // setHeader rather than writeHead: headers passed to writeHead are not
    // readable via getHeader, and the compression middleware has to be able to
    // see this content type to leave the stream alone. A gzipped event stream
    // buffers, and a buffered event stream is not an event stream.
    response.setHeader("Content-Type", "text/event-stream");
    response.setHeader("Cache-Control", "no-cache, no-transform");
    response.setHeader("Connection", "keep-alive");
    response.setHeader("X-Accel-Buffering", "no");
    response.flushHeaders();

    const controller = new AbortController();
    let closed = false;

    const send = (event, data) => {
      if (closed) return;
      response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    };

    const pushState = async () => {
      try {
        const state = describeJob(run, await readJob(jobId));
        runs.update(run, () => {});
        send("state", state);
        return state;
      } catch (error) {
        send("error", { message: String(error.message ?? error) });
        return null;
      }
    };

    const cleanup = () => {
      closed = true;
      controller.abort();
      clearInterval(heartbeat);
      clearInterval(safetyPoll);
    };

    request.on("close", cleanup);

    const heartbeat = setInterval(() => {
      if (!closed) response.write(": keep-alive\n\n");
    }, 15_000);

    const safetyPoll = setInterval(() => {
      pushState();
    }, 5_000);

    const initial = await pushState();
    if (initial?.finished) {
      cleanup();
      response.end();
      return;
    }

    try {
      for await (const event of streamChat({ sessionId: run.sessionId, jobId, signal: controller.signal })) {
        if (closed) break;

        if (event.event === "intermediate") {
          send("activity", {
            type: event.data?.type ?? "progress",
            content: event.data?.content ?? "",
            at: event.data?.timestamp ?? new Date().toISOString()
          });
          continue;
        }

        // Anything structural: re-read the job so the client gets one coherent
        // state rather than a partial event it has to reconcile.
        const state = await pushState();
        if (state?.finished) break;
      }
    } catch (error) {
      if (!closed) {
        request.log.warn("superdocs stream ended", { detail: String(error.message ?? error) });
        send("degraded", { message: "Live progress dropped. Falling back to polling." });
      }
    }

    if (!closed) {
      await pushState();
      cleanup();
      response.end();
    }
  })
);

/* ------------------------------------------------- step 3: per-change decisions */

/**
 * Approving a change that rewrites a ServiceNow-owned value is refused here,
 * not merely discouraged in the UI. The proposal is re-read from the server's
 * own copy, so a client cannot get a change approved by sending a friendlier
 * version of it.
 */
function decisionFor(run, changeId, approved) {
  const proposal = run.proposals?.[changeId];
  if (!proposal) throw errors.notFound("That proposed change is not part of this session.");

  const verification = verifyProposedChange(run.change, proposal);

  if (approved && verification.verdict === "blocked") {
    throw errors.conflict(
      "This change rewrites a value that ServiceNow owns, so it cannot be approved.",
      { verification }
    );
  }

  return { proposal, verification };
}

/** Rejections travel back to SuperDocs with the reason, so the retry is informed. */
function defaultFeedback(verification, approved) {
  if (approved || !verification.findings.length) return undefined;
  return verification.findings.map((finding) => finding.reason).join(" ");
}

app.post(
  "/api/documents/decide",
  rateLimit({ capacity: 30, refillPerSecond: 2 }),
  route(async (request, response) => {
    const run = requireRun(request);
    const changeId = String(request.body?.changeId ?? "");
    const approved = request.body?.approved === true;

    const { verification } = decisionFor(run, changeId, approved);

    const result = await approveChange({
      sessionId: run.sessionId,
      jobId: request.body?.jobId ?? run.jobId,
      changeId,
      approved,
      feedback: request.body?.feedback ?? defaultFeedback(verification, approved)
    });

    runs.update(run, (draft) => {
      draft.decisions[changeId] = approved;
    });
    runs.record(run, approved ? "change_approved" : "change_rejected", {
      changeId,
      verdict: verification.verdict
    });

    response.json({
      changeId,
      approved,
      batchComplete: result?.batch_complete ?? false,
      verification
    });
  })
);

/**
 * Batch decisions in one round trip. Twelve changes were twelve HTTP calls that
 * could fail halfway and leave the job half-decided; the API takes them
 * together, so they land together.
 */
app.post(
  "/api/documents/decide-batch",
  rateLimit({ capacity: 10, refillPerSecond: 0.5 }),
  route(async (request, response) => {
    const run = requireRun(request);
    const requested = Array.isArray(request.body?.decisions) ? request.body.decisions : [];

    if (!requested.length) throw errors.invalid("No decisions were sent.");

    const changes = requested.map((entry) => {
      const changeId = String(entry?.changeId ?? "");
      const approved = entry?.approved === true;
      const { verification } = decisionFor(run, changeId, approved);

      return { changeId, approved, feedback: defaultFeedback(verification, approved), verification };
    });

    const result = await approveChanges({
      sessionId: run.sessionId,
      jobId: request.body?.jobId ?? run.jobId,
      changes
    });

    runs.update(run, (draft) => {
      for (const change of changes) draft.decisions[change.changeId] = change.approved;
    });
    runs.record(run, "batch_decided", {
      approved: changes.filter((change) => change.approved).length,
      rejected: changes.filter((change) => !change.approved).length
    });

    response.json({
      decided: changes.map(({ changeId, approved, verification }) => ({
        changeId,
        approved,
        verification
      })),
      batchComplete: result?.batch_complete ?? false
    });
  })
);

/**
 * The other kind of pause. A large edit stops to ask whether to keep going, and
 * it reports the same status as a change batch — resolving it through the
 * approve endpoint does nothing and the job waits forever.
 */
app.post(
  "/api/documents/continue",
  rateLimit({ capacity: 10, refillPerSecond: 0.5 }),
  route(async (request, response) => {
    const run = requireRun(request);
    const keepGoing = request.body?.keepGoing !== false;

    const result = await continueJob({
      sessionId: run.sessionId,
      jobId: request.body?.jobId ?? run.jobId,
      keepGoing
    });

    runs.record(run, keepGoing ? "continue_resumed" : "continue_stopped", {});
    response.json({ keepGoing, status: result?.status ?? null });
  })
);

/**
 * Reject, then ask SuperDocs to redo that one section with the reason. The
 * reviewer is not left choosing between a wrong edit and no edit.
 *
 * Bills one SuperDocs operation.
 */
app.post(
  "/api/documents/reedit",
  rateLimit({ capacity: 10, refillPerSecond: 0.2 }),
  route(async (request, response) => {
    const run = requireRun(request);
    await assertQuota();

    const changeId = String(request.body?.changeId ?? "");
    const proposal = run.proposals?.[changeId];
    if (!proposal) throw errors.notFound("That proposed change is not part of this session.");

    const chunkId = proposal.chunk_id;
    if (!chunkId) {
      throw errors.conflict("SuperDocs did not attach this change to a section, so it cannot be re-edited.");
    }

    const verification = verifyProposedChange(run.change, proposal);
    const guidance = [
      request.body?.feedback,
      ...verification.findings.map((finding) => finding.reason)
    ]
      .filter(Boolean)
      .join(" ");

    const result = await reEditChunk({
      sessionId: run.sessionId,
      chunkId,
      currentHtml: proposal.old_html ?? "",
      originalHtml: proposal.old_html ?? "",
      proposedHtml: proposal.new_html ?? "",
      explanation: guidance || proposal.ai_explanation || undefined
    });

    runs.record(run, "chunk_reedited", { changeId, chunkId });

    response.json({
      chunkId: result?.chunk_id ?? chunkId,
      html: result?.new_html ?? null,
      error: result?.error ?? null
    });
  })
);

/* ------------------------------------------------ step 3b: reviewer sign-off */

/**
 * SuperDocs does not always ask for per-change decisions: when the model
 * rewrites the document in one pass it applies the result itself and the
 * approve endpoint never fires. The human gate therefore lives here too —
 * nothing exports until a reviewer signs off on a finished document that still
 * matches the ServiceNow record.
 */
app.post(
  "/api/documents/approve",
  rateLimit({ capacity: 10, refillPerSecond: 0.5 }),
  route(async (request, response) => {
    const run = requireRun(request);

    if (!run.completed) throw errors.conflict("The SuperDocs edit is not finished yet.");

    const verification = verifyPreservedValues(run.change, run.finalHtml ?? "");

    runs.update(run, (draft) => {
      draft.finalVerification = verification;
    });

    if (!verification.ok) {
      runs.record(run, "approval_refused", {
        failed: verification.checks.filter((check) => !check.found).map((check) => check.field)
      });
      throw errors.conflict(
        "The document no longer matches the ServiceNow record, so it cannot be approved.",
        { verification }
      );
    }

    const reviewer = String(request.body?.reviewer ?? "").trim() || null;
    const approvedAt = new Date().toISOString();

    runs.update(run, (draft) => {
      draft.approved = true;
      draft.approvedAt = approvedAt;
      draft.reviewer = reviewer;
      draft.checksum = documentChecksum(run.finalHtml);
    });
    runs.record(run, "document_approved", { reviewer, checksum: run.checksum });

    response.json({ approved: true, approvedAt, reviewer, checksum: run.checksum, verification });
  })
);

/* ------------------------------------------------------------ step 4: export */

app.post(
  "/api/documents/export",
  rateLimit({ capacity: 10, refillPerSecond: 0.2 }),
  route(async (request, response) => {
    const run = requireRun(request);

    if (!run.completed) throw errors.conflict("The SuperDocs edit is not finished yet.");
    if (!run.approved) throw errors.conflict("Approve the document before exporting it.");

    // Re-verified at the last possible moment: approval was a point in time,
    // and the document may have moved since.
    const verification = verifyPreservedValues(run.change, run.finalHtml ?? "");
    if (!verification.ok) {
      runs.record(run, "export_refused", {});
      throw errors.conflict(
        "The finished document no longer matches the ServiceNow record, so it cannot be exported.",
        { verification }
      );
    }

    const format = String(request.body?.format ?? "docx");
    const filename = createFilename(run.change).replace(/\.docx$/u, `.${format}`);

    const { bytes, contentType } = await exportDocument({
      sessionId: run.sessionId,
      format,
      filename,
      sourceFilename: sourceFilename(run.change)
    });

    runs.update(run, (draft) => {
      draft.exportedAt = new Date().toISOString();
    });
    runs.record(run, "exported", { filename, bytes: bytes.length, format });

    // Write-back is best-effort and deliberately after the bytes are in hand:
    // a ServiceNow outage must not cost the reviewer a document they approved.
    void writeBackToServiceNow(run, filename).catch((error) => {
      log.warn("write-back failed", { sessionId: run.sessionId, detail: String(error.message ?? error) });
    });

    response
      .status(200)
      .set({
        "Content-Type": contentType ?? contentTypeFor(format),
        "Content-Disposition": `attachment; filename="${filename}"`,
        "X-SuperDocs-Session": run.sessionId,
        "X-Document-Checksum": run.checksum ?? ""
      })
      .send(bytes);
  })
);

/**
 * Close the loop. ServiceNow is the system of record, so the change gets a
 * journal entry naming the document, its checksum and who approved it — the
 * same PATCH that would run against a live tenant.
 */
async function writeBackToServiceNow(run, filename) {
  if (!config.writeBack) return;

  const note = buildWriteBackNote({
    change: run.change,
    filename,
    checksum: run.checksum ?? documentChecksum(run.finalHtml),
    sessionId: run.sessionId,
    approvedAt: run.approvedAt,
    reviewer: run.reviewer
  });

  try {
    await changeSource.recordDocument(run.change.id, note);
    runs.update(run, (draft) => {
      draft.writeBack = { ok: true, at: new Date().toISOString() };
    });
    runs.record(run, "servicenow_updated", { record: run.change.number });
  } catch (error) {
    runs.update(run, (draft) => {
      draft.writeBack = { ok: false, at: new Date().toISOString(), detail: String(error.message ?? error) };
    });
    runs.record(run, "servicenow_update_failed", { detail: String(error.message ?? error) });
    throw error;
  }
}

/* ------------------------------------------------------------- audit trail */

app.get(
  "/api/runs/:sessionId/audit",
  route(async (request, response) => {
    const run = runs.get(request.params.sessionId);
    if (!run) throw errors.gone("That document session is no longer active.");

    response.json({
      sessionId: run.sessionId,
      change: run.change?.number ?? null,
      createdAt: new Date(run.createdAt).toISOString(),
      approvedAt: run.approvedAt ?? null,
      exportedAt: run.exportedAt ?? null,
      checksum: run.checksum ?? null,
      writeBack: run.writeBack ?? null,
      events: run.audit
    });
  })
);

/* ------------------------------------------------------------ static + errors */

app.use(
  express.static(path.join(projectRoot, "dist"), {
    // Fingerprinted assets never change under their URL; index.html always must.
    setHeaders: staticCacheHeaders,
    maxAge: 0
  })
);

/** SPA fallback. Express 5 has no bare "*" route, so this runs as a handler. */
app.use((request, response, next) => {
  if (request.method !== "GET" || request.path.startsWith("/api/")) {
    next();
    return;
  }
  response.sendFile(path.join(projectRoot, "dist", "index.html"));
});

/** One error shape for every failure, upstream ones translated on the way out. */
app.use((error, request, response, _next) => {
  let translated = error;

  if (error instanceof SuperDocsError) {
    translated = errors.upstream("SuperDocs could not complete this step.", error.message, {
      upstreamStatus: error.status || null
    });
    request.log?.error("superdocs failure", { status: error.status, detail: error.message, body: error.body });
  } else if (error instanceof ServiceNowError) {
    translated = errors.upstream("ServiceNow could not complete this step.", error.detail ?? error.message, {
      upstreamStatus: error.status || null
    });
    request.log?.error("servicenow failure", { status: error.status, detail: error.message });
  } else if (error?.type === "entity.parse.failed") {
    // body-parser throws a SyntaxError for a malformed JSON body. Left alone it
    // falls through to the 500 branch below, which tells the caller the server
    // broke when in fact their payload did.
    translated = errors.invalid("The request body is not valid JSON.");
  } else if (error?.type === "entity.too.large") {
    translated = errors.invalid("The request body is larger than this API accepts.");
  } else if (!(error instanceof AppError)) {
    request.log?.error("unhandled failure", { detail: String(error?.stack ?? error) });
  }

  const { status, body } = toEnvelope(translated, request.id);

  if (response.headersSent) {
    response.end();
    return;
  }

  response.status(status).json(body);
});

/* -------------------------------------------------------------------- boot */

const sweeper = setInterval(() => runs.sweep(), 5 * 60 * 1000);
sweeper.unref();

const server = app.listen(config.port, () => {
  log.info("ServiceFlow Docs server listening", describeConfig(config));
  log.info(`  UI/API   http://127.0.0.1:${config.port}`);
  log.info(`  ServiceNow  ${config.serviceNow.mode} (${config.serviceNow.instanceUrl})`);
  log.info(
    `  SuperDocs   ${
      config.superDocs.configured ? config.superDocs.baseUrl : "NOT CONFIGURED - set SUPERDOCS_API_KEY"
    }${config.superDocs.replayMode !== "off" ? ` [${config.superDocs.replayMode}]` : ""}`
  );

  // Prime the upstream caches now rather than on the first page load, so the
  // reviewer never waits on a probe that could have run while the port opened.
  Promise.all([readUpstreamHealth.prime(), readQuota.prime(), readServiceNowStatus.prime()]).then(
    () => log.debug("upstream caches primed"),
    () => {}
  );
});

/** Flush run state before exiting, or a deploy strands every open review. */
function shutdown(signal) {
  log.info("shutting down", { signal });
  clearInterval(sweeper);
  runs.flush();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 5000).unref();
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

function contentTypeFor(format) {
  switch (format) {
    case "docx":
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    case "pdf":
      return "application/pdf";
    case "html":
      return "text/html; charset=utf-8";
    case "markdown":
      return "text/markdown; charset=utf-8";
    default:
      return "text/plain; charset=utf-8";
  }
}
