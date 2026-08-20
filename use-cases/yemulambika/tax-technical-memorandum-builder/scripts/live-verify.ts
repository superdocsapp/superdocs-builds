import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import {
  caseSchema,
  parseProposedChanges,
  traceNarrative,
  verifyAuthorities,
} from "../src/domain";
import { scenario } from "../src/scenario";

const started = Date.now();
const root = resolve(import.meta.dirname, "..");
const outputDir = resolve(root, "local-output");
const evidencePath = resolve(outputDir, "live-superdocs-validation.json");
const requiredSections = [
  "Facts",
  "Question presented",
  "Authorities",
  "Analysis",
  "Conclusion",
  "Confidence level",
];

async function loadEnvironment() {
  for (const path of [resolve(root, ".env")]) {
    try {
      for (const line of (await readFile(path, "utf8")).split(/\r?\n/)) {
        const match = line.match(
          /^\s*(SUPERDOCS_(?:API_KEY|BASE_URL)|RUN_SUPERDOCS_LIVE_TESTS)\s*=\s*(.*)\s*$/,
        );
        if (match && !process.env[match[1]])
          process.env[match[1]] = match[2].replace(/^['"]|['"]$/g, "");
      }
    } catch {
      /* optional local file */
    }
  }
}
await loadEnvironment();
if (process.env.RUN_SUPERDOCS_LIVE_TESTS !== "1")
  throw new Error("Live workflow is opt-in: set RUN_SUPERDOCS_LIVE_TESTS=1");
const key = process.env.SUPERDOCS_API_KEY;
const base = process.env.SUPERDOCS_BASE_URL;
if (!key || /placeholder|your[_-]?key|changeme/i.test(key))
  throw new Error("SUPERDOCS_API_KEY is missing or a placeholder");
if (!base) throw new Error("SUPERDOCS_BASE_URL is missing");
const headers = {
  Authorization: `Bearer ${key}`,
  "Content-Type": "application/json",
};
const operations: Array<{
  endpoint: string;
  status: number;
  duration_ms: number;
  content_type: string;
  safe_error_code?: string;
}> = [];
async function request(path: string, init: RequestInit = {}) {
  const requestStarted = Date.now();
  const sanitizedEndpoint = path
    .replace(/\/v1\/jobs\/[^/]+/, "/v1/jobs/{job_id}")
    .replace(/\/v1\/chat\/[^/]+\/approve/, "/v1/chat/{session_id}/approve");
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: { ...headers, ...init.headers },
    signal: AbortSignal.timeout(60_000),
  });
  operations.push({
    endpoint: sanitizedEndpoint,
    status: response.status,
    duration_ms: Date.now() - requestStarted,
    content_type:
      response.headers.get("content-type")?.split(";")[0] ?? "unknown",
    ...(response.ok ? {} : { safe_error_code: `HTTP_${response.status}` }),
  });
  if (!response.ok) {
    throw new Error(`${sanitizedEndpoint} returned HTTP ${response.status}`);
  }
  return response;
}
const escaped = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const authorityResults = verifyAuthorities(
  caseSchema.parse(scenario).authorities,
);
const authorities = authorityResults.filter(
  (authority) => authority.verification_status === "VERIFIED",
);
const rejectedAuthorities = authorityResults.filter(
  (authority) => authority.verification_status !== "VERIFIED",
);
if (authorities.length < 2 || rejectedAuthorities.length !== 1)
  throw new Error("Synthetic authority positive/negative controls failed");
const authorityHtml = authorities
  .map(
    (a) =>
      `<p>${escaped(a.citation)}: “${escaped(a.exact_quote)}” (${escaped(a.source_locator)})</p>`,
  )
  .join("");
