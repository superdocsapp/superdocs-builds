import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  ClipboardCheck,
  Download,
  FileCheck2,
  FileText,
  HelpCircle,
  Loader2,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import type { ReactNode } from "react";

import {
  ActivityEvent,
  ChangeListItem,
  JobState,
  ProposedChange,
  ServiceHealth,
  UploadResult,
  WorkflowState,
  formatDate,
  htmlToPlainText,
  stepIndexByState
} from "./domain";
import {
  ApiError,
  approveDocument,
  continueEdit,
  decideBatch,
  decideChange,
  exportDocument,
  fetchChanges,
  fetchHealth,
  fetchJob,
  reEditChunk,
  startEdit,
  subscribeToRun,
  uploadDocument
} from "./api";
import { RunRail, steps } from "./components/RunRail";
import { NextActionBar } from "./components/NextActionBar";
import { AgentFeed } from "./components/AgentFeed";
import { VerificationConsole } from "./components/VerificationConsole";
import { ProposalCard } from "./components/ProposalCard";
import { AuditTrail } from "./components/AuditTrail";
import { SignOff } from "./components/SignOff";
import { GuidedTour, tourAlreadySeen } from "./components/GuidedTour";

/** Watchdog cadence. The stream is the primary signal; this covers it dropping. */
const POLL_INTERVAL_MS = 4000;

/**
 * How long the watchdog trusts a quiet stream before fetching itself. The
 * server pushes full state at least every 5s over SSE, so anything longer than
 * that means the stream is genuinely not delivering.
 */
const STREAM_GRACE_MS = 8000;

