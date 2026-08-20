import { useEffect, useRef, useState } from "react";
import type { NumericEntry, Proposal } from "./domain";
import { validateDocumentFiles } from "./file-selection";
import "./style.css";

type UiCase = {
  caseId: string;
  mode: string;
  documents: Array<{ name: string; status: string; documentId?: string }>;
  jobStatus: string;
  jobDurationMs: number;
  proposals: Proposal[];
  authorities: Array<{
    title: string;
    citation: string;
    exactQuote: string;
    status: string;
  }>;
  numeric: NumericEntry[];
  negativeCleared: boolean;
  mandatoryPending: number;
  approved: boolean;
  duplicateSuppressed?: boolean;
};
type Download = {
  kind: "client" | "file";
  name: string;
  size: number;
  hash: string;
  url: string;
};

async function api(path: string, init: RequestInit = {}) {
  const response = await fetch(`/api/superdocs${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      code?: string;
      message?: string;
    };
    throw new Error(
      `${body.code ?? "REQUEST_FAILED"}: ${body.message ?? "The operation failed."}`,
    );
  }
  return response;
}

export default function App() {
  const [mode, setMode] = useState("Loading…");
  const [configured, setConfigured] = useState(true);
  const [workflow, setWorkflow] = useState<UiCase>();
  const [status, setStatus] = useState("Ready");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloads, setDownloads] = useState<Download[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const actionRef = useRef(false);
  const downloadsRef = useRef<Download[]>([]);

  useEffect(() => {
    downloadsRef.current = downloads;
  }, [downloads]);

  useEffect(() => {
    api("/config")
      .then((response) => response.json())
      .then((body) => {
        setMode(body.mode);
        setConfigured(body.configured);
        if (!body.configured)
          setError(`${body.error.code}: ${body.error.message}`);
      })
      .catch((reason) => {
        setMode("Configuration error");
        setError(String(reason));
      });
    return () =>
      downloadsRef.current.forEach((download) =>
        URL.revokeObjectURL(download.url),
      );
  }, []);

  async function action(label: string, run: () => Promise<void>) {
    if (actionRef.current) return;
    actionRef.current = true;
    setBusy(true);
    setError("");
    setStatus(label);
    try {
      await run();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The operation failed.",
      );
      setStatus("Failed — retry is available");
    } finally {
      actionRef.current = false;
      setBusy(false);
    }
  }
  const start = () =>
    action("Starting a new tax memorandum case…", async () => {
      const response = await api("/cases", { method: "POST", body: "{}" });
      setWorkflow(await response.json());
      setStatus("Case ready — select four synthetic documents");
    });
  const upload = () =>
    action("Uploading four synthetic documents…", async () => {
      if (!workflow) return;
      const selection = validateDocumentFiles(files);
      if (!selection.ok) throw new Error(selection.message);
      const pendingNames = new Set(
        workflow.documents
          .filter((document) => document.status !== "UPLOADED")
          .map((document) => document.name),
      );
      let current = workflow;
      for (const file of selection.files.filter((item) =>
        pendingNames.has(item.name),
      )) {
        const response = await api(`/cases/${workflow.caseId}/documents`, {
          method: "POST",
          body: JSON.stringify({ name: file.name, content: await file.text() }),
        });
        current = await response.json();
        setWorkflow(current);
      }
      setStatus("Four documents uploaded");
    });
  const generate = () =>
    action("Starting live memorandum generation…", async () => {
      if (!workflow) return;
      let current = (await (
        await api(`/cases/${workflow.caseId}/generate`, {
          method: "POST",
          body: "{}",
        })
      ).json()) as UiCase;
      setWorkflow(current);
      const delays = [
        500, 1000, 2000, 4000, 8000, 8000, 8000, 8000, 8000, 8000, 8000, 8000,
      ];
      for (const delay of delays) {
        if (
          ["awaiting_approval", "completed", "failed", "cancelled"].includes(
            current.jobStatus,
          )
        )
          break;
        setStatus(`SuperDocs job: ${current.jobStatus}`);
        await new Promise((resolve) => setTimeout(resolve, delay));
        current = (await (
          await api(`/cases/${workflow.caseId}/status`)
        ).json()) as UiCase;
        setWorkflow(current);
      }
      if (!["awaiting_approval", "completed"].includes(current.jobStatus))
        throw new Error(
          current.jobStatus === "failed"
            ? "JOB_FAILED: SuperDocs generation failed."
            : "POLL_TIMEOUT: The bounded polling window ended. Retry status safely.",
        );
      setStatus(`SuperDocs job: ${current.jobStatus} — human review required`);
    });
  async function clearControls() {
    if (!workflow) return;
    await action(
      "Rejecting fabricated quotation and unmatched figure…",
      async () => {
        const response = await api(
          `/cases/${workflow.caseId}/clear-negative-controls`,
          { method: "POST", body: "{}" },
        );
        const cleared = (await response.json()) as UiCase;
        setWorkflow({ ...cleared, proposals: workflow.proposals });
        setStatus("Negative controls rejected and cleared");
      },
    );
  }
  function updateProposal(id: string, patch: Partial<Proposal>) {
    setWorkflow((current) =>
      current
        ? {
            ...current,
            proposals: current.proposals.map((proposal) =>
              proposal.id === id ? { ...proposal, ...patch } : proposal,
            ),
          }
        : current,
    );
  }
  const approve = () =>
    action("Submitting reviewed content…", async () => {
      if (!workflow) return;
      const response = await api(`/cases/${workflow.caseId}/approve`, {
        method: "POST",
        body: JSON.stringify({ proposals: workflow.proposals }),
      });
      const next = (await response.json()) as UiCase;
      setWorkflow(next);
      setStatus(
        next.duplicateSuppressed
          ? "Identical approval suppressed locally"
          : "Review submitted — memo content approved",
      );
    });
  async function exportOutput(kind: "client" | "file") {
    if (!workflow) return;
    await action(`Exporting ${kind}-ready HTML…`, async () => {
      const response = await api(`/cases/${workflow.caseId}/export`, {
        method: "POST",
        body: JSON.stringify({ kind }),
      });
      const blob = await response.blob();
      const name =
        response.headers
          .get("content-disposition")
          ?.match(/filename="([^"]+)"/)?.[1] ?? `tax-memo-${kind}.html`;
      const hash = response.headers.get("x-content-sha256") ?? "unavailable";
      const url = URL.createObjectURL(blob);
      setDownloads((items) => [
        ...items.filter((item) => item.kind !== kind),
        { kind, name, size: blob.size, hash, url },
      ]);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = name;
      anchor.click();
      setStatus(`${name} downloaded`);
    });
  }
  const mandatoryPending =
    workflow?.proposals.filter((proposal) => proposal.decision === "PENDING")
      .length ?? 0;
  const blockers =
    !workflow?.negativeCleared ||
    Boolean(mandatoryPending) ||
    workflow?.proposals.some((proposal) => !proposal.reviewerNote);
  const fileSelection = validateDocumentFiles(files);

  return (
    <main>
      <header>
        <p className="eyebrow">SuperDocs use case · synthetic demonstration</p>
        <h1>Tax Technical Memorandum Builder</h1>
        <p className="mode">SuperDocs mode: {mode}</p>
        <button
          disabled={busy || Boolean(workflow) || !configured}
          onClick={start}
        >
          Start new tax memorandum case
        </button>
        <span className="status" aria-live="polite">
          {status}
        </span>
        {error && (
          <p className="bad" role="alert">
            {error}
          </p>
        )}
      </header>
      {workflow && (
        <>
          <section>
            <h2>Uploaded documents</h2>
            {workflow.documents.map((document) => (
              <p key={document.name}>
                <b>{document.name}</b> — {document.status}{" "}
                <small>{document.documentId}</small>
              </p>
            ))}
            <label>
              Select the four supplied synthetic documents
              <input
                aria-label="Synthetic document files"
                type="file"
                multiple
                onChange={(event) => {
                  const selected = Array.from(event.target.files ?? []);
                  setFiles(selected);
                  const validation = validateDocumentFiles(selected);
                  setError(validation.ok ? "" : validation.message);
                }}
              />
            </label>
            <button
              disabled={
                busy ||
                !fileSelection.ok ||
                workflow.jobStatus !== "ready" ||
                workflow.documents.every(
                  (document) => document.status === "UPLOADED",
                )
              }
              onClick={upload}
            >
              Upload four documents
            </button>
            <button
              disabled={
                busy ||
                workflow.documents.some(
                  (document) => document.status !== "UPLOADED",
                ) ||
                Boolean(workflow.proposals.length)
              }
              onClick={generate}
            >
              {workflow.jobStatus === "ready"
                ? "Generate memorandum"
                : "Retry generation status"}
            </button>
            <p>
              <b>Job status:</b> {workflow.jobStatus} ({workflow.jobDurationMs}{" "}
              ms)
            </p>
          </section>
          <section>
            <h2>Quotation verification</h2>
            {workflow.authorities.map((authority) => (
              <article key={authority.title}>
                <h3>{authority.title}</h3>
                <p>{authority.citation}</p>
                <blockquote>{authority.exactQuote}</blockquote>
                <b className={authority.status === "VERIFIED" ? "ok" : "bad"}>
                  {authority.status === "VERIFIED"
                    ? "VERIFIED"
                    : "REJECTED / BLOCKING"}
                </b>
              </article>
            ))}
          </section>
          <section>
            <h2>Monetary traceability</h2>
            {workflow.numeric.map((entry, index) => (
              <p
                key={`${entry.narrative_figure}-${index}`}
                className={entry.verified ? "ok" : "bad"}
                data-testid="monetary-row"
                data-trace-status={
                  entry.verified ? "matched" : "unmatched-blocking"
                }
                data-monetary-id={
                  entry.source_row_id ?? `unmatched-${index + 1}`
                }
              >
                {entry.narrative_figure} —{" "}
                {entry.verified
                  ? `TRACED ${entry.source_row_id}`
                  : "UNMATCHED / BLOCKING — finalization is blocked until this figure is corrected"}
              </p>
            ))}
            {!workflow.negativeCleared && (
              <button
                className="reject"
                disabled={busy}
                onClick={clearControls}
              >
                Reject fabricated quotation and correct unmatched figure
              </button>
            )}
          </section>
          <section>
            <h2>Human review</h2>
            {workflow.proposals.length === 0 ? (
              <p>Proposals will begin PENDING after generation.</p>
            ) : (
              workflow.proposals.map((proposal) => {
                const sameHeading = workflow.proposals.filter(
                  (item) => item.section === proposal.section,
                );
                const position =
                  sameHeading.findIndex((item) => item.id === proposal.id) + 1;
                const accessibleName = `${proposal.section} proposal ${position} of ${sameHeading.length}`;
                return (
                  <article
                    className="proposal"
                    key={proposal.id}
                    data-proposal-id={proposal.id}
                  >
                    <h3>{proposal.section}</h3>
                    <p className="proposal-id">Proposal ID: {proposal.id}</p>
                    <p>{proposal.after}</p>
                    <label>
                      Reviewer note
                      <input
                        aria-label={`Reviewer note for ${accessibleName}`}
                        value={proposal.reviewerNote ?? ""}
                        onChange={(event) =>
                          updateProposal(proposal.id, {
                            reviewerNote: event.target.value,
                          })
                        }
                      />
                    </label>
                    <button
                      aria-label={`Approve ${accessibleName}`}
                      onClick={() =>
                        updateProposal(proposal.id, { decision: "APPROVED" })
                      }
                    >
                      Approve
                    </button>
                    <button
                      className="reject"
                      aria-label={`Reject ${accessibleName}`}
                      onClick={() =>
                        updateProposal(proposal.id, { decision: "REJECTED" })
                      }
                    >
                      Reject
                    </button>
                    <b>{proposal.decision}</b>
                  </article>
                );
              })
            )}
            <p>
              <b>Mandatory pending:</b> {mandatoryPending}
            </p>
            <button
              disabled={busy || blockers || workflow.approved}
              onClick={approve}
            >
              Submit reviewed content
            </button>
            <button disabled={busy || !workflow.approved} onClick={approve}>
              Submit identical decisions again
            </button>
          </section>
          <section>
            <h2>Final exports</h2>
            <button
              disabled={busy || !workflow.approved}
              onClick={() => exportOutput("client")}
            >
              Download client-ready HTML
            </button>
            <button
              disabled={busy || !workflow.approved}
              onClick={() => exportOutput("file")}
            >
              Download file-ready HTML
            </button>
            {downloads.map((download) => (
              <article key={download.kind}>
                <h3>{download.name}</h3>
                <p>{download.size} bytes</p>
                <code>{download.hash}</code>
                <a href={download.url} target="_blank" rel="noreferrer">
                  Open {download.kind} preview
                </a>
              </article>
            ))}
          </section>
        </>
      )}
    </main>
  );
}
