"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getSubmittalDetail, runWorkflow, updateRegisterStatus } from "@/lib/api/submittals";
import { createTransmittal } from "@/lib/api/transmittals";
import { RegisterStatusBadge, TechnicalStatusBadge } from "@/components/ui/Badge";
import { SkeletonCard, Skeleton } from "@/components/ui/Skeleton";
import { FindingCard } from "@/components/submittals/FindingCard";
import { ReviewProgress } from "@/components/submittals/ReviewProgress";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  FileCheck,
  FileStack,
  Play,
  RefreshCcw,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatDate, daysUntil } from "@/lib/utils";
import type { RegisterStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const REGISTER_STATUSES: { value: RegisterStatus; label: string }[] = [
  { value: "NOT_RECEIVED", label: "Not received" },
  { value: "RECEIVED", label: "Received" },
  { value: "UNDER_REVIEW", label: "Under review" },
  { value: "REVIEWED", label: "Reviewed" },
  { value: "OVERDUE", label: "Overdue" },
];

/** Workflow steps for the progress indicator */
const WORKFLOW_STEPS = [
  { key: "register", label: "Register" },
  { key: "documents", label: "Documents" },
  { key: "comparison", label: "Comparison" },
  { key: "review", label: "Review" },
  { key: "transmittal", label: "Transmittal" },
] as const;

function getWorkflowStep(
  submittal: {
    register_status: string;
    status: string;
    transmittal: unknown;
    findings: { result: string; status: string }[];
  },
): number {
  const findings = submittal.findings ?? [];
  const hasTransmittal = !!submittal.transmittal;
  const allReviewed =
    findings.length > 0 &&
    findings.every(
      (f) => f.status === "APPROVED" || f.status === "REJECTED",
    );

  if (hasTransmittal) return 5; // transmittal
  if (allReviewed) return 4; // review
  if (findings.length > 0) return 3; // comparison
  if (submittal.register_status !== "NOT_RECEIVED") return 2; // documents
  return 1; // register
}

function WorkflowProgress({ currentStep }: { currentStep: number }) {
  return (
    <nav aria-label="Submittal workflow progress" className="w-full">
      <ol className="flex items-center gap-0" role="list">
        {WORKFLOW_STEPS.map((step, idx) => {
          const isCompleted = idx + 1 < currentStep;
          const isCurrent = idx + 1 === currentStep;
          const isUpcoming = idx + 1 > currentStep;
          return (
            <li
              key={step.key}
              className={cn("flex items-center", idx < WORKFLOW_STEPS.length - 1 && "flex-1")}
            >
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold border-2 transition-colors",
                    isCompleted && "bg-blue-600 border-blue-600 text-white",
                    isCurrent && "bg-white border-blue-600 text-blue-700 ring-2 ring-blue-100",
                    isUpcoming && "bg-white border-slate-200 text-slate-400",
                  )}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    idx + 1
                  )}
                </span>
                <span
                  className={cn(
                    "text-xs font-medium hidden sm:inline",
                    isCompleted && "text-blue-700",
                    isCurrent && "text-blue-700",
                    isUpcoming && "text-slate-400",
                  )}
                >
                  {step.label}
                </span>
              </div>
              {idx < WORKFLOW_STEPS.length - 1 && (
                <div
                  className={cn(
                    "mx-1.5 h-0.5 flex-1 rounded-full",
                    isCompleted ? "bg-blue-600" : "bg-slate-200",
                  )}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default function SubmittalDetailPage({
  params,
}: {
  params: { projectId: string; submittalNumber: string };
}) {
  const { submittalNumber } = params;
  const router = useRouter();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const {
    data: submittal,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["submittal", submittalNumber],
    queryFn: () => getSubmittalDetail(submittalNumber),
  });

  const statusMutation = useMutation({
    mutationFn: (status: RegisterStatus) =>
      updateRegisterStatus(submittalNumber, status),
    onSuccess: () => {
      toast({ title: "Register status updated.", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["submittal", submittalNumber] });
      queryClient.invalidateQueries({ queryKey: ["register"] });
    },
    onError: (err: Error) => {
      toast({
        title: "Status update failed.",
        description: err.message,
        variant: "error",
      });
    },
  });

  const runWorkflowMutation = useMutation({
    mutationFn: () =>
      runWorkflow({
        submittal_number: submittalNumber,
        specification_section: submittal?.specification_section,
      }),
    onSuccess: () => {
      toast({ title: "Workflow completed. Findings generated.", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["submittal", submittalNumber] });
    },
    onError: (err: Error) => {
      toast({
        title: "Workflow failed.",
        description: err.message,
        variant: "error",
      });
    },
  });

  const createTransmittalMutation = useMutation({
    mutationFn: () => createTransmittal(submittalNumber),
    onSuccess: (data) => {
      toast({ title: "Transmittal created.", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["submittal", submittalNumber] });
      router.push(`/transmittals/${data.transmittal_id}`);
    },
    onError: (err: Error) => {
      toast({
        title: "Could not create transmittal.",
        description: err.message,
        variant: "error",
      });
    },
  });

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load submittal</h2>
        <p className="text-sm text-slate-500">The server returned an error.</p>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  const findings = submittal?.findings ?? [];
  const totalFindings = findings.length;
  const matches = findings.filter((f) => f.result === "MATCH").length;
  const deviations = findings.filter((f) => f.result === "DEVIATION").length;
  const pending = findings.filter(
    (f) => f.status === "PENDING_REVIEW" || f.status === "CLARIFICATION_REQUESTED",
  ).length;
  const reviewed = findings.filter(
    (f) => f.status === "APPROVED" || f.status === "REJECTED",
  ).length;
  const allReviewed = totalFindings > 0 && pending === 0;
  const hasTransmittal = !!submittal?.transmittal;
  const days = submittal ? daysUntil(submittal.due_date) : null;
  const workflowStep = submittal ? getWorkflowStep(submittal) : 0;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      {/* Back */}
      <Link
        href={`/projects/${params.projectId}/submittals`}
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Submittal Register
      </Link>

      {/* Workflow Progress */}
      {!isLoading && totalFindings > 0 && (
        <WorkflowProgress currentStep={workflowStep} />
      )}

      {/* Header */}
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-7 w-36" />
          <Skeleton className="h-5 w-64" />
          <div className="flex gap-2 mt-2">
            <Skeleton className="h-6 w-24 rounded-full" />
            <Skeleton className="h-6 w-20 rounded-full" />
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div>
            <div className="flex items-baseline gap-2 flex-wrap">
              <h1 className="text-2xl font-semibold text-slate-900">
                {submittal!.number}
              </h1>
              <span className="text-slate-400">—</span>
              <span className="text-xl text-slate-700">{submittal!.title}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500 font-mono">
              {submittal!.specification_section}
              {submittal!.specification_revision &&
                ` · ${submittal!.specification_revision}`}
            </p>
          </div>

          {/* Status badges + register status control */}
          <div className="flex flex-wrap items-center gap-3">
            <RegisterStatusBadge status={submittal!.register_status} />
            <TechnicalStatusBadge status={submittal!.status} />

            {/* Inline status update */}
            <div className="flex items-center gap-1.5 ml-2">
              <label
                htmlFor="register-status-select"
                className="text-xs text-slate-400 font-medium"
              >
                Update status:
              </label>
              <select
                id="register-status-select"
                value={submittal!.register_status}
                disabled={statusMutation.isPending}
                onChange={(e) =>
                  statusMutation.mutate(e.target.value as RegisterStatus)
                }
                className="h-7 rounded border border-slate-300 bg-white px-2 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                aria-label="Update register status"
              >
                {REGISTER_STATUSES.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              {statusMutation.isPending && (
                <span className="text-xs text-slate-400 animate-pulse">
                  Saving…
                </span>
              )}
            </div>
          </div>

          {/* Transmittal CTA */}
          <div className="flex items-center gap-3 flex-wrap">
            {hasTransmittal ? (
              <Link href={`/transmittals/${submittal!.transmittal!.id}`}>
                <Button size="sm" variant="secondary">
                  <FileCheck className="h-4 w-4" aria-hidden />
                  View Transmittal
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </Link>
            ) : (
              <>
                <Button
                  size="sm"
                  disabled={!allReviewed}
                  loading={createTransmittalMutation.isPending}
                  onClick={() => createTransmittalMutation.mutate()}
                  title={
                    !allReviewed
                      ? "All findings must be reviewed first."
                      : undefined
                  }
                >
                  Create Transmittal
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Button>
                {!allReviewed && totalFindings > 0 && (
                  <p className="text-xs text-amber-600">
                    {pending} finding{pending !== 1 ? "s" : ""} must be reviewed
                    first.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Specification Requirement */}
      {isLoading ? (
        <SkeletonCard />
      ) : (
        <section aria-labelledby="spec-requirement-heading">
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            <div className="border-b border-slate-100 bg-slate-50 px-5 py-3">
              <h2
                id="spec-requirement-heading"
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
              >
                Specification Requirement
              </h2>
            </div>
            <div className="px-5 py-4 space-y-4">
              {/* Top row: section + revision */}
              <div className="flex items-center gap-3 flex-wrap">
                <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 border border-blue-200 px-2.5 py-1 text-xs font-semibold text-blue-700 font-mono">
                  Section {submittal!.specification_section}
                </span>
                {submittal!.specification_revision && (
                  <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                    {submittal!.specification_revision}
                  </span>
                )}
              </div>

              {/* Source Evidence — what the spec requires */}
              {submittal!.source_evidence && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">
                    What the specification requires
                  </p>
                  <blockquote className="border-l-3 border-blue-400 bg-blue-50/50 rounded-r-md pl-4 pr-3 py-3 text-sm text-slate-800 leading-relaxed">
                    {submittal!.source_evidence}
                  </blockquote>
                </div>
              )}

              {/* Description — what this submittal is about */}
              {submittal!.description && (
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">
                    Submittal description
                  </p>
                  <p className="text-sm text-slate-700 leading-relaxed">
                    {submittal!.description}
                  </p>
                </div>
              )}

              {/* Bottom row: who, what form, when */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2 border-t border-slate-100">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">
                    Responsible party
                  </p>
                  <p className="text-sm font-medium text-slate-800">
                    {submittal!.required_by ?? "—"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">
                    Required submission form
                  </p>
                  <p className="text-sm font-medium text-slate-800">
                    {submittal!.required_form ?? "—"}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">
                    Due date
                  </p>
                  <div className="flex items-center gap-2">
                    <span
                      className={
                        submittal!.register_status === "OVERDUE"
                          ? "text-sm font-medium text-red-600"
                          : "text-sm font-medium text-slate-800"
                      }
                    >
                      {formatDate(submittal!.due_date)}
                    </span>
                    {submittal!.register_status === "OVERDUE" && days !== null && (
                      <span className="flex items-center gap-1 text-xs text-red-500">
                        <CalendarClock className="h-3 w-3" aria-hidden />
                        {Math.abs(days)} day{Math.abs(days) !== 1 ? "s" : ""} overdue
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Review summary stats */}
      {!isLoading && totalFindings > 0 && (
        <section aria-labelledby="review-summary-heading">
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            <div className="border-b border-slate-100 bg-slate-50 px-5 py-3">
              <h2
                id="review-summary-heading"
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
              >
                Review Summary
              </h2>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-slate-100 px-0">
              {[
                {
                  label: "Total findings",
                  value: totalFindings,
                  icon: null,
                  color: "text-slate-800",
                },
                {
                  label: "Matches",
                  value: matches,
                  icon: (
                    <CheckCircle2
                      className="h-4 w-4 text-green-500"
                      aria-hidden
                    />
                  ),
                  color: "text-green-700",
                },
                {
                  label: "Deviations",
                  value: deviations,
                  icon: (
                    <XCircle className="h-4 w-4 text-red-500" aria-hidden />
                  ),
                  color: "text-red-700",
                },
                {
                  label: "Pending review",
                  value: pending,
                  icon: (
                    <AlertTriangle
                      className="h-4 w-4 text-amber-500"
                      aria-hidden
                    />
                  ),
                  color: pending > 0 ? "text-amber-700" : "text-slate-400",
                },
              ].map(({ label, value, icon, color }) => (
                <div key={label} className="px-5 py-4 text-center">
                  <div className="flex items-center justify-center gap-1.5 mb-1">
                    {icon}
                    <span
                      className={`text-2xl font-semibold tabular-nums ${color}`}
                    >
                      {value}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Review progress bar */}
      {!isLoading && totalFindings > 0 && (
        <ReviewProgress reviewed={reviewed} total={totalFindings} />
      )}

      {/* Findings */}
      <section aria-labelledby="findings-heading">
        <h2
          id="findings-heading"
          className="mb-3 text-sm font-semibold text-slate-700"
        >
          Comparison Findings
          {!isLoading && totalFindings > 0 && (
            <span className="ml-2 font-normal text-slate-400">
              ({totalFindings})
            </span>
          )}
        </h2>
        {isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : totalFindings === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white px-5 py-12 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 mb-3">
              <FileStack className="h-6 w-6 text-slate-400" aria-hidden />
            </div>
            <p className="text-sm font-medium text-slate-700">
              No comparison findings yet
            </p>
            <p className="mt-1.5 text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
              The AI comparison engine has not been run for this submittal.
              Findings are generated when the workflow compares the specification
              requirements against the contractor&apos;s submitted product data.
            </p>
            <Button
              size="sm"
              className="mt-4"
              loading={runWorkflowMutation.isPending}
              onClick={() => runWorkflowMutation.mutate()}
            >
              <Play className="h-3.5 w-3.5" aria-hidden />
              Run Comparison Workflow
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            {findings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                submittalNumber={submittalNumber}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
