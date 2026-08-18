"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { PanelLeft, PanelRight, SquarePen, TriangleAlert } from "lucide-react";
import {
  POLICY_DOCUMENT_TYPES,
  type ChangeSet,
  type PolicyDocumentType,
} from "@/domain";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { AiCommandBar } from "./AiCommandBar";
import { DOCUMENT_TITLES } from "./document-meta";
import { DocumentPreview } from "./DocumentPreview";
import { DocumentRail, type DocumentStatus } from "./DocumentRail";
import { EditReviewPanel, EditStatusLine } from "./EditReview";
import { ExportControl } from "./ExportControl";
import type { PolicyWorkspaceState } from "./generate-workspace";
import { PolicyFactsPanel } from "./PolicyFactsPanel";
import { AppHeader, ConsistencyStatus } from "./shell";
import { SynchronizedReviewDialog } from "./SynchronizedReviewDialog";
import {
  getSuperDocsJob,
  getSuperDocsSynchronizedJob,
  exportSuperDocsDocument,
  initializeSuperDocsSession,
  refreshSuperDocsDocuments,
  startSuperDocsEdit,
  startSuperDocsSynchronizedChange,
  submitSuperDocsReview,
  submitSuperDocsSynchronizedReview,
} from "./superdocs-api";
import type {
  PolicyDocumentExportFormat,
  SuperDocsJobView,
  SuperDocsTargetedJob,
  SuperDocsWorkspaceSession,
} from "./superdocs-contract";
import { applyPolicyEditOutcome } from "./workspace-edit";
import {
  activeSynchronizedChangeSet,
  isEditBusy,
  isSynchronizedBusy,
  withUpdatedJob,
  type EditState,
  type EditTarget,
  type SynchronizedState,
} from "./workspace-state";
import {
  approveSynchronizedChangeSet,
  commitValidatedSynchronizedChange,
  failSynchronizedChangeSet,
  proposeReturnWindowChangeSet,
  rejectSynchronizedChangeSet,
} from "./changeset-workflow";

