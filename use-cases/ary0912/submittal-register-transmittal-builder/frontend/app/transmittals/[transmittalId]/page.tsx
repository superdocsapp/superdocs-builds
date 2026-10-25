"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  editTransmittal,
  getTransmittalJob,
  approveTransmittalChange,
  exportTransmittal,
  downloadTransmittalUrl,
} from "@/lib/api/transmittals";
import { getSubmittalDetail, getProjectSubmittals } from "@/lib/api/submittals";
import { TransmittalTimeline } from "@/components/transmittals/TransmittalTimeline";
import { ChangeCard } from "@/components/transmittals/ChangeCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileText,
  RefreshCcw,
  Send,
} from "lucide-react";
import Link from "next/link";
import { formatDateTime, transmittalStatusLabel } from "@/lib/utils";
import { PROJECT_ID } from "@/lib/constants";
import type { TransmittalStatus } from "@/lib/api/types";

function useTransmittalFromRegister(transmittalId: string) {
  return useQuery({
    queryKey: ["transmittal-lookup", transmittalId],
    queryFn: async () => {
      const register = await getProjectSubmittals(PROJECT_ID);
      for (const item of register.items) {
        const detail = await getSubmittalDetail(item.number);
        if (detail.transmittal?.id === transmittalId) {
          return { submittal: detail, transmittal: detail.transmittal! };
        }
      }
      return null;
    },
    staleTime: 10_000,
  });
}

