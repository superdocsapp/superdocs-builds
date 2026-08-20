"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { reviewFinding } from "@/lib/api/submittals";
import { Dialog, DialogContent, DialogClose } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import type { Finding, ReviewDecision } from "@/lib/api/types";

interface ReviewModalProps {
  finding: Finding;
  submittalNumber: string;
  open: boolean;
  onClose: () => void;
}

const DECISIONS: { value: ReviewDecision; label: string; description: string }[] = [
  { value: "APPROVE", label: "Approve", description: "Accept this finding as reviewed." },
  { value: "REJECT", label: "Reject", description: "Reject this finding." },
  {
    value: "REQUEST_CLARIFICATION",
    label: "Request Clarification",
    description: "Hold this finding pending further information.",
  },
];

export function ReviewModal({
  finding,
  submittalNumber,
  open,
  onClose,
}: ReviewModalProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const defaultReviewer =
    typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_DEV_REVIEWER ?? "Reviewer"
      : "Reviewer";

  const [decision, setDecision] = useState<ReviewDecision>("APPROVE");
  const [reviewer, setReviewer] = useState(defaultReviewer);
  const [comment, setComment] = useState("");
  const [reviewerError, setReviewerError] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      reviewFinding(finding.id, {
        reviewer: reviewer.trim(),
        decision,
        comment: comment.trim() || null,
      }),
    onSuccess: () => {
      toast({ title: "Finding reviewed.", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["submittal", submittalNumber] });
      queryClient.invalidateQueries({ queryKey: ["register"] });
      onClose();
    },
    onError: (err: Error) => {
      toast({
        title: "Review failed.",
        description: err.message,
        variant: "error",
      });
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reviewer.trim()) {
      setReviewerError("Reviewer name is required.");
      return;
    }
    setReviewerError("");
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        title="Review Finding"
        description={`${finding.attribute} · ${finding.result}`}
      >
        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          {/* Decision */}
          <fieldset>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Decision
            </legend>
            <div className="space-y-2">
              {DECISIONS.map((d) => (
                <label
                  key={d.value}
                  className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors ${
                    decision === d.value
                      ? "border-blue-500 bg-blue-50"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <input
                    type="radio"
                    name="decision"
                    value={d.value}
                    checked={decision === d.value}
                    onChange={() => setDecision(d.value)}
                    className="mt-0.5 accent-blue-600"
                  />
                  <div>
                    <p className="text-sm font-medium text-slate-800">{d.label}</p>
                    <p className="text-xs text-slate-500">{d.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </fieldset>

          {/* Reviewer */}
          <div>
            <label
              htmlFor="reviewer"
              className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500"
            >
              Reviewer
            </label>
            <input
              id="reviewer"
              type="text"
              value={reviewer}
              onChange={(e) => {
                setReviewer(e.target.value);
                setReviewerError("");
              }}
              className={`w-full rounded-md border px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                reviewerError ? "border-red-400" : "border-slate-300"
              }`}
              aria-describedby={reviewerError ? "reviewer-error" : undefined}
              aria-required="true"
            />
            {reviewerError && (
              <p id="reviewer-error" className="mt-1 text-xs text-red-600" role="alert">
                {reviewerError}
              </p>
            )}
          </div>

          {/* Comment */}
          <div>
            <label
              htmlFor="comment"
              className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500"
            >
              Comment{" "}
              <span className="font-normal text-slate-400 lowercase tracking-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Notes about this review decision…"
            />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <DialogClose asChild>
              <Button type="button" variant="secondary" onClick={onClose}>
                Cancel
              </Button>
            </DialogClose>
            <Button
              type="submit"
              variant={decision === "REJECT" ? "danger" : "primary"}
              loading={mutation.isPending}
            >
              Submit Review
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