export function WorkspaceView({
  workspace,
  onWorkspaceChange,
  onEditIntake,
}: {
  workspace: PolicyWorkspaceState;
  onWorkspaceChange: (workspace: PolicyWorkspaceState) => void;
  onEditIntake: () => void;
}) {
  const [activeTab, setActiveTab] = useState<PolicyDocumentType>("terms");
  const [session, setSession] = useState<SuperDocsWorkspaceSession | null>(null);
  const [connectionState, setConnectionState] = useState<
    "idle" | "connecting" | "connected" | "error"
  >("idle");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [exportingFormat, setExportingFormat] =
    useState<PolicyDocumentExportFormat | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportWarning, setExportWarning] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [editState, setEditState] = useState<EditState>({ stage: "idle" });
  const [returnWindowInput, setReturnWindowInput] = useState(() =>
    String(workspace.profile.returns.windowDays),
  );
  const [synchronizedState, setSynchronizedState] =
    useState<SynchronizedState>({ stage: "idle" });
  const [superDocsDocuments, setSuperDocsDocuments] = useState<
    ReadonlySet<PolicyDocumentType>
  >(() => new Set());
  const [navOpen, setNavOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const operationControllersRef = useRef(new Set<AbortController>());
  const { profile, documents, validation } = workspace;
  const editBusy = isEditBusy(editState.stage);
  const synchronizedBusy = isSynchronizedBusy(synchronizedState.stage);
  const exportBusy = exportingFormat !== null;
  const operationBusy = editBusy || synchronizedBusy || exportBusy;

  useEffect(() => {
    const controllers = operationControllersRef.current;
    return () => controllers.forEach((controller) => controller.abort());
  }, []);

  async function ensureSession(
    signal: AbortSignal,
  ): Promise<SuperDocsWorkspaceSession> {
    if (session) {
      return session;
    }
    setConnectionState("connecting");
    setConnectionError(null);
    try {
      const initialized = await initializeSuperDocsSession(profile, signal);
      setSession(initialized);
      setConnectionState("connected");
      return initialized;
    } catch (error) {
      if (!signal.aborted) {
        setConnectionState("error");
        setConnectionError(errorMessage(error));
      }
      throw error;
    }
  }

  async function handleInitialize() {
    if (session || connectionState === "connecting") {
      return;
    }
    const controller = beginOperation(operationControllersRef.current);
    try {
      await ensureSession(controller.signal);
    } catch {}
  }

  async function handleExport(format: PolicyDocumentExportFormat) {
    if (!session || operationBusy) {
      return;
    }
    const selectedDocumentType = activeTab;
    const selectedDocumentId = session.documentIds[selectedDocumentType];
    const controller = beginOperation(operationControllersRef.current);
    setExportingFormat(format);
    setExportError(null);
    setExportWarning(null);

    try {
      const exported = await exportSuperDocsDocument(
        {
          sessionId: session.sessionId,
          documentType: selectedDocumentType,
          documentId: selectedDocumentId,
          documentIds: session.documentIds,
          format,
          companyName: profile.company.legalName,
        },
        controller.signal,
      );
      triggerDownload(exported.blob, exported.filename);
      if (exported.warningCount > 0) {
        setExportWarning(
          `${DOCUMENT_TITLES[selectedDocumentType]} downloaded with ${exported.warningCount} SuperDocs export ${exported.warningCount === 1 ? "warning" : "warnings"}.`,
        );
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setExportError(errorMessage(error));
      }
    } finally {
      if (!controller.signal.aborted) {
        setExportingFormat(null);
      }
    }
  }

  async function handleProposeEdit() {
    if (!session || !instruction.trim() || operationBusy) {
      return;
    }
    const controller = beginOperation(operationControllersRef.current);
    const target: EditTarget = {
      documentType: activeTab,
      documentId: session.documentIds[activeTab],
    };
    setEditState({ stage: "submitting", target });

    try {
      const started = await startSuperDocsEdit(
        {
          sessionId: session.sessionId,
          documentId: target.documentId,
          instruction: instruction.trim(),
        },
        controller.signal,
      );
      setEditState({ stage: "processing", target, job: started });
      const reviewJob = await pollUntilReview(
        started,
        session,
        target,
        controller.signal,
        (job) => setEditState({ stage: "processing", target, job }),
      );

      if (reviewJob.status === "completed") {
        setEditState({
          stage: "completed",
          message: "SuperDocs completed without proposing changes.",
        });
        return;
      }
      setEditState({ stage: "awaiting_review", target, job: reviewJob });
    } catch (error) {
      if (!controller.signal.aborted) {
        setEditState({ stage: "error", message: errorMessage(error) });
      }
    }
  }

  async function handleReview(approved: boolean) {
    if (
      !session ||
      editState.stage !== "awaiting_review" ||
      editState.job.proposals.length === 0
    ) {
      return;
    }
    const { job, target } = editState;
    const controller = beginOperation(operationControllersRef.current);
    setEditState({
      stage: "applying",
      target,
      job,
      message: approved ? "Applying approved changes…" : "Rejecting changes…",
    });

    try {
      await submitSuperDocsReview(
        {
          sessionId: session.sessionId,
          jobId: job.jobId,
          documentId: target.documentId,
          approved,
        },
        controller.signal,
      );

      if (!approved) {
        onWorkspaceChange(
          applyPolicyEditOutcome(workspace, { kind: "rejected" }),
        );
        setEditState({ stage: "completed", message: "Changes rejected" });
        return;
      }

      await pollUntilCompleted(
        job,
        session,
        target,
        controller.signal,
        (nextJob) =>
          setEditState({
            stage: "applying",
            target,
            job: nextJob,
            message: "Applying approved changes…",
          }),
      );
      const authoritative = await refreshSuperDocsDocuments(
        session.sessionId,
        controller.signal,
      );
      const selectedDocument = authoritative.find(
        (document) => document.documentId === target.documentId,
      );
      if (!selectedDocument?.html) {
        throw new Error(
          "SuperDocs completed the edit but did not return HTML for the selected document.",
        );
      }

      onWorkspaceChange(
        applyPolicyEditOutcome(workspace, {
          kind: "approved",
          documentType: target.documentType,
          html: selectedDocument.html,
        }),
      );
      setSuperDocsDocuments(
        (current) => new Set([...current, target.documentType]),
      );
      setInstruction("");
      setEditState({
        stage: "completed",
        message: `${DOCUMENT_TITLES[target.documentType]} updated from SuperDocs`,
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        setEditState({ stage: "error", message: errorMessage(error) });
      }
    }
  }

  async function handleProposeSynchronizedUpdate() {
    if (operationBusy) {
      return;
    }
    const nextValue = Number(returnWindowInput);
    const proposed = proposeReturnWindowChangeSet(workspace, nextValue);
    if (!proposed.ok) {
      setSynchronizedState({
        stage: "error",
        message: proposed.error.message,
      });
      return;
    }

    const changeSet = proposed.value;
    const controller = beginOperation(operationControllersRef.current);
    setSynchronizedState({ stage: "preparing", changeSet });

    try {
      const currentSession = await ensureSession(controller.signal);
      const started = await startSuperDocsSynchronizedChange(
        {
          sessionId: currentSession.sessionId,
          documentIds: currentSession.documentIds,
          changeSet,
        },
        controller.signal,
      );
      setSynchronizedState({
        stage: "processing",
        changeSet,
        preEditState: started.preEditState,
        jobs: started.jobs,
      });

      // Poll every targeted job independently. Each job's own gate
      // (targeting safety + managed-fact coverage) runs server-side the
      // moment that job reaches awaiting_approval, so a rejection here means
      // that one document's batch was already denied.
      const settled = await Promise.allSettled(
        started.jobs.map((targeted) =>
          pollUntilTargetedSynchronizedReview(
            targeted.job,
            currentSession,
            targeted.documentType,
            changeSet,
            controller.signal,
            (nextJob) =>
              setSynchronizedState((current) =>
                withUpdatedJob(current, targeted.documentType, nextJob),
              ),
          ).then((job): SuperDocsTargetedJob => ({
            documentType: targeted.documentType,
            job,
          })),
        ),
      );

      const fulfilled = settled
        .filter(
          (result): result is PromiseFulfilledResult<SuperDocsTargetedJob> =>
            result.status === "fulfilled",
        )
        .map((result) => result.value);
      const rejectedIndex = settled.findIndex(
        (result) => result.status === "rejected",
      );

      if (rejectedIndex !== -1) {
        // At least one document's batch failed its own gate (or the job
        // itself failed). Deny every OTHER job that reached awaiting_review
        // with a passing gate — the synchronized ChangeSet is unsafe as a
        // whole even though that job's own batch was individually fine.
        await denyAwaitingJobs(
          fulfilled,
          currentSession,
          changeSet,
          controller.signal,
        );
        const failedDocumentType = started.jobs[rejectedIndex]?.documentType;
        const reason = (settled[rejectedIndex] as PromiseRejectedResult)
          .reason;
        markSynchronizedFailed(
          changeSet,
          `${failedDocumentType ? `${DOCUMENT_TITLES[failedDocumentType]}: ` : ""}${errorMessage(reason)}`,
        );
        return;
      }

      const emptyBatch = fulfilled.find(
        (targeted) => targeted.job.status === "completed",
      );
      if (emptyBatch) {
        await denyAwaitingJobs(
          fulfilled.filter((targeted) => targeted !== emptyBatch),
          currentSession,
          changeSet,
          controller.signal,
        );
        markSynchronizedFailed(
          changeSet,
          `SuperDocs completed the ${DOCUMENT_TITLES[emptyBatch.documentType]} job without a reviewable proposal. The canonical return window remains unchanged.`,
        );
        return;
      }

      setSynchronizedState({
        stage: "awaiting_review",
        changeSet,
        preEditState: started.preEditState,
        jobs: fulfilled,
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        markSynchronizedFailed(changeSet, errorMessage(error));
      }
    }
  }

  async function handleSynchronizedReview(approved: boolean) {
    if (
      !session ||
      synchronizedState.stage !== "awaiting_review" ||
      synchronizedState.jobs.some((targeted) => targeted.job.proposals.length === 0)
    ) {
      return;
    }
    const { changeSet, jobs, preEditState } = synchronizedState;
    const controller = beginOperation(operationControllersRef.current);
    setSynchronizedState({
      stage: "applying",
      changeSet,
      preEditState,
      jobs,
      message: approved
        ? "Applying the approved synchronized update…"
        : "Rejecting every proposed change across both jobs…",
    });

    try {
      // Submit the same decision for every targeted job's own pending
      // changes. These are two independent SuperDocs jobs, not one atomic
      // transaction, so track each submission's outcome separately.
      const decisions = await Promise.allSettled(
        jobs.map((targeted) =>
          submitSuperDocsSynchronizedReview(
            {
              sessionId: session.sessionId,
              jobId: targeted.job.jobId,
              documentType: targeted.documentType,
              documentIds: session.documentIds,
              changeSet,
              approved,
            },
            controller.signal,
          ),
        ),
      );

      if (!approved) {
        const rejected = rejectSynchronizedChangeSet(workspace, changeSet);
        if (!rejected.ok) {
          throw new Error(rejected.error.message);
        }
        setSynchronizedState({
          stage: "rejected",
          changeSet: rejected.value.changeSet,
          message:
            "Update rejected. Every proposal was denied across both jobs and the canonical return window remains unchanged.",
        });
        return;
      }

      const decisionFailure = decisions.find(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      if (decisionFailure) {
        throw new Error(
          `Approval could not be submitted for one document's SuperDocs job (${errorMessage(decisionFailure.reason)}). This is a partial-apply condition: nothing was committed, but the other document's job may already have applied its edit and could require manual recovery.`,
        );
      }

      const approvedChangeSet = approveSynchronizedChangeSet(changeSet);
      if (!approvedChangeSet.ok) {
        throw new Error(approvedChangeSet.error.message);
      }
      const approvedValue = approvedChangeSet.value;

      const completions = await Promise.allSettled(
        jobs.map((targeted) =>
          pollUntilTargetedSynchronizedCompleted(
            targeted.job,
            session,
            targeted.documentType,
            approvedValue,
            controller.signal,
          ),
        ),
      );
      const completionFailureIndex = completions.findIndex(
        (result) => result.status === "rejected",
      );
      if (completionFailureIndex !== -1) {
        const failedDocumentType = jobs[completionFailureIndex]?.documentType;
        const reason = (
          completions[completionFailureIndex] as PromiseRejectedResult
        ).reason;
        throw new Error(
          `SuperDocs did not finish applying the approved update${failedDocumentType ? ` for ${DOCUMENT_TITLES[failedDocumentType]}` : ""} (${errorMessage(reason)}). This is a partial-apply condition: two SuperDocs jobs are not one atomic transaction, so the other document's edit may already be applied. Nothing was committed to the canonical PolicyProfile; document state may require manual recovery.`,
        );
      }

      const authoritative = await refreshSuperDocsDocuments(
        session.sessionId,
        controller.signal,
      );
      const completed = commitValidatedSynchronizedChange(
        workspace,
        approvedValue,
        preEditState,
        authoritative,
        session.documentIds,
      );
      if (!completed.ok) {
        markSynchronizedFailed(approvedValue, completed.error.message);
        return;
      }

      onWorkspaceChange(completed.value.workspace);
      setSuperDocsDocuments(
        (current) =>
          new Set([
            ...current,
            ...completed.value.changeSet.affectedDocuments,
          ]),
      );
      setReturnWindowInput(
        String(completed.value.workspace.profile.returns.windowDays),
      );
      setSynchronizedState({
        stage: "synchronized",
        changeSet: completed.value.changeSet,
        unchangedDocuments: completed.value.unchangedDocuments,
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        markSynchronizedFailed(changeSet, errorMessage(error));
      }
    }
  }

  function markSynchronizedFailed(
    changeSet: ChangeSet,
    message: string,
  ) {
    const failed = failSynchronizedChangeSet(workspace, changeSet);
    setSynchronizedState({
      stage: "failed",
      changeSet: failed.ok ? failed.value.changeSet : changeSet,
      message,
    });
  }

  async function denyAwaitingJobs(
    jobs: readonly SuperDocsTargetedJob[],
    currentSession: SuperDocsWorkspaceSession,
    changeSet: ChangeSet,
    signal: AbortSignal,
  ): Promise<void> {
    await Promise.allSettled(
      jobs
        .filter(
          (targeted) =>
            targeted.job.status === "awaiting_approval" &&
            targeted.job.proposals.length > 0,
        )
        .map((targeted) =>
          submitSuperDocsSynchronizedReview(
            {
              sessionId: currentSession.sessionId,
              jobId: targeted.job.jobId,
              documentType: targeted.documentType,
              documentIds: currentSession.documentIds,
              changeSet,
              approved: false,
            },
            signal,
          ),
        ),
    );
  }

  const activeChangeSet = activeSynchronizedChangeSet(synchronizedState);
  const reviewingCount = synchronizedBusy
    ? (activeChangeSet?.affectedDocuments.length ?? 0)
    : editBusy
      ? 1
      : 0;

  const documentStatuses = deriveDocumentStatuses({
    workspace,
    editState,
    synchronizedState,
    superDocsDocuments,
  });

  const inspector: ReactNode =
    editState.stage === "awaiting_review" ? (
      <EditReviewPanel
        state={editState}
        onApprove={() => handleReview(true)}
        onReject={() => handleReview(false)}
      />
    ) : (
      <PolicyFactsPanel
        profile={profile}
        returnWindowInput={returnWindowInput}
        disabled={operationBusy}
        proposeError={
          synchronizedState.stage === "error" ? synchronizedState.message : null
        }
        onReturnWindowInputChange={(value) => {
          if (synchronizedState.stage === "error") {
            setSynchronizedState({ stage: "idle" });
          }
          setReturnWindowInput(value);
        }}
        onProposeReturnWindow={handleProposeSynchronizedUpdate}
      />
    );

  const navigation = (
    <DocumentRail
      active={activeTab}
      statuses={documentStatuses}
      disabled={operationBusy}
      onSelect={(documentType) => {
        setActiveTab(documentType);
        setNavOpen(false);
      }}
    />
  );

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <AppHeader
        context={profile.company.legalName}
        leading={
          <Button
            variant="quiet"
            size="icon"
            className="lg:hidden"
            aria-label="Open policy documents"
            onClick={() => setNavOpen(true)}
          >
            <PanelLeft />
          </Button>
        }
      >
        <ConsistencyStatus
          validation={validation}
          reviewingCount={reviewingCount}
        />
        <Separator orientation="vertical" className="mx-1 h-4" />
        <ExportControl
          hasSession={session !== null}
          disabled={session === null || editBusy || synchronizedBusy}
          exportingFormat={exportingFormat}
          documentTitle={DOCUMENT_TITLES[activeTab]}
          onExport={handleExport}
        />
        <Button variant="quiet" size="sm" onClick={onEditIntake}>
          <SquarePen />
          <span className="hidden sm:inline">Edit intake</span>
        </Button>
        <Button
          variant="quiet"
          size="icon"
          className="xl:hidden"
          aria-label="Open policy facts"
          onClick={() => setInspectorOpen(true)}
        >
          <PanelRight />
        </Button>
      </AppHeader>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[15.5rem] shrink-0 border-r border-line bg-chrome lg:block">
          {navigation}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8 sm:py-10">
            <div className="mx-auto mb-3 w-full max-w-[46rem]">
              <p className="text-right text-[11px] font-medium uppercase tracking-[0.09em] text-faint">
                {superDocsDocuments.has(activeTab)
                  ? "Edited in SuperDocs"
                  : "Deterministic draft"}
              </p>
            </div>
            <DocumentPreview
              documentType={activeTab}
              html={documents[activeTab]}
              profile={profile}
              source={
                superDocsDocuments.has(activeTab)
                  ? "superdocs"
                  : "deterministic"
              }
            />
          </div>

          <AiCommandBar
            documentTitle={DOCUMENT_TITLES[activeTab]}
            connectionState={connectionState}
            connectionError={connectionError}
            hasSession={session !== null}
            instruction={instruction}
            busy={operationBusy}
            status={
              <>
                {exportError ? (
                  <div
                    className="flex items-center gap-2 rounded-[var(--radius-control)] border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger"
                    role="alert"
                  >
                    <TriangleAlert className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1">{exportError}</span>
                    <Button
                      variant="quiet"
                      size="sm"
                      onClick={() => setExportError(null)}
                    >
                      Dismiss
                    </Button>
                  </div>
                ) : null}
                {exportWarning ? (
                  <div
                    className="flex items-center gap-2 rounded-[var(--radius-control)] border border-warn-line bg-warn-soft px-3 py-2 text-[13px] text-warn"
                    role="status"
                  >
                    <TriangleAlert className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1">{exportWarning}</span>
                    <Button
                      variant="quiet"
                      size="sm"
                      onClick={() => setExportWarning(null)}
                    >
                      Dismiss
                    </Button>
                  </div>
                ) : null}
                <EditStatusLine
                  state={editState}
                  onDismiss={() => setEditState({ stage: "idle" })}
                />
                {editState.stage === "awaiting_review" ? (
                  <div className="flex items-center gap-2 rounded-[var(--radius-control)] border border-warn-line bg-warn-soft px-3 py-2 text-[13px] text-warn xl:hidden">
                    <span className="flex-1">
                      {editState.job.proposals.length} proposed{" "}
                      {editState.job.proposals.length === 1
                        ? "change"
                        : "changes"}{" "}
                      awaiting review
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setInspectorOpen(true)}
                    >
                      Review
                    </Button>
                  </div>
                ) : null}
              </>
            }
            onInstructionChange={setInstruction}
            onSubmit={handleProposeEdit}
            onConnect={handleInitialize}
          />
        </main>

        <aside className="hidden w-[20.5rem] shrink-0 border-l border-line bg-chrome xl:block">
          {inspector}
        </aside>
      </div>

      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent side="left" className="p-0">
          <SheetTitle className="sr-only">Policy documents</SheetTitle>
          <SheetDescription className="sr-only">
            Select which policy document to work on.
          </SheetDescription>
          {navigation}
        </SheetContent>
      </Sheet>

      <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <SheetContent side="right" className="w-[21rem] p-0">
          <SheetTitle className="sr-only">Policy facts</SheetTitle>
          <SheetDescription className="sr-only">
            Canonical facts shared across the policy set.
          </SheetDescription>
          {inspector}
        </SheetContent>
      </Sheet>

      <SynchronizedReviewDialog
        state={synchronizedState}
        onApprove={() => handleSynchronizedReview(true)}
        onReject={() => handleSynchronizedReview(false)}
        onDismiss={() => setSynchronizedState({ stage: "idle" })}
      />
    </div>
  );
}

/** Derives per-document rail state from real workspace, edit and job state. */
function deriveDocumentStatuses({
  workspace,
  editState,
  synchronizedState,
  superDocsDocuments,
}: {
  workspace: PolicyWorkspaceState;
  editState: EditState;
  synchronizedState: SynchronizedState;
  superDocsDocuments: ReadonlySet<PolicyDocumentType>;
}): Record<PolicyDocumentType, DocumentStatus> {
  const statuses = {} as Record<PolicyDocumentType, DocumentStatus>;

  for (const documentType of POLICY_DOCUMENT_TYPES) {
    statuses[documentType] = superDocsDocuments.has(documentType)
      ? "updated"
      : "idle";
  }

  if (isEditBusy(editState.stage) && "target" in editState) {
    statuses[editState.target.documentType] =
      editState.stage === "awaiting_review" ? "review" : "working";
  }

  if (isSynchronizedBusy(synchronizedState.stage)) {
    const changeSet = activeSynchronizedChangeSet(synchronizedState);
    for (const documentType of changeSet?.affectedDocuments ?? []) {
      statuses[documentType] =
        synchronizedState.stage === "awaiting_review" ? "review" : "working";
    }
  }

  for (const issue of workspace.validation.issues) {
    for (const documentType of issue.documents ?? []) {
      statuses[documentType] = "issue";
    }
  }

  return statuses;
}

async function pollUntilReview(
  initialJob: SuperDocsJobView,
  session: SuperDocsWorkspaceSession,
  target: EditTarget,
  signal: AbortSignal,
  onProgress: (job: SuperDocsJobView) => void,
): Promise<SuperDocsJobView> {
  let job = initialJob;
  while (true) {
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(jobFailureMessage(job));
    }
    if (job.status === "awaiting_approval" && job.proposals.length > 0) {
      return job;
    }
    await pollDelay(signal);
    job = await getSuperDocsJob(
      {
        jobId: job.jobId,
        sessionId: session.sessionId,
        documentId: target.documentId,
      },
      signal,
    );
    onProgress(job);
  }
}

async function pollUntilCompleted(
  initialJob: SuperDocsJobView,
  session: SuperDocsWorkspaceSession,
  target: EditTarget,
  signal: AbortSignal,
  onProgress: (job: SuperDocsJobView) => void,
): Promise<void> {
  let job = initialJob;
  while (job.status !== "completed") {
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(jobFailureMessage(job));
    }
    await pollDelay(signal);
    job = await getSuperDocsJob(
      {
        jobId: job.jobId,
        sessionId: session.sessionId,
        documentId: target.documentId,
      },
      signal,
    );
    onProgress(job);
  }
}

