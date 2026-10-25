"use client";

import { useState } from "react";
import { ResultBadge, FindingStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ReviewModal } from "./ReviewModal";
import { formatDateTime } from "@/lib/utils";
import type { Finding } from "@/lib/api/types";
import { CheckCircle2, XCircle, HelpCircle, Clock, AlertTriangle } from "lucide-react";

interface FindingCardProps {
  finding: Finding;
  submittalNumber: string;
}

export function FindingCard({ finding, submittalNumber }: FindingCardProps) {
  const [reviewOpen, setReviewOpen] = useState(false);

  const isPending = finding.status === "PENDING_REVIEW";
  const isClarification = finding.status === "CLARIFICATION_REQUESTED";
  const isDeviation = finding.result === "DEVIATION";

  return (
    <>
      <article
        className={`rounded-lg border bg-white overflow-hidden ${
          isDeviation ? "border-red-200" : "border-slate-200"
        }`}
        aria-label={`Finding: ${finding.attribute}`}
      >
        {/* Header */}
        <div
          className={`flex items-center justify-between gap-4 px-5 py-3 border-b ${
            isDeviation ? "border-red-100 bg-red-50" : "border-slate-100 bg-slate-50"
          }`}
        >
          <div className="flex items-center gap-2">
            {isDeviation && (
              <AlertTriangle className="h-4 w-4 text-red-500 shrink-0" aria-hidden />
            )}
            <h3 className="font-semibold text-slate-900">{finding.attribute}</h3>
          </div>
          <div className="flex items-center gap-2">
            <ResultBadge result={finding.result} />
            <FindingStatusBadge status={finding.status} />
          </div>
        </div>

        {/* Side-by-side comparison */}
        <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-slate-100">
          {/* Specification column */}
          <div className="px-5 py-4 space-y-3">
            <p className="text-[10px] font-bold uppercase tracking-widest text-blue-600">
              Specification Requirement
            </p>
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Required</p>
              <p className="text-sm font-medium text-slate-900">{finding.requirement}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Evidence</p>
              <blockquote className="border-l-2 border-blue-300 pl-3 text-xs text-slate-600 leading-relaxed italic">
                {finding.specification_evidence}
              </blockquote>
            </div>
          </div>

          {/* Submission column */}
          <div
            className={`px-5 py-4 space-y-3 ${
              isDeviation ? "bg-red-50/40" : ""
            }`}
          >
            <p className={`text-[10px] font-bold uppercase tracking-widest ${isDeviation ? "text-red-600" : "text-green-600"}`}>
              Submitted Product
            </p>
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Submitted Value</p>
              <p
                className={`text-sm font-medium ${
                  isDeviation ? "text-red-700" : "text-slate-900"
                }`}
              >
                {finding.submitted_value}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-slate-400 mb-1">Evidence</p>
              <blockquote
                className={`border-l-2 pl-3 text-xs leading-relaxed italic ${
                  isDeviation
                    ? "border-red-300 text-red-700"
                    : "border-green-300 text-slate-600"
                }`}
              >
                {finding.submission_evidence}
              </blockquote>
            </div>
          </div>
        </div>

        {/* Deviation banner */}
        {isDeviation && (
          <div className="border-t border-red-100 bg-red-50 px-5 py-2.5 flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 text-red-500 shrink-0" aria-hidden />
            <p className="text-xs font-medium text-red-700">
              Deviation — submitted value does not meet specification requirement
            </p>
          </div>
        )}

        {/* Review section */}
        <div
          className={`border-t px-5 py-4 ${
            isPending
              ? "border-amber-200 bg-amber-50"
              : isClarification
              ? "border-indigo-200 bg-indigo-50"
              : finding.status === "APPROVED"
              ? "border-green-200 bg-green-50"
              : "border-red-200 bg-red-50"
          }`}
        >
          {isPending ? (
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-2 text-sm text-amber-700">
                <Clock className="h-4 w-4 shrink-0" aria-hidden />
                <span className="font-medium">Awaiting reviewer decision</span>
              </div>
              <Button
                size="sm"
                onClick={() => setReviewOpen(true)}
                aria-label={`Review finding: ${finding.attribute}`}
              >
                Review This Finding →
              </Button>
            </div>
          ) : isClarification ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-indigo-700">
                <HelpCircle className="h-4 w-4" aria-hidden />
                Clarification Requested
              </div>
              <ReviewStamp finding={finding} />
            </div>
          ) : (
            <div className="space-y-2">
              <div
                className={`flex items-center gap-2 text-sm font-semibold ${
                  finding.status === "APPROVED" ? "text-green-700" : "text-red-700"
                }`}
              >
                {finding.status === "APPROVED" ? (
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                ) : (
                  <XCircle className="h-4 w-4" aria-hidden />
                )}
                {finding.status === "APPROVED" ? "Approved by reviewer" : "Rejected by reviewer"}
              </div>
              <ReviewStamp finding={finding} />
            </div>
          )}
        </div>
      </article>

      <ReviewModal
        finding={finding}
        submittalNumber={submittalNumber}
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
      />
    </>
  );
}

function ReviewStamp({ finding }: { finding: Finding }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {finding.reviewer && (
        <span>
          Reviewer: <strong className="text-slate-800">{finding.reviewer}</strong>
        </span>
      )}
      {finding.reviewed_at && (
        <span className="text-slate-400">{formatDateTime(finding.reviewed_at)}</span>
      )}
      {finding.reviewer_comment && (
        <p className="w-full mt-1 italic text-slate-600">
          &ldquo;{finding.reviewer_comment}&rdquo;
        </p>
      )}
    </div>
  );
}
