import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { resolve } from "node:path";
import {
  parseProposedChanges,
  traceNarrative,
  verifyAuthorities,
  type Proposal,
} from "../src/domain";
import { renderReviewedExports } from "../src/export-renderer";
import { scenario } from "../src/scenario";
import { FakeSuperDocsClient } from "../src/superdocs";
import { RealSuperDocsClient } from "./superdocs-real";

for (const path of [resolve(import.meta.dirname, "../.env")]) {
  try {
    for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
      const match = line.match(
        /^\s*(SUPERDOCS_(?:API_KEY|BASE_URL|MODE)|RUN_SUPERDOCS_LIVE_TESTS)\s*=\s*(.*)\s*$/,
      );
      if (match && !process.env[match[1]])
        process.env[match[1]] = match[2].replace(/^['"]|['"]$/g, "");
    }
  } catch {
    /* optional */
  }
}

const port = Number(process.env.PORT ?? 4174);
const mode = process.env.SUPERDOCS_MODE === "real" ? "real" : "fake";
const liveConfigured =
  mode !== "real" ||
  Boolean(
    process.env.SUPERDOCS_API_KEY &&
    !/placeholder|your[_-]?key|changeme/i.test(process.env.SUPERDOCS_API_KEY),
  );
const real =
  mode === "real" && liveConfigured
    ? new RealSuperDocsClient(
        process.env.SUPERDOCS_API_KEY!,
        process.env.SUPERDOCS_BASE_URL ?? "https://api.superdocs.app",
      )
    : null;
const fake = new FakeSuperDocsClient();
const authorities = verifyAuthorities(scenario.authorities);
const validAuthorities = authorities.filter(
  (item) => item.verification_status === "VERIFIED",
);
const rejectedAuthorities = authorities.filter(
  (item) => item.verification_status !== "VERIFIED",
);
const sections = {
  Analysis:
    "INR 6500000.00 less INR 4800000.00, INR 200000.00 and INR 300000.00 equals INR 1200000.00.",
  Conclusion:
    "The taxable amount is INR 1200000.00 on the supplied synthetic record.",
};
const escaped = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ]!,
  );

type CaseState = {
  id: string;
  sessionId: string;
  documentIds: string[];
  jobId?: string;
  jobStatus: string;
  proposals: Proposal[];
  negativeCleared: boolean;
  approvalFingerprint?: string;
  generationPromise?: Promise<void>;
  approvalPromise?: Promise<void>;
  startedAt: number;
  jobStartedAt?: number;
  approvedAt?: number;
};
const cases = new Map<string, CaseState>();
const documents = [
  {
    name: "synthetic-client-facts.txt",
    content: [...scenario.facts, scenario.question].join("\n"),
  },
  ...validAuthorities.map((item, index) => ({
    name: `synthetic-authority-${index + 1}.txt`,
    content: item.attachment_text,
  })),
];
const authorityHtml = validAuthorities
  .map(
    (item) =>
      `<p>${escaped(item.citation)}: “${escaped(item.exact_quote)}” (${escaped(item.source_locator)})</p>`,
  )
  .join("");
const draftHtml = `<h1>Tax Technical Memorandum</h1><h2>Facts</h2>${scenario.facts.map((item) => `<p>${escaped(item)}</p>`).join("")}<h2>Question presented</h2><p>${escaped(scenario.question)}</p><h2>Authorities</h2>${authorityHtml}<h2>Analysis</h2><p>${sections.Analysis}</p><h2>Conclusion</h2><p>${sections.Conclusion}</p><h2>Confidence level</h2><p>Moderate</p>`;
documents.push({ name: "synthetic-tax-memo.html", content: draftHtml });