/**
 * Polls one targeted (pinned) synchronized job for that document. When the
 * server response reports `awaiting_approval` with proposals, PolicySet's
 * server-side gate for that document has already run (and passed) inside
 * `getPolicyTargetedSynchronizedJob` — a gate failure surfaces here as a
 * rejected fetch, which this function lets propagate to the caller.
 */
async function pollUntilTargetedSynchronizedReview(
  initialJob: SuperDocsJobView,
  session: SuperDocsWorkspaceSession,
  documentType: PolicyDocumentType,
  changeSet: ChangeSet,
  signal: AbortSignal,
  onProgress: (job: SuperDocsJobView) => void,
): Promise<SuperDocsJobView> {
  let job = initialJob;
  while (true) {
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(jobFailureMessage(job));
    }
    if (job.status === "awaiting_approval" && job.proposals.length > 0) {
      return job;
    }
    await pollDelay(signal);
    job = await getSuperDocsSynchronizedJob(
      {
        jobId: job.jobId,
        sessionId: session.sessionId,
        documentType,
        documentIds: session.documentIds,
        changeSet,
      },
      signal,
    );
    onProgress(job);
  }
}

async function pollUntilTargetedSynchronizedCompleted(
  initialJob: SuperDocsJobView,
  session: SuperDocsWorkspaceSession,
  documentType: PolicyDocumentType,
  changeSet: ChangeSet,
  signal: AbortSignal,
): Promise<void> {
  let job = initialJob;
  while (job.status !== "completed") {
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(jobFailureMessage(job));
    }
    await pollDelay(signal);
    job = await getSuperDocsSynchronizedJob(
      {
        jobId: job.jobId,
        sessionId: session.sessionId,
        documentType,
        documentIds: session.documentIds,
        changeSet,
      },
      signal,
    );
  }
}

function beginOperation(controllers: Set<AbortController>): AbortController {
  controllers.forEach((controller) => controller.abort());
  controllers.clear();
  const controller = new AbortController();
  controllers.add(controller);
  return controller;
}

function pollDelay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const handleAbort = () => {
      window.clearTimeout(timeout);
      reject(new DOMException("Operation aborted", "AbortError"));
    };
    const timeout = window.setTimeout(() => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    }, 1_500);
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

function jobFailureMessage(job: SuperDocsJobView): string {
  return job.errorCode
    ? `SuperDocs could not complete the edit (${job.errorCode}).`
    : "SuperDocs could not complete the edit.";
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The SuperDocs operation could not be completed.";
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