export function App() {
  const [health, setHealth] = useState<ServiceHealth | null>(null);
  const [changes, setChanges] = useState<ChangeListItem[]>([]);
  const [selectedNumber, setSelectedNumber] = useState<string | null>(null);
  const [session, setSession] = useState<UploadResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobState | null>(null);
  const [streamed, setStreamed] = useState<ActivityEvent[]>([]);
  const [live, setLive] = useState(false);
  const [workflowState, setWorkflowState] = useState<WorkflowState>("RECEIVED");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [reviewer, setReviewer] = useState(recallReviewer);

  const pollTimer = useRef<number | null>(null);
  const reviewerInput = useRef<HTMLInputElement | null>(null);
  /** When the SSE stream last delivered state, so the watchdog knows to stay out of the way. */
  const lastStreamAt = useRef(0);

  const change = useMemo(
    () => changes.find((candidate) => candidate.number === selectedNumber) ?? changes[0] ?? null,
    [changes, selectedNumber]
  );

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));

    fetchChanges()
      .then((payload) => {
        setChanges(payload.changes);
        setSelectedNumber((current) => current ?? firstActionable(payload.changes));
        if (!tourAlreadySeen()) window.setTimeout(() => setTourOpen(true), 700);
      })
      .catch((cause) => setError(messageFor(cause)));
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const applyJob = useCallback((next: JobState) => {
    setJob(next);
    setWorkflowState(deriveState(next));
  }, []);

  /**
   * Live run updates.
   *
   * The SSE stream is the primary signal — it carries the model's progress as
   * it happens, and the server pushes full state down it on a 5s floor. The
   * poll below is a watchdog, not a second source: while the stream is
   * delivering it stands down entirely, and it only fetches once the stream has
   * gone quiet for longer than the server's own push interval.
   *
   * Running both unconditionally meant every job was read from SuperDocs about
   * twice as often as anything needed, for identical results.
   */
  useEffect(() => {
    if (!session || !jobId) return undefined;

    let cancelled = false;
    let finished = false;

    const poll = async (force = false) => {
      if (cancelled || finished) return;

      // The stream is keeping us current, so there is nothing to ask for.
      if (!force && Date.now() - lastStreamAt.current < STREAM_GRACE_MS) {
        pollTimer.current = window.setTimeout(poll, POLL_INTERVAL_MS);
        return;
      }

      try {
        const next = await fetchJob(session.sessionId, jobId);
        if (cancelled) return;

        applyJob(next);
        finished = next.finished;
        if (!finished) pollTimer.current = window.setTimeout(poll, POLL_INTERVAL_MS);
      } catch (cause) {
        if (cancelled) return;
        setError(messageFor(cause));
        setWorkflowState("FAILED");
      }
    };

    // One immediate read so the UI is populated before the stream connects.
    poll(true);

    const unsubscribe = subscribeToRun(session.sessionId, jobId, {
      onState: (next) => {
        if (cancelled) return;
        lastStreamAt.current = Date.now();
        setLive(true);
        applyJob(next);
        finished = next.finished;
      },
      onActivity: (event) => {
        if (cancelled) return;
        setLive(true);
        setStreamed((current) => [
          ...current,
          { sequence: current.length, type: event.type, content: event.content, at: event.at }
        ]);
      },
      onDegraded: (message) => {
        // The stream is gone; the watchdog is the only signal left, so let it
        // fetch on its next tick instead of standing down.
        lastStreamAt.current = 0;
        setLive(false);
        setNotice(message);
      },
      onError: () => {
        lastStreamAt.current = 0;
        setLive(false);
      }
    });

    return () => {
      cancelled = true;
      stopPolling();
      unsubscribe();
      setLive(false);
    };
  }, [session, jobId, stopPolling, applyJob]);

  /** Refresh once after any action, so the UI reflects the server immediately. */
  const refresh = useCallback(async () => {
    if (!session || !jobId) return null;
    const next = await fetchJob(session.sessionId, jobId);
    applyJob(next);
    return next;
  }, [session, jobId, applyJob]);

  function selectChange(number: string) {
    stopPolling();
    setSelectedNumber(number);
    setSession(null);
    setJobId(null);
    setJob(null);
    setStreamed([]);
    setWorkflowState("RECEIVED");
    setError(null);
    setNotice(null);
  }

  async function generateDocument() {
    if (!change) return;

    if (!change.validation.ok) {
      setWorkflowState("INVALID_INPUT");
      setError(
        `ServiceNow record is incomplete: ${change.validation.missingFields.join(", ")}. Nothing was sent to SuperDocs.`
      );
      return;
    }

    stopPolling();
    setError(null);
    setNotice(null);
    setJob(null);
    setJobId(null);
    setStreamed([]);
    setBusy("upload");
    setWorkflowState("UPLOADED");

    try {
      const uploaded = await uploadDocument(change.number);
      setSession(uploaded);

      setBusy("edit");
      setWorkflowState("EDITING");
      const started = await startEdit(uploaded.sessionId);
      setJobId(started.jobId);
    } catch (cause) {
      setError(messageFor(cause));
      setWorkflowState("FAILED");
    } finally {
      setBusy(null);
    }
  }

  async function decide(proposal: ProposedChange, approved: boolean) {
    if (!session || !jobId) return;

    setBusy(proposal.changeId);
    setError(null);

    try {
      await decideChange({
        sessionId: session.sessionId,
        jobId,
        changeId: proposal.changeId,
        approved
      });
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  /** Reject a change and have SuperDocs redo that section knowing what was wrong. */
  async function rejectAndRedo(proposal: ProposedChange) {
    if (!session || !jobId) return;

    setBusy(proposal.changeId);
    setError(null);

    try {
      await decideChange({
        sessionId: session.sessionId,
        jobId,
        changeId: proposal.changeId,
        approved: false
      });
      const result = await reEditChunk({ sessionId: session.sessionId, changeId: proposal.changeId });
      setNotice(
        result.error
          ? `SuperDocs could not redo that section: ${result.error}`
          : "SuperDocs rewrote that section with your rejection as guidance."
      );
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  /** Approve everything that preserves the ServiceNow values, reject what does not. */
  async function applyRecommendations() {
    if (!session || !jobId || !job) return;

    const undecided = job.proposedChanges.filter((proposal) => !proposal.decided);
    if (!undecided.length) return;

    setBusy("recommendations");
    setError(null);

    try {
      await decideBatch({
        sessionId: session.sessionId,
        jobId,
        decisions: undecided.map((proposal) => ({
          changeId: proposal.changeId,
          approved: proposal.verification.recommendation === "approve"
        }))
      });
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  async function rejectBlocked() {
    if (!session || !jobId || !job) return;

    const blocked = job.proposedChanges.filter(
      (proposal) => !proposal.decided && proposal.verification.verdict === "blocked"
    );
    if (!blocked.length) return;

    setBusy("recommendations");
    setError(null);

    try {
      await decideBatch({
        sessionId: session.sessionId,
        jobId,
        decisions: blocked.map((proposal) => ({ changeId: proposal.changeId, approved: false }))
      });
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  async function resumeEdit() {
    if (!session || !jobId) return;

    setBusy("continue");
    setError(null);

    try {
      await continueEdit({ sessionId: session.sessionId, jobId, keepGoing: true });
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  /**
   * Reviewer sign-off. The server re-verifies the document before it accepts
   * this, and records who signed it.
   *
   * The name is required here rather than optional: an approval nobody put
   * their name to is not an approval. The API still accepts an unattributed
   * one, because it has callers other than this page.
   */
  async function approve() {
    if (!session || !job?.readyToApprove) return;

    const signedBy = reviewer.trim();

    if (!signedBy) {
      setNotice("Add your name before signing off — it goes into the audit trail.");
      reviewerInput.current?.focus();
      return;
    }

    setBusy("approve");
    setError(null);
    setNotice(null);

    try {
      await approveDocument(session.sessionId, signedBy);
      rememberReviewer(signedBy);
      await refresh();
      setWorkflowState("APPROVED");
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  async function download() {
    if (!session || !job?.exportReady) return;

    setBusy("export");
    setError(null);

    try {
      await exportDocument(session.sessionId, session.filename);
      setWorkflowState("EXPORTED");
      setNotice("Exported. The ServiceNow change now carries a work note naming the document.");
      await refresh();
    } catch (cause) {
      setError(messageFor(cause));
    } finally {
      setBusy(null);
    }
  }

  const currentStep = stepIndexByState[workflowState];
  const proposals = job?.proposedChanges ?? [];
  const undecidedCount = proposals.filter((proposal) => !proposal.decided).length;
  const previewText = htmlToPlainText(job?.documentHtml ?? session?.sourceHtml ?? null);
  const feed = useMemo(() => mergeActivity(job?.activity ?? [], streamed), [job, streamed]);

  const nextHandler = resolveNextHandler(job?.nextAction?.id, {
    continue: resumeEdit,
    "reject-blocked": rejectBlocked,
    decide: applyRecommendations,
    approve,
    export: download,
    restart: generateDocument
  });

  return (
    <main className="app-shell">
      <TopBar health={health} onReplayTour={() => setTourOpen(true)} />

      <section className="product-frame">
        <aside className="side-panel" aria-label="Document progress">
          <div className="product-lockup">
            <div className="brand-mark" aria-hidden="true">
              S
            </div>
            <div>
              <span>ServiceFlow</span>
              <strong>Documents</strong>
            </div>
          </div>

          <div className="side-copy">
            <span className="eyebrow">Production Change</span>
            <h1>ServiceNow records, rewritten by SuperDocs, checked before approval.</h1>
          </div>

          <RunRail currentStep={currentStep} job={job} sessionId={session?.sessionId ?? null} />

          <div className="run-card">
            <span className="eyebrow">SuperDocs Session</span>
            <strong>{session?.sessionId ?? "Not started"}</strong>
            <span>
              {job
                ? `Job ${job.status}${job.progress ? ` · ${job.progress}%` : ""}`
                : "No active job"}
            </span>
          </div>
        </aside>

        <section className="workbench">
          <section className="hero-panel">
            <div>
              <span className="eyebrow">Selected Change</span>
              <h2>{change?.short_description ?? "Loading changes..."}</h2>
              <p>
                {change
                  ? `${change.number} was read from ServiceNow over the Table API. The document is written by the live SuperDocs API.`
                  : "Reading the ServiceNow change queue."}
              </p>
            </div>
            <div className="hero-actions">
              <button
                className="primary-button"
                disabled={!change || busy !== null || workflowState === "EDITING"}
                onClick={generateDocument}
                type="button"
              >
                {busy === "upload" || busy === "edit" ? (
                  <Loader2 className="spin" size={15} />
                ) : (
                  <Sparkles size={15} />
                )}
                Generate with SuperDocs
              </button>
            </div>
          </section>

          <NextActionBar
            action={job?.nextAction ?? startingAction(change, workflowState)}
            busy={busy !== null}
            onAct={nextHandler}
          />

          {error && (
            <div className="error-strip" role="alert">
              <AlertCircle size={16} />
              {error}
            </div>
          )}

          {notice && (
            <div className="notice-strip" role="status">
              <ShieldCheck size={16} />
              {notice}
            </div>
          )}

          <section className="queue-panel" aria-label="Change queue" data-tour="queue">
            <div className="queue-heading">
              <div>
                <span className="eyebrow">Change Queue</span>
                <strong>
                  {changes.length} closed changes in ServiceNow
                </strong>
              </div>
            </div>
            <div className="queue-list">
              {changes.map((record) => (
                <button
                  className={`queue-item ${record.number === change?.number ? "selected" : ""}`}
                  key={record.number}
                  onClick={() => selectChange(record.number)}
                  type="button"
                >
                  <span>
                    {record.number}
                    {!record.validation.ok && <em className="queue-flag">incomplete</em>}
                  </span>
                  <strong>{record.short_description}</strong>
                </button>
              ))}
            </div>
          </section>

          {change && (
            <section className="summary-grid" id="change">
              <Metric label="Change ID" value={change.number} mono />
              <Metric label="Status" value={change.status || "Unknown"} />
              <Metric label="Configuration item" value={change.configuration_item} mono />
              <Metric label="Requester" value={change.requester || "-"} />
              <Metric label="Resolution" value={change.resolution_code || "-"} />
              <Metric label="Risk" value={change.risk || "-"} />
              <Metric label="Assignment group" value={change.assignment_group || "-"} />
              <Metric
                label="Maintenance window"
                value={`${formatDate(change.planned_start)} - ${formatDate(change.planned_end)}`}
              />
            </section>
          )}

          <section className="content-grid">
            <section className="left-stack">
              <section className="panel draft-panel" id="draft">
                <PanelHeader
                  icon={<FileText size={19} />}
                  kicker="SuperDocs Document"
                  status={draftStatus(workflowState, job)}
                  title={session?.filename ?? "Production Change Record"}
                />

                <div className="document-preview">
                  {previewText ? (
                    <article className="doc-body">
                      {previewText.split("\n").map((line, index) =>
                        line.trim() ? <p key={index}>{line}</p> : null
                      )}
                    </article>
                  ) : (
                    <div className="empty-document">
                      <FileCheck2 size={34} />
                      <strong>No document yet.</strong>
                      <span>Generate to upload this change to SuperDocs and start the edit.</span>
                    </div>
                  )}
                </div>
              </section>

              <AgentFeed events={feed} live={live} status={job?.status ?? null} />

              <AuditTrail
                checksum={job?.checksum ?? null}
                events={job?.audit ?? []}
                writeBack={job?.writeBack ?? null}
              />
            </section>

            <section className="right-stack">
              <VerificationConsole
                change={change}
                proposals={proposals}
                verification={job?.verification ?? null}
              />

              <section className="panel review-panel" id="review" data-tour="review">
                <PanelHeader
                  icon={<ShieldCheck size={19} />}
                  kicker="Proposed Changes"
                  status={
                    job?.awaitingContinue
                      ? "paused"
                      : job?.awaitingApproval
                        ? `${undecidedCount} awaiting decision`
                        : job?.finished
                          ? "Complete"
                          : "Waiting"
                  }
                  title="Approve or reject each edit"
                />

                {job?.awaitingContinue && (
                  <div className="continue-strip">
                    <p>
                      This edit is large enough that SuperDocs paused to ask whether to keep going.
                      Nothing is lost either way — work already applied is kept.
                    </p>
                    <button
                      className="secondary-button"
                      disabled={busy !== null}
                      onClick={resumeEdit}
                      type="button"
                    >
                      {busy === "continue" ? <Loader2 className="spin" size={15} /> : <ArrowRight size={15} />}
                      Keep going
                    </button>
                  </div>
                )}

                {proposals.length > 0 && (
                  <div className="panel-actions">
                    <button
                      className="secondary-button"
                      disabled={busy !== null || undecidedCount === 0}
                      onClick={applyRecommendations}
                      type="button"
                    >
                      {busy === "recommendations" ? (
                        <Loader2 className="spin" size={15} />
                      ) : (
                        <ShieldCheck size={15} />
                      )}
                      Apply recommendations
                    </button>
                  </div>
                )}

                <div className="proposal-list">
                  {proposals.length === 0 && (
                    <p className="proposal-empty">
                      {workflowState === "EDITING"
                        ? "SuperDocs is drafting. Proposed changes appear here as it works."
                        : "No proposed changes yet."}
                    </p>
                  )}

                  {proposals.map((proposal) => (
                    <ProposalCard
                      busy={busy === proposal.changeId}
                      disabled={busy !== null}
                      key={proposal.changeId}
                      onDecide={(approved) => decide(proposal, approved)}
                      onReEdit={() => rejectAndRedo(proposal)}
                      proposal={proposal}
                    />
                  ))}
                </div>

                {(job?.readyToApprove || job?.approved) && (
                  <SignOff
                    approved={Boolean(job.approved)}
                    approvedAt={job.approvedAt}
                    checksum={job.checksum}
                    disabled={busy !== null}
                    onChange={setReviewer}
                    ref={reviewerInput}
                    reviewer={reviewer}
                    signedBy={job.reviewer}
                  />
                )}

                <div className="panel-actions">
                  <button
                    className="secondary-button"
                    disabled={!job?.readyToApprove || busy !== null || !reviewer.trim()}
                    onClick={approve}
                    title={
                      job?.readyToApprove && !reviewer.trim()
                        ? "Add your name before signing off"
                        : undefined
                    }
                    type="button"
                  >
                    {busy === "approve" ? (
                      <Loader2 className="spin" size={15} />
                    ) : (
                      <ClipboardCheck size={15} />
                    )}
                    {job?.approved ? "Approved" : "Approve document"}
                  </button>
                  <button
                    className="primary-button"
                    disabled={!job?.exportReady || busy !== null}
                    onClick={download}
                    type="button"
                  >
                    {busy === "export" ? (
                      <Loader2 className="spin" size={15} />
                    ) : (
                      <Download size={15} />
                    )}
                    Export from SuperDocs
                  </button>
                </div>
              </section>

            </section>
          </section>
        </section>
      </section>

      {tourOpen && <GuidedTour force onClose={() => setTourOpen(false)} />}
    </main>
  );
}

function TopBar({ health, onReplayTour }: { health: ServiceHealth | null; onReplayTour: () => void }) {
  const quota = health?.superDocs.quota;

  return (
    <header className="top-bar">
      <div className="top-brand">
        <div className="brand-mark" aria-hidden="true">
          S
        </div>
        <strong>ServiceFlow Docs</strong>
      </div>

      <nav aria-label="Primary">
        <a href="#change">Change</a>
        <a href="#draft">Document</a>
        <a href="#review">Review</a>
      </nav>

      <div className="top-right">
        {quota?.remaining != null && (
          <span className="quota-chip" title={`${quota.tier ?? "free"} tier · resets ${quota.resetsAt ?? "monthly"}`}>
            {quota.remaining} ops left
          </span>
        )}
        {health?.superDocs.replaying && <span className="replay-chip">replay</span>}
        <span className="top-status" title={health ? undefined : "Connecting to upstream systems"}>
          <SystemStatus connected={health?.serviceNow.connected} name="ServiceNow" />
          <ArrowRight aria-hidden="true" size={12} />
          <SystemStatus connected={health?.superDocs.connected} name="SuperDocs" />
        </span>
        <button aria-label="Replay the guided tour" className="icon-button" onClick={onReplayTour} type="button">
          <HelpCircle size={15} />
        </button>
      </div>
    </header>
  );
}

/**
 * One system in the pipeline, with whether it is answering.
 *
 * `undefined` means health has not come back yet — distinct from "not
 * connected", which is a real problem rather than a loading state.
 */
function SystemStatus({ connected, name }: { connected: boolean | undefined; name: string }) {
  const state = connected === undefined ? "pending" : connected ? "live" : "down";

  return (
    <span className={`system ${state}`}>
      <span aria-hidden="true" className="system-dot" />
      {name}
      <span className="sr-only">
        {state === "live" ? " connected" : state === "down" ? " unreachable" : " connecting"}
      </span>
    </span>
  );
}

function PanelHeader({
  icon,
  kicker,
  status,
  title
}: {
  icon: ReactNode;
  kicker: string;
  status?: string;
  title: string;
}) {
  return (
    <div className="panel-heading">
      <div className="panel-title">
        <span className="panel-icon">{icon}</span>
        <div>
          <span className="eyebrow">{kicker}</span>
          <h2>{title}</h2>
        </div>
      </div>
      {status && <span className="status-pill">{status}</span>}
    </div>
  );
}

function Metric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong className={mono ? "mono" : ""}>{value}</strong>
    </article>
  );
}

/**
 * Before a run exists the server has no opinion, so the bar still has to say
 * something useful — the first step of the guide.
 */
function startingAction(change: ChangeListItem | null, state: WorkflowState) {
  if (state === "INVALID_INPUT") {
    return {
      id: "restart" as const,
      label: "Pick a complete change",
      detail: "This record is missing fields the document requires, so nothing was sent to SuperDocs.",
      tone: "danger" as const
    };
  }

  return {
    id: "wait" as const,
    label: change ? `Generate the record for ${change.number}` : "Loading the ServiceNow queue",
    detail: change
      ? `${steps[0].detail} Generating uploads it to SuperDocs and starts the edit.`
      : null,
    tone: "neutral" as const
  };
}

function resolveNextHandler(
  id: string | undefined,
  handlers: Record<string, () => void | Promise<void>>
) {
  if (!id) return undefined;
  return handlers[id];
}

/**
 * The stream delivers progress events before a poll would, and the job's own
 * metadata accumulates the same events. Merge on content so a line is not
 * shown twice when both arrive.
 */
function mergeActivity(fromJob: ActivityEvent[], fromStream: ActivityEvent[]) {
  const seen = new Set(fromJob.map((event) => event.content));
  const extra = fromStream.filter((event) => !seen.has(event.content));
  return [...fromJob, ...extra];
}

function deriveState(job: JobState): WorkflowState {
  if (job.failed) return "FAILED";
  if (job.exported) return "EXPORTED";
  if (job.approved) return "APPROVED";
  if (job.awaitingApproval || job.awaitingContinue) return "REVIEW_REQUIRED";
  if (job.finished) return "APPROVED";
  return "EDITING";
}

function draftStatus(state: WorkflowState, job: JobState | null) {
  if (state === "EXPORTED") return "Exported";
  if (job?.finished) return "Final";
  if (job?.awaitingApproval) return "Proposed";
  if (state === "EDITING") return "Editing";
  if (state === "UPLOADED") return "Uploaded";
  return "Waiting";
}

/**
 * Which change to open on.
 *
 * The queue is ordered by most recently updated, and the record that exists to
 * demonstrate the validation gate can easily be the newest one — which opened
 * the app on a change that cannot be generated, with the first action a dead
 * end. Open on something the reviewer can actually act on; the incomplete
 * record is still one click away.
 */
function firstActionable(changes: ChangeListItem[]) {
  const usable = changes.find((candidate) => candidate.validation.ok);
  return usable?.number ?? changes[0]?.number ?? null;
}

/**
 * The reviewer signing off is almost always the same person, run after run, so
 * their name is remembered on this browser. It is a convenience only: the
 * authoritative record of who approved what lives server-side in the run's
 * audit trail.
 */
const REVIEWER_KEY = "serviceflow.reviewer";

function recallReviewer() {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberReviewer(name: string) {
  try {
    window.localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    /* private windows and blocked site data just do not remember it */
  }
}

function messageFor(cause: unknown) {
  if (cause instanceof ApiError) {
    return cause.detail ? `${cause.message} (${cause.detail})` : cause.message;
  }
  return cause instanceof Error ? cause.message : "Something went wrong.";
}
