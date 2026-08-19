"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { FindingsPanel } from "@/components/FindingsPanel";
import { LetterPreview } from "@/components/LetterPreview";
import { ReviseBox } from "@/components/ReviseBox";
import { ExportButton } from "@/components/ExportButton";
import { wordDiff, isNoOpChange } from "@/lib/diff";
import { textFromHtml } from "@/lib/textFromHtml";
import { filenameFor } from "@/lib/filename";
import { groupChanges, type ChangeGroup } from "@/lib/groupChanges";
import type { ApproveDecision, AuditReport, Intake, PendingChange } from "@/lib/types";

interface JobView {
  job_id: string;
  session_id: string;
  status: "pending" | "in_progress" | "awaiting_approval" | "completed" | "failed" | "cancelled";
  progress?: number;
  error: string | null;
  awaitingKind: "continue_prompt" | "hitl_review" | null;
  message: string | null;
  pendingChanges: PendingChange[];
  parseProblem: string | null;
  documentHtml: string;
}

async function fetchJob(jobId: string): Promise<JobView> {
  const res = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.fix ?? body.cause ?? "Could not check draft progress.");
  }
  return res.json();
}

/**
 * Renders the change as a word-level diff over plain text.
 *
 * Deliberately not HTML. The content here was produced by a model that has just
 * read intake text a third party may have written, so rendering it as markup
 * puts an injection payload one sanitizer bug away from executing. Reference
 * letters are prose; the reviewer needs to see which words changed.
 */
function DiffBody({ change }: { change: PendingChange }) {
  const before = textFromHtml(change.old_html);
  const after = textFromHtml(change.new_html);

  if (isNoOpChange(before, after)) {
    return (
      <p className="text-muted-foreground text-sm italic">
        This change rewrites the section to the same text. Approving it costs nothing and changes nothing.
      </p>
    );
  }

  const segments = wordDiff(before, after);

  return (
    <p className="text-sm leading-relaxed">
      {segments.map((segment, i) => {
        if (segment.op === "same") return <span key={i}>{segment.text}</span>;
        if (segment.op === "removed") {
          return (
            <span key={i} className="bg-destructive/10 text-destructive line-through decoration-1">
              {segment.text}
            </span>
          );
        }
        return (
          <span key={i} className="bg-emerald-500/15 text-emerald-800 dark:text-emerald-300">
            {segment.text}
          </span>
        );
      })}
    </p>
  );
}