const readJson = async (request: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}") as Record<
    string,
    unknown
  >;
};
const json = (response: ServerResponse, status: number, body: unknown) => {
  response.writeHead(status, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(body));
};
const safeCase = (state: CaseState) => ({
  caseId: state.id,
  mode: mode === "real" ? "Live" : "Offline demo",
  documents: documents.map((document, index) => ({
    name: document.name,
    status: state.documentIds[index] ? "UPLOADED" : "PENDING",
    documentId: state.documentIds[index]
      ? `...${state.documentIds[index].slice(-8)}`
      : undefined,
  })),
  jobStatus: state.jobStatus,
  jobDurationMs: state.jobStartedAt
    ? (state.approvedAt ?? Date.now()) - state.jobStartedAt
    : 0,
  proposals: state.proposals,
  authorities: authorities.map((item) => ({
    title: item.title,
    citation: item.citation,
    exactQuote: item.exact_quote,
    status: item.verification_status,
  })),
  numeric: traceNarrative(
    state.negativeCleared
      ? sections
      : { ...sections, NegativeControl: "INR 999999.00" },
    scenario.rows,
  ),
  negativeCleared: state.negativeCleared,
  mandatoryPending: state.proposals.filter(
    (item) => item.decision === "PENDING",
  ).length,
  approved: Boolean(state.approvedAt),
});
const getCase = (url: URL) => cases.get(url.pathname.split("/")[4]);
const requireConfigured = (response: ServerResponse) => {
  if (liveConfigured) return true;
  json(response, 503, {
    code: "LIVE_CONFIGURATION_MISSING",
    message:
      "Live SuperDocs mode is selected, but the server credential is unavailable.",
  });
  return false;
};

createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", "http://localhost");
    if (request.method === "GET" && url.pathname === "/api/superdocs/config")
      return json(response, 200, {
        mode: mode === "real" ? "Live" : "Offline demo",
        configured: liveConfigured,
        error: liveConfigured
          ? undefined
          : {
              code: "LIVE_CONFIGURATION_MISSING",
              message:
                "Live SuperDocs mode is selected, but the server credential is unavailable.",
            },
      });
    if (request.method === "POST" && url.pathname === "/api/superdocs/cases") {
      if (!requireConfigured(response)) return;
      const state: CaseState = {
        id: crypto.randomUUID(),
        sessionId: `tax-ui-${crypto.randomUUID()}`,
        documentIds: [],
        jobStatus: "ready",
        proposals: [],
        negativeCleared: false,
        startedAt: Date.now(),
      };
      cases.set(state.id, state);
      return json(response, 200, safeCase(state));
    }
    const state = getCase(url);
    if (!state)
      return json(response, 404, {
        code: "CASE_NOT_FOUND",
        message: "The workflow case was not found.",
      });
    if (!requireConfigured(response)) return;
    if (request.method === "POST" && url.pathname.endsWith("/documents")) {
      if (state.jobId)
        return json(response, 409, {
          code: "UPLOAD_CLOSED",
          message: "Documents cannot be changed after generation starts.",
        });
      const body = await readJson(request);
      const name = typeof body.name === "string" ? body.name : "";
      const content = typeof body.content === "string" ? body.content : "";
      const expected = documents[state.documentIds.length];
      if (!expected || name !== expected.name || !content.trim())
        return json(response, 422, {
          code: "INVALID_SYNTHETIC_DOCUMENT",
          message:
            "Select the four supplied synthetic documents in their displayed order.",
        });
      const uploaded = real
        ? await real.upload(name, content, state.sessionId)
        : await fake.upload(name, content);
      state.documentIds.push(uploaded.documentId);
      return json(response, 200, safeCase(state));
    }
    if (request.method === "POST" && url.pathname.endsWith("/generate")) {
      if (state.documentIds.length !== documents.length)
        return json(response, 409, {
          code: "DOCUMENTS_REQUIRED",
          message: "Upload all four synthetic documents before generation.",
        });
      if (!state.jobId && !state.generationPromise)
        state.generationPromise = (async () => {
          const job = real
            ? await real.instruction(
                state.sessionId,
                "Review this fictional tax memorandum. Propose separate minimal edits to Analysis and Conclusion only. Preserve every supplied number and authority quotation. Do not introduce unsupported content.",
              )
            : await fake.instruction(state.sessionId, "draft");
          state.jobId = job.jobId;
          state.jobStatus = job.status;
          state.jobStartedAt = Date.now();
          if (!real) {
            const result = await fake.poll(state.jobId);
            state.jobStatus = result.status;
            state.proposals = parseProposedChanges(result.proposedChanges, {
              sessionId: state.sessionId,
            });
          }
        })().finally(() => {
          state.generationPromise = undefined;
        });
      if (state.generationPromise) await state.generationPromise;
      return json(response, 200, safeCase(state));
    }
    if (request.method === "GET" && url.pathname.endsWith("/status")) {
      if (!state.jobId)
        return json(response, 409, {
          code: "JOB_NOT_STARTED",
          message: "Generation has not started.",
        });
      if (
        !["awaiting_approval", "completed", "failed", "cancelled"].includes(
          state.jobStatus,
        )
      ) {
        const job = real
          ? await real.poll(state.jobId)
          : await fake.poll(state.jobId);
        state.jobStatus = job.status;
        if (job.proposedChanges && !state.proposals.length)
          state.proposals = parseProposedChanges(job.proposedChanges, {
            sessionId: state.sessionId,
          });
      }
      return json(response, 200, safeCase(state));
    }
    if (
      request.method === "POST" &&
      url.pathname.endsWith("/clear-negative-controls")
    ) {
      state.negativeCleared = true;
      return json(response, 200, safeCase(state));
    }
    if (request.method === "POST" && url.pathname.endsWith("/approve")) {
      const body = await readJson(request);
      const decisions = body.proposals as Proposal[];
      if (!Array.isArray(decisions))
        return json(response, 422, {
          code: "INVALID_DECISIONS",
          message: "Review decisions are required.",
        });
      state.proposals = state.proposals.map(
        (proposal) =>
          decisions.find((item) => item.id === proposal.id) ?? proposal,
      );
      if (
        !state.negativeCleared ||
        state.proposals.some((item) => item.decision === "PENDING")
      )
        return json(response, 409, {
          code: "REVIEW_BLOCKED",
          message:
            "Clear every blocker and mandatory decision before approval.",
        });
      const fingerprint = createHash("sha256")
        .update(
          JSON.stringify(
            state.proposals.map(({ id, decision, reviewerNote }) => ({
              id,
              decision,
              reviewerNote,
            })),
          ),
        )
        .digest("hex");
      if (state.approvalFingerprint === fingerprint || state.approvalPromise) {
        if (state.approvalPromise) await state.approvalPromise;
        return json(response, 200, {
          ...safeCase(state),
          duplicateSuppressed: true,
        });
      }
      state.approvalFingerprint = fingerprint;
      state.approvalPromise = (
        real
          ? real.approve(state.sessionId, state.jobId!, state.proposals)
          : fake.approve(state.sessionId, state.jobId!, state.proposals)
      )
        .then(() => {
          state.approvedAt = Date.now();
        })
        .catch((error) => {
          state.approvalFingerprint = undefined;
          throw error;
        })
        .finally(() => {
          state.approvalPromise = undefined;
        });
      await state.approvalPromise;
      return json(response, 200, {
        ...safeCase(state),
        duplicateSuppressed: false,
      });
    }
    if (request.method === "POST" && url.pathname.endsWith("/export")) {
      if (!state.approvedAt)
        return json(response, 409, {
          code: "EXPORT_BLOCKED",
          message: "Approval is required before export.",
        });
      const body = await readJson(request);
      const kind = body.kind === "file" ? "file" : "client";
      const html = renderReviewedExports({
        draftHtml,
        proposals: state.proposals,
        authorities: validAuthorities.map(({ title, citation }) => ({
          title,
          citation,
        })),
        rows: scenario.rows,
        rejectedAuthorityTitle:
          rejectedAuthorities[0]?.title ?? "No rejected authority",
      })[kind];
      const filename = `synthetic-tax-memo-${kind}.html`;
      const exported = real
        ? await real.exportHtml(html, filename)
        : { bytes: new TextEncoder().encode(html), contentType: "text/html" };
      const hash = createHash("sha256").update(exported.bytes).digest("hex");
      response.writeHead(200, {
        "Content-Type": exported.contentType ?? "text/html",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "X-Content-SHA256": hash,
        "Access-Control-Expose-Headers":
          "X-Content-SHA256, Content-Disposition",
      });
      response.end(exported.bytes);
      return;
    }
    return json(response, 404, {
      code: "ROUTE_NOT_FOUND",
      message: "The requested workflow action does not exist.",
    });
  } catch (error) {
    const status =
      error instanceof Error && /HTTP 4\d\d/.test(error.message) ? 502 : 500;
    json(response, status, {
      code: "SUPERDOCS_OPERATION_FAILED",
      message:
        status === 502
          ? "SuperDocs rejected the server-side operation."
          : "The workflow could not be completed.",
    });
  }
}).listen(port, "127.0.0.1", () =>
  console.log(`Task 2 BFF ready on http://127.0.0.1:${port} (${mode})`),
);