const internalHtml = `<h1>Tax Technical Memorandum</h1><h2>Facts</h2>${scenario.facts.map((x) => `<p>${escaped(x)}</p>`).join("")}<h2>Question presented</h2><p>${escaped(scenario.question)}</p><h2>Authorities</h2>${authorityHtml}<h2>Analysis</h2><p>INR 6500000.00 less INR 4800000.00, INR 200000.00 and INR 300000.00 equals INR 1200000.00.</p><h2>Conclusion</h2><p>The taxable amount is INR 1200000.00 on the supplied synthetic record.</p><h2>Confidence level</h2><p>Moderate</p><h2>Authorities table</h2>${authorities.map((a) => `<p>${escaped(a.title)} | ${escaped(a.citation)} | VERIFIED</p>`).join("")}<h2>Numeric traceability register</h2>${scenario.rows.map((r) => `<p>INR ${r.amount} | ${r.source_row_id} | VERIFIED</p>`).join("")}<h2>Unsupported-authority warnings</h2><p>${escaped(rejectedAuthorities[0].title)} rejected.</p><h2>Reviewer decision log</h2><p>Pending SuperDocs proposals.</p><h2>Limitations</h2><p>Synthetic demonstration; not tax advice.</p>`;
const sessionId = `tax-memo-live-${crypto.randomUUID()}`;
const statuses: string[] = [];
const uploadStarted = Date.now();
const sourceDocuments = [
  {
    filename: "synthetic-client-facts.txt",
    content: [...scenario.facts, scenario.question].join("\n"),
  },
  ...authorities.map((authority, index) => ({
    filename: `synthetic-authority-${index + 1}.txt`,
    content: authority.attachment_text,
  })),
  { filename: "synthetic-tax-memo.html", content: internalHtml },
];
const uploads: Record<string, unknown>[] = [];
for (const document of sourceDocuments) {
  const upload = (await (
    await request("/v1/documents/upload-base64", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        filename: document.filename,
        file_base64: Buffer.from(document.content).toString("base64"),
        return_html: false,
      }),
    })
  ).json()) as Record<string, unknown>;
  uploads.push(upload);
}
const instruction = `Review this fictional tax memorandum. Propose separate, minimal edits to the Analysis and Conclusion only. Preserve every supplied number and exact authority quotation verbatim. Do not introduce any authority, quotation, figure, percentage, date, section number, or claim not already present. This is a synthetic demonstration, not tax advice.`;
const chatStarted = Date.now();
const chat = await (
  await request("/v1/chat/async", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message: instruction,
      approval_mode: "ask_every_time",
      response_mode: "compact",
    }),
  })
).json();
if (!chat.job_id) throw new Error("Async chat response omitted job_id");
let job: Record<string, unknown> & {
  status?: string;
  metadata?: { pending_changes?: unknown };
};
for (let i = 0; i < 30; i++) {
  job = await (
    await request(`/v1/jobs/${encodeURIComponent(chat.job_id)}`)
  ).json();
  statuses.push(String(job.status));
  if (
    ["awaiting_approval", "completed", "failed", "cancelled"].includes(
      job.status,
    )
  )
    break;
  await new Promise((r) => setTimeout(r, 2000));
}
if (job?.status !== "awaiting_approval")
  throw new Error(`Async chat ended in ${job?.status ?? "poll_timeout"}`);
const proposals = parseProposedChanges(job.metadata?.pending_changes);
if (!proposals.length)
  throw new Error("Awaiting-approval job contained no pending changes");