function DiffCard({
  group,
  decision,
  onDecide,
}: {
  group: ChangeGroup;
  decision: ApproveDecision | undefined;
  onDecide: (decision: ApproveDecision | null) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const grouped = group.changeIds.length > 1;

  return (
    <Card className={decision ? "opacity-70" : undefined}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-sm font-medium">{group.explanation}</CardTitle>
            {grouped && (
              <p className="text-muted-foreground mt-1 text-xs">
                Applies to {group.changeIds.length} identical edits — one decision covers all of them.
              </p>
            )}
          </div>
          {decision && (
            <Badge variant={decision.approved ? "default" : "secondary"}>
              {decision.approved ? "approved" : "rejected"}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <DiffBody change={group.sample} />

        {!decision && (
          <>
            <Textarea
              placeholder="Optional: why you are rejecting this, so the next pass can act on it"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={2}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => onDecide({ change_id: group.changeIds[0], approved: true })}>
                {grouped ? `Approve all ${group.changeIds.length}` : "Approve"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  onDecide({
                    change_id: group.changeIds[0],
                    approved: false,
                    feedback: feedback.trim() || undefined,
                  })
                }
              >
                {grouped ? `Reject all ${group.changeIds.length}` : "Reject"}
              </Button>
            </div>
          </>
        )}

        {decision && (
          <Button size="sm" variant="ghost" className="w-fit" onClick={() => onDecide(null)}>
            Undo
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function ReviewPanel({
  sessionId,
  jobId,
  intake,
  onCompleted,
  onRevised,
}: {
  sessionId: string;
  jobId: string;
  intake: Intake;
  onCompleted: () => void;
  onRevised: (jobId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [decisions, setDecisions] = useState<Record<string, ApproveDecision>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditReport | null>(null);
  const [auditing, setAuditing] = useState(false);
  const auditedForRef = useRef<string | null>(null);

  const { data: job, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId),
    // Backs off as the wait lengthens. A draft can legitimately run for
    // minutes, and hammering a 3s poll for five of them is wasted requests.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed" || status === "cancelled") return false;
      if (status === "awaiting_approval") return false;
      return Math.min(15_000, 2500 + query.state.dataUpdateCount * 750);
    },
    retry: 3,
  });

  const pendingChanges = useMemo(() => job?.pendingChanges ?? [], [job]);
  const changeGroups = useMemo(() => groupChanges(pendingChanges), [pendingChanges]);
  const memoryKey = intake.writerEmail || intake.writerName;

  const letterPreview = useMemo(() => {
    if (job?.status === "completed" && job.documentHtml) {
      return { html: job.documentHtml, final: true };
    }
    if (pendingChanges.length) {
      return { html: pendingChanges.map((c) => c.new_html).join("\n"), final: false };
    }
    return { html: "", final: false };
  }, [job, pendingChanges]);

  // Fingerprint the proposal so the audit runs once per distinct proposal, not
  // once per poll. Auditing costs a verifier call.
  const proposalKey = useMemo(() => pendingChanges.map((c) => c.change_id).join("|"), [pendingChanges]);

  const runAudit = useCallback(async () => {
    if (!pendingChanges.length) return;
    setAuditing(true);
    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intake,
          letterHtml: pendingChanges.map((c) => c.new_html).join("\n"),
        }),
      });
      if (res.ok) setAudit(await res.json());
    } catch {
      // The audit is additive. A failure here must not block the review.
    } finally {
      setAuditing(false);
    }
  }, [pendingChanges, intake]);

  useEffect(() => {
    if (proposalKey && proposalKey !== auditedForRef.current) {
      auditedForRef.current = proposalKey;
      void runAudit();
    }
  }, [proposalKey, runAudit]);

  useEffect(() => {
    if (job?.status === "completed") onCompleted();
  }, [job?.status, onCompleted]);

  const allDecided = pendingChanges.length > 0 && pendingChanges.every((c) => decisions[c.change_id]);

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, jobId, decisions: Object.values(decisions) }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.fix ?? body.cause ?? "Could not submit your decisions.");
      setDecisions({});
      setAudit(null);
      auditedForRef.current = null;
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Could not submit your decisions.");
    } finally {
      setSubmitting(false);
    }
  }

  async function answerContinue(proceed: boolean) {
    setSubmitting(true);
    try {
      await fetch("/api/continue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, jobId, proceed }),
      });
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-4">
          <p className="text-destructive text-sm">{(error as Error).message}</p>
          <p className="text-muted-foreground mt-2 text-sm">
            The draft is still running on SuperDocs and this session id is still valid. Reloading the page
            resumes the review.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!job || job.status === "pending" || job.status === "in_progress") {
    return (
      <div className="text-muted-foreground flex flex-col gap-2 text-sm">
        <p>Drafting. This can take anywhere from thirty seconds to a few minutes.</p>
        {typeof job?.progress === "number" && <p>Progress: {job.progress}%</p>}
        <p className="text-xs">
          You can close this tab. The draft keeps running, and reopening the page resumes the review.
        </p>
      </div>
    );
  }

  if (job.status === "failed" || job.status === "cancelled") {
    return (
      <Card>
        <CardContent className="py-4">
          <p className="text-destructive text-sm">
            The draft {job.status}: {job.error ?? "no reason given"}
          </p>
          <p className="text-muted-foreground mt-2 text-sm">Nothing was written to the letter.</p>
        </CardContent>
      </Card>
    );
  }

  if (job.awaitingKind === "continue_prompt") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-medium">This edit is larger than one pass</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-muted-foreground text-sm">
            {job.message ?? "SuperDocs is asking whether to keep going. Continuing costs another operation."}
          </p>
          <div className="flex gap-2">
            <Button size="sm" disabled={submitting} onClick={() => answerContinue(true)}>
              Continue
            </Button>
            <Button size="sm" variant="outline" disabled={submitting} onClick={() => answerContinue(false)}>
              Stop here
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (job.status === "completed") {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-muted-foreground text-sm">
          Everything you approved has been written. Nothing you rejected was applied.
        </p>
        <LetterPreview html={letterPreview.html} final={letterPreview.final} />
        <ExportButton sessionId={sessionId} filename={filenameFor(intake.subjectName)} />
        <ReviseBox sessionId={sessionId} memoryKey={memoryKey} onRevised={onRevised} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <FindingsPanel report={audit} loading={auditing} />
      <LetterPreview html={letterPreview.html} final={letterPreview.final} />

      {job.parseProblem && (
        <Card>
          <CardContent className="py-3">
            <p className="text-destructive text-sm">{job.parseProblem}</p>
          </CardContent>
        </Card>
      )}

      <p className="text-muted-foreground text-sm">
        {pendingChanges.length} proposed change{pendingChanges.length === 1 ? "" : "s"}
        {changeGroups.length !== pendingChanges.length ? `, grouped into ${changeGroups.length} to review` : ""}.
        Nothing is written to the letter until you submit. Rejecting one does not discard the others.
      </p>

      {changeGroups.map((group) => (
        <DiffCard
          key={group.key}
          group={group}
          decision={decisions[group.changeIds[0]]}
          onDecide={(decision) =>
            setDecisions((prev) => {
              const next = { ...prev };
              for (const id of group.changeIds) {
                if (decision === null) delete next[id];
                else next[id] = { ...decision, change_id: id };
              }
              return next;
            })
          }
        />
      ))}

      {submitError && <p className="text-destructive text-sm">{submitError}</p>}

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!allDecided || submitting}>
          {submitting
            ? "Submitting…"
            : `Submit ${Object.values(decisions).filter((d) => d.approved).length} approved, ${
                Object.values(decisions).filter((d) => !d.approved).length
              } rejected`}
        </Button>
        {!allDecided && (
          <span className="text-muted-foreground text-sm">
            {pendingChanges.length - Object.keys(decisions).length} still to decide
          </span>
        )}
      </div>

      <ReviseBox
        sessionId={sessionId}
        memoryKey={memoryKey}
        onRevised={onRevised}
        disabled={pendingChanges.length > 0 && !allDecided}
        disabledReason="Decide on the changes above first, so a new request does not land on top of an undecided one."
      />
    </div>
  );
}