export default function TransmittalDetailPage({
  params,
}: {
  params: { transmittalId: string };
}) {
  const { transmittalId } = params;
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useTransmittalFromRegister(transmittalId);

  const [editMessage, setEditMessage] = useState("");
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);

  const editMutation = useMutation({
    mutationFn: () => editTransmittal(transmittalId, editMessage),
    onSuccess: () => {
      toast({ title: "Edit request submitted.", variant: "success" });
      setEditMessage("");
      queryClient.invalidateQueries({ queryKey: ["transmittal-lookup", transmittalId] });
    },
    onError: (err: Error) => {
      toast({ title: "Edit request failed.", description: err.message, variant: "error" });
    },
  });

  const jobQuery = useQuery({
    queryKey: ["transmittal-job", transmittalId],
    queryFn: () => getTransmittalJob(transmittalId),
    enabled:
      data?.transmittal?.status === "PROCESSING_EDIT" ||
      data?.transmittal?.status === "AWAITING_APPROVAL",
    refetchInterval:
      data?.transmittal?.status === "PROCESSING_EDIT" ? 3000 : false,
  });

  const approveMutation = useMutation({
    mutationFn: ({ changeId, approved }: { changeId?: string; approved: boolean }) =>
      approveTransmittalChange(transmittalId, approved, changeId),
    onSuccess: (_, vars) => {
      toast({
        title: vars.approved ? "Edit approved." : "Edit rejected.",
        variant: "success",
      });
      setApprovingId(null);
      setRejectingId(null);
      queryClient.invalidateQueries({ queryKey: ["transmittal-lookup", transmittalId] });
      queryClient.invalidateQueries({ queryKey: ["transmittal-job", transmittalId] });
    },
    onError: (err: Error) => {
      toast({ title: "Approval failed.", description: err.message, variant: "error" });
      setApprovingId(null);
      setRejectingId(null);
    },
  });

  const exportMutation = useMutation({
    mutationFn: () => exportTransmittal(transmittalId),
    onSuccess: () => {
      toast({ title: "Document exported.", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["transmittal-lookup", transmittalId] });
    },
    onError: (err: Error) => {
      toast({ title: "Export failed.", description: err.message, variant: "error" });
    },
  });

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load transmittal</h2>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-8 space-y-4">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 rounded-lg" />
        <Skeleton className="h-32 rounded-lg" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Transmittal not found</h2>
        <Link href="/transmittals">
          <Button variant="secondary">Back to Transmittals</Button>
        </Link>
      </div>
    );
  }

  const { submittal, transmittal } = data;
  const status = transmittal.status as TransmittalStatus;
  const changes = jobQuery.data?.proposed_changes ?? [];

  const canRequestEdit = status === "UPLOADED" || status === "EDIT_REJECTED";
  const canApprove = status === "AWAITING_APPROVAL";
  const canExport = status === "EDIT_APPROVED";
  const isExported = status === "EXPORTED";

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      {/* Back */}
      <Link
        href={`/projects/${PROJECT_ID}/submittals/${submittal.number}`}
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        {submittal.number} — {submittal.title}
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-600" aria-hidden />
            <h1 className="text-2xl font-semibold text-slate-900">{transmittal.number}</h1>
          </div>
          <p className="mt-0.5 text-sm text-slate-500">
            {submittal.title} · {submittal.specification_section}
          </p>
          <div className="mt-2">
            <Badge
              variant={
                isExported || canExport
                  ? "green"
                  : status === "EDIT_REJECTED"
                  ? "red"
                  : status === "AWAITING_APPROVAL" || status === "PROCESSING_EDIT"
                  ? "amber"
                  : "blue"
              }
            >
              {transmittalStatusLabel(status)}
            </Badge>
          </div>
          {transmittal.created_at && (
            <p className="mt-1 text-xs text-slate-400">
              Created {formatDateTime(transmittal.created_at)}
            </p>
          )}
        </div>

        {isExported ? (
          <a
            href={downloadTransmittalUrl(transmittalId)}
            download
            className="inline-flex items-center gap-2 rounded-md border border-green-300 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green-500"
          >
            <Download className="h-4 w-4" aria-hidden />
            Download DOCX
          </a>
        ) : canExport ? (
          <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
            Export DOCX
          </Button>
        ) : null}
      </div>

      {/* Timeline */}
      <TransmittalTimeline status={status} />

      {/* SuperDocs IDs */}
      {transmittal.superdocs_session_id && (
        <div className="rounded-lg border border-slate-200 bg-white px-5 py-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            SuperDocs Session
          </p>
          <p className="font-mono text-xs text-slate-600 break-all">
            {transmittal.superdocs_session_id}
          </p>
          {transmittal.superdocs_job_id && (
            <>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Job ID</p>
              <p className="font-mono text-xs text-slate-600 break-all">
                {transmittal.superdocs_job_id}
              </p>
            </>
          )}
        </div>
      )}

      {/* Request Edit */}
      {canRequestEdit && (
        <section aria-labelledby="edit-heading">
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            <div className="border-b border-slate-100 px-5 py-3">
              <h2 id="edit-heading" className="text-sm font-semibold text-slate-700">
                Request SuperDocs Edit
              </h2>
            </div>
            <div className="px-5 py-4 space-y-3">
              <label htmlFor="edit-message" className="block text-xs font-medium text-slate-500">
                Describe what should be changed in the transmittal document
              </label>
              <textarea
                id="edit-message"
                value={editMessage}
                onChange={(e) => setEditMessage(e.target.value)}
                rows={3}
                placeholder="e.g. Update thickness value to reflect approved deviation…"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="flex justify-end">
                <Button
                  onClick={() => editMutation.mutate()}
                  loading={editMutation.isPending}
                  disabled={!editMessage.trim()}
                >
                  <Send className="h-4 w-4" aria-hidden />
                  Submit Edit Request
                </Button>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Processing indicator */}
      {status === "PROCESSING_EDIT" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 flex items-center gap-3">
          <RefreshCcw className="h-4 w-4 text-amber-600 animate-spin" aria-hidden />
          <div>
            <p className="text-sm font-medium text-amber-800">Processing edit</p>
            <p className="text-xs text-amber-600">
              SuperDocs is processing your edit request. This page polls automatically.
            </p>
          </div>
        </div>
      )}

      {/* Proposed changes */}
      {canApprove && (
        <section aria-labelledby="changes-heading">
          <h2 id="changes-heading" className="mb-3 text-sm font-semibold text-slate-700">
            Proposed Changes
            {changes.length > 0 && (
              <span className="ml-2 font-normal text-slate-400">({changes.length})</span>
            )}
          </h2>
          {jobQuery.isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-28 rounded-lg" />
              ))}
            </div>
          ) : changes.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white px-5 py-8 text-center space-y-4">
              <p className="text-sm text-slate-500">
                No structured changes were returned. Approve or reject the edit as a whole.
              </p>
              <div className="flex justify-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={rejectingId === "global"}
                  onClick={() => {
                    setRejectingId("global");
                    approveMutation.mutate({ approved: false });
                  }}
                >
                  Reject Edit
                </Button>
                <Button
                  size="sm"
                  loading={approvingId === "global"}
                  onClick={() => {
                    setApprovingId("global");
                    approveMutation.mutate({ approved: true });
                  }}
                >
                  Approve Edit
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {changes.map((change, idx) => (
                <ChangeCard
                  key={change.change_id ?? idx}
                  change={change}
                  index={idx}
                  approving={approvingId === (change.change_id ?? String(idx))}
                  rejecting={rejectingId === (change.change_id ?? String(idx))}
                  onApprove={(id) => {
                    setApprovingId(id ?? String(idx));
                    approveMutation.mutate({ changeId: id, approved: true });
                  }}
                  onReject={(id) => {
                    setRejectingId(id ?? String(idx));
                    approveMutation.mutate({ changeId: id, approved: false });
                  }}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Edit approved banner */}
      {canExport && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-5 py-4 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <p className="text-sm font-medium text-green-800">Edit approved</p>
            <p className="text-xs text-green-600">
              The document is ready for export.
            </p>
          </div>
          <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
            Export DOCX
          </Button>
        </div>
      )}

      {/* Exported banner */}
      {isExported && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-5 py-4 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <p className="text-sm font-medium text-green-800">Document exported</p>
            <p className="text-xs text-green-600">
              The final DOCX is available for download.
            </p>
          </div>
          <a
            href={downloadTransmittalUrl(transmittalId)}
            download
            className="inline-flex items-center gap-2 rounded-md border border-green-400 bg-white px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green-500"
          >
            <Download className="h-4 w-4" aria-hidden />
            Download DOCX
          </a>
        </div>
      )}
    </div>
  );
}