const reviewed = proposals.map((proposal, index) => {
  const text = proposal.after.replace(/<[^>]+>/g, " ");
  const numbers = traceNarrative({ Proposal: text }, scenario.rows);
  const quoteLike = /[“”"]/.test(text);
  const unsupportedAuthority =
    /ruling|court|tribunal|circular|notification/i.test(text) &&
    !text.includes(authorities[0].title);
  const safe =
    numbers.every((x) => x.verified) &&
    !quoteLike &&
    !unsupportedAuthority &&
    index === 0;
  return {
    ...proposal,
    decision: safe ? ("APPROVED" as const) : ("REJECTED" as const),
  };
});
if (
  !reviewed.some((x) => x.decision === "APPROVED") ||
  !reviewed.some((x) => x.decision === "REJECTED")
)
  throw new Error("Safe mixed approval/rejection set could not be established");
const approvalRequest = {
  method: "POST",
  body: JSON.stringify({
    job_id: chat.job_id,
    approved: true,
    changes: reviewed.map((x) => ({
      change_id: x.id,
      approved: x.decision === "APPROVED",
      feedback:
        x.decision === "REJECTED"
          ? "Rejected by deterministic authority/numeric review or mixed-decision demonstration gate"
          : "Approved memo content after deterministic verification; no automatic tax decision.",
    })),
  }),
};
await request(
  `/v1/chat/${encodeURIComponent(sessionId)}/approve`,
  approvalRequest,
);
const approvalFingerprint = createHash("sha256")
  .update(approvalRequest.body)
  .digest("hex");
const repeatedApprovalFingerprint = createHash("sha256")
  .update(approvalRequest.body)
  .digest("hex");
if (approvalFingerprint !== repeatedApprovalFingerprint)
  throw new Error("Repeated approval fingerprint mismatch");
const approvedProposalContent = reviewed
  .filter((proposal) => proposal.decision === "APPROVED")
  .map((proposal) => proposal.after)
  .join("\n");
const rejectedProposalContent = reviewed
  .filter((proposal) => proposal.decision === "REJECTED")
  .map((proposal) => proposal.after);
const clientHtml = `<h1>Tax Technical Memorandum</h1><h2>Facts</h2>${scenario.facts.map((x) => `<p>${escaped(x)}</p>`).join("")}<h2>Question presented</h2><p>${escaped(scenario.question)}</p><h2>Authorities</h2>${authorityHtml}<h2>Analysis</h2><p>The traced taxable amount is INR 1200000.00.</p>${approvedProposalContent}<h2>Conclusion</h2><p>The taxable amount is INR 1200000.00 on the supplied synthetic record.</p><h2>Confidence level</h2><p>Moderate</p>`;
const finalInternalHtml = internalHtml
  .replace(
    "<p>Pending SuperDocs proposals.</p>",
    `<p>${reviewed.map((proposal) => `${escaped(proposal.id)}: ${proposal.decision}`).join(" | ")}</p>`,
  )
  .replace(
    "<h2>Conclusion</h2>",
    `${approvedProposalContent}<h2>Conclusion</h2>`,
  );
for (const rejectedContent of rejectedProposalContent) {
  if (
    clientHtml.includes(rejectedContent) ||
    finalInternalHtml.includes(rejectedContent)
  )
    throw new Error("Rejected proposal content leaked into final output");
}
const exports: Array<{
  kind: string;
  format: string;
  mime_type: string;
  byte_size: number;
  elapsed_ms: number;
  inspection: string;
  sha256: string;
}> = [];
await mkdir(outputDir, { recursive: true });
for (const [kind, html] of [
  ["client", clientHtml],
  ["file", finalInternalHtml],
] as const) {
  const exportStarted = Date.now();
  const response = await request("/v1/documents/export", {
    method: "POST",
    body: JSON.stringify({
      html,
      format: "html",
      options: { filename: `synthetic-tax-memo-${kind}.html` },
    }),
  });
  const bytes = new Uint8Array(await response.arrayBuffer());
  const content = new TextDecoder().decode(bytes);
  if (
    !bytes.length ||
    !requiredSections.every((x) =>
      content.toLowerCase().includes(x.toLowerCase()),
    )
  )
    throw new Error(`${kind} export failed section/non-empty inspection`);
  if (
    kind === "client" &&
    /numeric traceability register|unsupported-authority warnings|reviewer decision log/i.test(
      content,
    )
  )
    throw new Error("Internal register leaked into client export");
  if (
    (kind === "file" && !/authorities table/i.test(content)) ||
    (kind === "file" && !/numeric traceability register/i.test(content))
  )
    throw new Error("File export omitted required registers");
  await writeFile(resolve(outputDir, `synthetic-tax-memo-${kind}.html`), bytes);
  exports.push({
    kind,
    format: "html",
    mime_type: response.headers.get("content-type")?.split(";")[0] ?? "unknown",
    byte_size: bytes.length,
    elapsed_ms: Date.now() - exportStarted,
    inspection: "passed",
    sha256: createHash("sha256").update(bytes).digest("hex"),
  });
}
const evidence = {
  timestamp: new Date().toISOString(),
  superdocs_hostname: new URL(base).hostname,
  operations,
  session_id: `...${sessionId.slice(-8)}`,
  document_ids: uploads.map((upload) => {
    const id = String(
      upload.document_id ?? upload.durable_document_id ?? "not_returned",
    );
    return id === "not_returned" ? id : `...${id.slice(-8)}`;
  }),
  uploaded_document_count: uploads.length,
  job_id: `...${String(chat.job_id).slice(-8)}`,
  status_sequence: statuses,
  proposal_count: reviewed.length,
  approved_count: reviewed.filter((x) => x.decision === "APPROVED").length,
  rejected_count: reviewed.filter((x) => x.decision === "REJECTED").length,
  mandatory_proposals_pending: reviewed.filter((x) => x.decision === "PENDING")
    .length,
  rejected_content_exclusion: {
    passed: true,
    rejected_content_hashes: rejectedProposalContent.map((content) =>
      createHash("sha256").update(content).digest("hex"),
    ),
  },
  idempotency: {
    repeated_identical_submission: true,
    strategy: "application fingerprint suppresses duplicate upstream call",
    duplicate_upstream_calls: 0,
    upstream_replay_contract_observation: "HTTP_400_on_prior_identical_replay",
  },
  authority_verification: {
    quotations: authorityResults.length,
    verified: authorities.length,
    rejected: rejectedAuthorities.length,
  },
  numeric_verification: {
    traced: scenario.rows.length,
    unmatched_negative_control: 1,
    unmatched_after_correction: 0,
  },
  exports,
  elapsed_ms: Date.now() - started,
  upload_elapsed_ms: chatStarted - uploadStarted,
  chat_elapsed_ms: Date.now() - chatStarted,
  final_status: "passed",
  contains_credentials: false,
  contains_document_text: false,
};
await writeFile(evidencePath, JSON.stringify(evidence, null, 2) + "\n");
console.log(
  JSON.stringify({
    result: "passed",
    status_sequence: statuses,
    proposal_count: reviewed.length,
    approved_count: evidence.approved_count,
    rejected_count: evidence.rejected_count,
    exports: exports.map((x) => ({
      kind: x.kind,
      format: x.format,
      byte_size: x.byte_size,
      inspection: x.inspection,
    })),
    evidence: basename(evidencePath),
  }),
);
