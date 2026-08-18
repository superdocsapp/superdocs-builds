"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { sanitizeHtml } from "@/lib/sanitizeHtml";
import type { ApproveDecision, JobStatusResponse, PendingChange } from "@/lib/types";

interface ReviewPanelProps {
  sessionId: string;
  jobId: string;
  onCompleted: () => void;
}

async function fetchJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch job status");
  return res.json();
}

function DiffCard({
  change,
  onDecide,
}: {
  change: PendingChange;
  onDecide: (decision: ApproveDecision) => void;
}) {
  const [decided, setDecided] = useState<"approved" | "rejected" | null>(null);
  const [feedback, setFeedback] = useState("");

  if (decided) {
    return (
      <Card>
        <CardContent className="flex items-center justify-between py-4">
          <span className="text-muted-foreground text-sm">
            {decided === "approved" ? "Approved" : "Rejected"}
          </span>
          <Badge variant={decided === "approved" ? "default" : "secondary"}>{decided}</Badge>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">{change.ai_explanation}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-muted-foreground mb-1 text-xs uppercase tracking-wide">Before</p>
            <div
              className="prose prose-sm rounded-md border bg-muted/30 p-3"
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(change.old_html) }}
            />
          </div>
          <div>
            <p className="text-muted-foreground mb-1 text-xs uppercase tracking-wide">Proposed</p>
            <div
              className="prose prose-sm rounded-md border p-3"
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(change.new_html) }}
            />
          </div>
        </div>
        <Textarea
          placeholder="Optional feedback if you reject this (the AI will retry with your note)"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={2}
        />
        <div className="flex gap-2">
          <Button
            onClick={() => {
              setDecided("approved");
              onDecide({ change_id: change.change_id, approved: true });
            }}
          >
            Approve
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              setDecided("rejected");
              onDecide({ change_id: change.change_id, approved: false, feedback: feedback || undefined });
            }}
          >
            Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function ReviewPanel({ sessionId, jobId, onCompleted }: ReviewPanelProps) {
  const queryClient = useQueryClient();
  const [submittingBatch, setSubmittingBatch] = useState(false);
  const [decisions, setDecisions] = useState<Record<string, ApproveDecision>>({});

  const { data: job, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed" || status === "cancelled") return false;
      return 3000;
    },
  });

  const pendingChanges = useMemo(() => {
    if (!job?.metadata) return [];
    if (job.metadata.awaiting_kind === "continue_prompt") return [];
    return job.metadata.pending_changes ?? [];
  }, [job]);

  const allDecided = pendingChanges.length > 0 && pendingChanges.every((c) => decisions[c.change_id]);

  useEffect(() => {
    if (job?.status === "completed") {
      onCompleted();
    }
  }, [job?.status, onCompleted]);

  async function submitDecisions() {
    setSubmittingBatch(true);
    try {
      const res = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId,
          jobId,
          decisions: Object.values(decisions),
        }),
      });
      if (!res.ok) throw new Error("Failed to submit approval");
      setDecisions({});
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } finally {
      setSubmittingBatch(false);
    }
  }

  if (error) {
    return <p className="text-destructive">Failed to load job status. It may still be processing — try again shortly.</p>;
  }

  if (!job || job.status === "pending" || job.status === "in_progress") {
    return (
      <div className="text-muted-foreground flex flex-col gap-2">
        <p>Drafting your letter… this can take up to a few minutes.</p>
        {typeof job?.progress === "number" && <p className="text-sm">Progress: {job.progress}%</p>}
      </div>
    );
  }

  if (job.status === "failed") {
    return <p className="text-destructive">Drafting failed: {job.error ?? "Unknown error"}</p>;
  }

  if (job.status === "completed") {
    return <p className="text-muted-foreground">Letter ready — see the export step.</p>;
  }

  if (job.metadata?.awaiting_kind === "continue_prompt") {
    return (
      <p className="text-muted-foreground">
        This letter is longer than a single pass — SuperDocs is asking whether to continue. Support for this isn&apos;t
        wired up in this build; try a shorter length preference.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        Review each proposed change below. Nothing is written to the final letter until you approve it.
      </p>
      {pendingChanges.map((change) => (
        <DiffCard
          key={change.change_id}
          change={change}
          onDecide={(decision) => setDecisions((prev) => ({ ...prev, [decision.change_id]: decision }))}
        />
      ))}
      <Button onClick={submitDecisions} disabled={!allDecided || submittingBatch}>
        {submittingBatch ? "Submitting…" : "Submit decisions"}
      </Button>
    </div>
  );
}
