import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Upload, Download, ArrowUpDown, Search, Shield, Eye, FileText, Plus,
  Loader2, AlertCircle, CheckCircle2, RefreshCw, Send, Check, X, XCircle,
  ArrowUp, ArrowDown, Trash2,
} from "lucide-react";
import { clsx } from "clsx";
import { usePacket } from "@/hooks/usePackets";
import {
  useDocuments, useUploadDocuments, useDeleteDocument, useReorderDocument, useDownloadDocument,
} from "@/hooks/useDocuments";
import { useProcessingStatus, useStartProcessing, useRetryDocument } from "@/hooks/useProcessing";
import { useAssignBates, useBatesPreview } from "@/hooks/useBates";
import { useBuildPacket, useDownloadPacket, useValidatePacket, useManifest } from "@/hooks/useExports";
import {
  useDetectRedactions, useRedactionCandidates, useApproveRedaction,
  useApplyRedaction, useApplyAllRedactions,
} from "@/hooks/useRedactions";
import { usePrivilegeLog, usePrivilegeDecisions, useMarkPrivilege } from "@/hooks/usePrivilege";
import { useAuditTrail } from "@/hooks/useAudit";
import {
  useRequestAIAnalysis, useAnalysisStatus, useApproveAIChanges, useContinueAIJob,
} from "@/hooks/useReview";
import { useToast } from "@/components/ui/use-toast";
import type {
  DocumentListResponse, PrivilegeDecision, PrivilegeStatus, PrivilegeCategory, RedactionCandidate,
} from "@/types/api";

const statusColors: Record<string, string> = {
  completed: "bg-green-100 text-green-700",
  processing: "bg-blue-100 text-blue-700",
  ocr: "bg-yellow-100 text-yellow-700",
  ai_analysis: "bg-purple-100 text-purple-700",
  waiting_review: "bg-orange-100 text-orange-700",
  queued: "bg-gray-100 text-gray-700",
  failed: "bg-red-100 text-red-700",
  bates_assigned: "bg-teal-100 text-teal-700",
  assembling: "bg-indigo-100 text-indigo-700",
  approved: "bg-green-100 text-green-700",
};

const privilegeColors: Record<string, string> = {
  privileged: "bg-red-100 text-red-700",
  not_privileged: "bg-green-100 text-green-700",
  pending: "bg-gray-100 text-gray-700",
};

const redactionStatusColors: Record<string, string> = {
  proposed: "bg-gray-100 text-gray-700",
  pending_approval: "bg-yellow-100 text-yellow-700",
  approved: "bg-blue-100 text-blue-700",
  rejected: "bg-red-100 text-red-700",
  applied: "bg-green-100 text-green-700",
  verified: "bg-teal-100 text-teal-700",
  failed: "bg-red-100 text-red-700",
};

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      <span className="ml-3 text-gray-600">{message}</span>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
      <div className="flex items-center gap-2">
        <AlertCircle className="h-5 w-5 text-red-600" />
        <span className="text-red-800">Failed to load</span>
      </div>
      <p className="text-sm text-red-600 mt-2">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
        >
          Retry
        </button>
      )}
    </div>
  );
}

const stripHtml = (html: string | null) =>
  (html ?? "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();

// ---------- AI Changes Panel ----------

function AiChangesPanel({ packetId, selectedDoc }: { packetId: string; selectedDoc: DocumentListResponse }) {
  const [instruction, setInstruction] = useState(
    "Review this document for legal relevance, summarize key points, and propose any edits needed for exhibit inclusion."
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const { toast } = useToast();

  const requestAIAnalysis = useRequestAIAnalysis();
  const approveAIChanges = useApproveAIChanges();
  const continueAIJob = useContinueAIJob();
  const { data: status, isLoading: statusLoading } = useAnalysisStatus(packetId, selectedDoc.id, jobId ?? "");

  const handleRequest = async () => {
    try {
      const res = await requestAIAnalysis.mutateAsync({
        packetId,
        documentId: selectedDoc.id,
        data: { instruction, approval_mode: "ask_every_time", model_tier: "core" },
      });
      setJobId(res.job_id);
      toast({ title: "AI analysis started", description: `Job ${res.job_id}` });
    } catch (err: any) {
      toast({ title: "Failed to start AI analysis", description: err?.message, variant: "destructive" });
    }
  };

  const handleApprove = async (approved: boolean) => {
    if (!jobId || !status?.changes) return;
    try {
      await approveAIChanges.mutateAsync({
        packetId,
        documentId: selectedDoc.id,
        data: { job_id: jobId, approved, changes: status.changes },
      });
      toast({ title: approved ? "Changes approved" : "Changes rejected" });
      setJobId(null);
    } catch (err: any) {
      toast({ title: "Failed to submit decision", description: err?.message, variant: "destructive" });
    }
  };

  const handleContinue = async (continueJob: boolean) => {
    if (!jobId) return;
    try {
      await continueAIJob.mutateAsync({
        packetId,
        documentId: selectedDoc.id,
        data: { job_id: jobId, continue_job: continueJob },
      });
      toast({ title: continueJob ? "Job continued" : "Job stopped" });
      setJobId(null);
    } catch (err: any) {
      toast({ title: "Failed to continue job", description: err?.message, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-4xl mx-auto bg-white rounded-lg shadow-sm border p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-medium text-gray-900">AI Review: {selectedDoc.filename}</h2>
        <span className={clsx("px-2 py-1 rounded text-xs", statusColors[selectedDoc.status] ?? "bg-gray-100 text-gray-700")}>
          {selectedDoc.status.replace("_", " ")}
        </span>
      </div>

      {!jobId ? (
        <div className="space-y-3">
          <label className="block text-sm font-medium text-gray-700">Instruction for SuperDocs AI</label>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          />
          <Button onClick={handleRequest} disabled={requestAIAnalysis.isPending}>
            {requestAIAnalysis.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Request AI Analysis
          </Button>
        </div>
      ) : statusLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
          <span className="ml-3 text-gray-600">Polling job {jobId}...</span>
        </div>
      ) : status?.status === "awaiting_approval" && status.changes && status.changes.length > 0 ? (
        <div className="space-y-4">
          <p className="text-sm font-medium text-gray-700">
            {status.changes.length} proposed change(s) awaiting approval
            {status.awaiting_kind === "continue" ? " (continue prompt)" : ""}
          </p>
          {status.changes.map((change) => (
            <div key={change.change_id} className="border border-gray-200 rounded-lg p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="px-1.5 py-0.5 text-xs bg-purple-50 text-purple-700 rounded">{change.operation}</span>
                <span className="text-xs text-gray-400">{change.change_id}</span>
              </div>
              {change.ai_explanation && (
                <p className="text-sm text-gray-600 mt-2">{change.ai_explanation}</p>
              )}
              {change.old_html && (
                <p className="text-xs text-gray-500 mt-2">
                  <span className="font-medium text-red-600">Before:</span> {stripHtml(change.old_html).slice(0, 300)}
                </p>
              )}
              {change.new_html && (
                <p className="text-xs text-gray-500 mt-1">
                  <span className="font-medium text-green-600">After:</span> {stripHtml(change.new_html).slice(0, 300)}
                </p>
              )}
            </div>
          ))}
          <div className="flex gap-2">
            <Button onClick={() => handleApprove(true)} disabled={approveAIChanges.isPending}>
              <Check className="h-4 w-4" /> Approve All
            </Button>
            <Button variant="outline" onClick={() => handleApprove(false)} disabled={approveAIChanges.isPending}>
              <X className="h-4 w-4" /> Reject All
            </Button>
          </div>
        </div>
      ) : status?.status === "awaiting_approval" && status.continue_prompt ? (
        <div className="space-y-3">
          <p className="text-sm text-gray-700">{String(status.continue_prompt)}</p>
          <div className="flex gap-2">
            <Button onClick={() => handleContinue(true)} disabled={continueAIJob.isPending}>
              <Check className="h-4 w-4" /> Continue
            </Button>
            <Button variant="outline" onClick={() => handleContinue(false)} disabled={continueAIJob.isPending}>
              <X className="h-4 w-4" /> Stop
            </Button>
          </div>
        </div>
      ) : status?.error ? (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-red-600" />
          <span className="text-sm text-red-800">{status.error}</span>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-gray-600">Job status: <span className="font-medium">{status?.status ?? "unknown"}</span></p>
          {status?.result && (
            <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto max-h-64">
              {JSON.stringify(status.result, null, 2).slice(0, 2000)}
            </pre>
          )}
          <Button variant="outline" onClick={() => setJobId(null)}>
            <XCircle className="h-4 w-4" /> Cancel Job
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------- Privilege Panel ----------

function PrivilegeRow({
  doc, decision, onSave, isSaving,
}: {
  doc: DocumentListResponse;
  decision?: PrivilegeDecision;
  onSave: (docId: string, data: { status: PrivilegeStatus; category?: PrivilegeCategory; reason?: string }) => void;
  isSaving: boolean;
}) {
  const [status, setStatus] = useState<PrivilegeStatus>(decision?.status ?? "pending");
  const [category, setCategory] = useState<PrivilegeCategory | "">(decision?.category ?? "");
  const [reason, setReason] = useState(decision?.reason ?? "");

  const invalid = status === "privileged" && !reason.trim();

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-gray-900 truncate">{doc.filename}</p>
          <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
            <span className={clsx("px-1.5 py-0.5 rounded", privilegeColors[status])}>{status.replace("_", " ")}</span>
            {doc.bates_range && <span className="font-mono">{doc.bates_range}</span>}
            {decision?.reviewer && <span>by {decision.reviewer}</span>}
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as PrivilegeStatus)}
          className="px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-primary-500"
        >
          <option value="pending">Pending</option>
          <option value="privileged">Privileged</option>
          <option value="not_privileged">Not Privileged</option>
        </select>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as PrivilegeCategory | "")}
          disabled={status !== "privileged"}
          className="px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
        >
          <option value="">Category...</option>
          <option value="attorney_client">Attorney-Client</option>
          <option value="work_product">Work Product</option>
          <option value="other">Other</option>
        </select>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={status !== "privileged"}
          placeholder={status === "privileged" ? "Reason (required)" : "Reason"}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
        />
      </div>
      {invalid && <p className="text-xs text-red-600 mt-2">Reason is required for privileged documents.</p>}
      <div className="mt-3 flex justify-end">
        <Button
          size="sm"
          variant="outline"
          disabled={isSaving || invalid || (status === "pending" && !decision)}
          onClick={() => onSave(doc.id, { status, category: category || undefined, reason: reason || undefined })}
        >
          {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save Decision
        </Button>
      </div>
    </div>
  );
}

function PrivilegePanel({ packetId, documents }: { packetId: string; documents?: DocumentListResponse[] }) {
  const [reviewer, setReviewer] = useState("reviewer");
  const { data: decisions } = usePrivilegeDecisions(packetId);
  const markPrivilege = useMarkPrivilege();
  const { toast } = useToast();

  const decisionsByDoc = useMemo(() => {
    const map: Record<string, PrivilegeDecision> = {};
    (decisions ?? []).forEach((d: PrivilegeDecision) => { map[d.document_id] = d; });
    return map;
  }, [decisions]);

  const handleSave = async (docId: string, data: { status: PrivilegeStatus; category?: PrivilegeCategory; reason?: string }) => {
    try {
      await markPrivilege.mutateAsync({ packetId, documentId: docId, data: { ...data, reviewer } });
      toast({ title: "Privilege decision saved" });
    } catch (err: any) {
      toast({ title: "Failed to save decision", description: err?.message, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="bg-white rounded-lg shadow-sm border p-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Privilege Marking</h2>
          <p className="text-sm text-gray-500 mt-1">Mark documents as privileged with category and reason. Privileged documents appear in the privilege log.</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">Reviewer:</label>
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-40 focus:ring-2 focus:ring-primary-500"
          />
        </div>
      </div>
      {!documents || documents.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-gray-500">
          No documents to mark. Upload documents first.
        </div>
      ) : (
        documents.map((doc) => (
          <PrivilegeRow
            key={doc.id}
            doc={doc}
            decision={decisionsByDoc[doc.id]}
            onSave={handleSave}
            isSaving={markPrivilege.isPending}
          />
        ))
      )}
    </div>
  );
}

// ---------- Redactions Panel ----------

function RedactionsPanel({ packetId, candidates }: { packetId: string; candidates?: RedactionCandidate[] }) {
  const [approver, setApprover] = useState("reviewer");
  const { toast } = useToast();
  const approveRedaction = useApproveRedaction();
  const applyRedaction = useApplyRedaction();
  const applyAll = useApplyAllRedactions();

  const approvedDocIds = useMemo(
    () => [...new Set((candidates ?? []).filter((c) => c.status === "approved").map((c) => c.document_id))],
    [candidates]
  );

  const handleApprove = async (candidate: RedactionCandidate, approved: boolean) => {
    try {
      await approveRedaction.mutateAsync({
        packetId,
        redactionId: candidate.id,
        data: { status: approved ? "approved" : "rejected", approver },
      });
      toast({ title: approved ? "Candidate approved" : "Candidate rejected" });
    } catch (err: any) {
      toast({ title: "Action failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleApply = async (candidate: RedactionCandidate) => {
    try {
      await applyRedaction.mutateAsync({ packetId, redactionId: candidate.id });
      toast({ title: "Redaction applied", description: "Applied and verified." });
    } catch (err: any) {
      toast({ title: "Apply failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleApplyAll = async () => {
    if (approvedDocIds.length === 0) return;
    try {
      const res = await applyAll.mutateAsync({ packetId, data: { document_ids: approvedDocIds } });
      const total = res.results?.reduce((sum: number, r: any) => sum + (r.candidates_applied ?? 0), 0) ?? 0;
      toast({ title: "Redactions applied", description: `${total} candidate(s) applied across ${res.results?.length ?? 0} document(s).` });
    } catch (err: any) {
      toast({ title: "Apply failed", description: err?.message, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="bg-white rounded-lg shadow-sm border p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-gray-900">Redaction Candidates</h2>
          <p className="text-sm text-gray-500 mt-1">
            {candidates?.length ?? 0} candidate(s). Approve, reject, then apply redactions to documents.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">Approver:</label>
          <input
            type="text"
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-32 focus:ring-2 focus:ring-primary-500"
          />
          <Button onClick={handleApplyAll} disabled={approvedDocIds.length === 0 || applyAll.isPending}>
            {applyAll.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Apply All Approved
          </Button>
        </div>
      </div>

      {!candidates || candidates.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-gray-500">
          No redaction candidates yet. Run "Detect Redactions" to scan for PII.
        </div>
      ) : (
        candidates.map((candidate) => (
          <div key={candidate.id} className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-gray-900">{candidate.matched_text}</p>
                <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-gray-500">
                  <span className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded">{candidate.category}</span>
                  <span>{candidate.document_name}</span>
                  <span>Page {candidate.page_number}</span>
                  <span className={clsx("px-1.5 py-0.5 rounded", redactionStatusColors[candidate.status] ?? "bg-gray-100 text-gray-700")}>
                    {candidate.status.replace("_", " ")}
                  </span>
                  {candidate.approval?.approver && <span>by {candidate.approval.approver}</span>}
                </div>
                {(candidate.context_before || candidate.context_after) && (
                  <p className="text-xs text-gray-500 mt-2">
                    {candidate.context_before && <span>…{candidate.context_before}</span>}
                    <span className="font-medium text-gray-700"> {candidate.matched_text} </span>
                    {candidate.context_after && <span>{candidate.context_after}…</span>}
                  </p>
                )}
              </div>
              <div className="flex gap-2 flex-shrink-0">
                {(candidate.status === "proposed" || candidate.status === "pending_approval") && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => handleApprove(candidate, true)} disabled={approveRedaction.isPending}>
                      <Check className="h-3.5 w-3.5" /> Approve
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => handleApprove(candidate, false)} disabled={approveRedaction.isPending}>
                      <X className="h-3.5 w-3.5" /> Reject
                    </Button>
                  </>
                )}
                {candidate.status === "approved" && (
                  <Button size="sm" onClick={() => handleApply(candidate)} disabled={applyRedaction.isPending}>
                    {applyRedaction.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                    Apply
                  </Button>
                )}
                {candidate.status === "applied" && (
                  <span className="text-xs text-gray-500 flex items-center gap-1">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    Applied
                    {candidate.approval?.verified_at && <span className="text-teal-600">• Verified</span>}
                  </span>
                )}
                {candidate.status === "rejected" && (
                  <span className="text-xs text-red-600 flex items-center gap-1">
                    <XCircle className="h-4 w-4" /> Rejected
                  </span>
                )}
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ---------- Audit Panel ----------

function AuditPanel({ packetId }: { packetId: string }) {
  const { data: trail, isLoading } = useAuditTrail(packetId);

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="bg-white rounded-lg shadow-sm border p-4">
        <h2 className="text-lg font-medium text-gray-900">Audit Trail</h2>
        <p className="text-sm text-gray-500 mt-1">{trail?.total_events ?? 0} event(s) recorded for this packet.</p>
      </div>
      {isLoading ? (
        <LoadingState message="Loading audit trail..." />
      ) : !trail || trail.events.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-gray-500">
          No audit events recorded yet.
        </div>
      ) : (
        trail.events.map((event) => (
          <div key={event.id} className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-1.5 py-0.5 text-xs bg-primary-50 text-primary-700 rounded font-medium">
                    {event.event_type.replace(/_/g, " ")}
                  </span>
                  {event.user_id && <span className="text-xs text-gray-500">by {event.user_id}</span>}
                  {event.document_name && <span className="text-xs text-gray-500">{event.document_name}</span>}
                </div>
                {event.metadata && (
                  <pre className="text-xs bg-gray-50 border border-gray-100 rounded p-2 mt-2 overflow-x-auto">
                    {JSON.stringify(event.metadata, null, 2).slice(0, 500)}
                  </pre>
                )}
              </div>
              <span className="text-xs text-gray-400 flex-shrink-0">
                {new Date(event.timestamp).toLocaleString()}
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ---------- Main Workspace ----------

export function PacketWorkspace() {
  const { packetId = "" } = useParams();
  const [activeTab, setActiveTab] = useState("documents");
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const { data: packet, isLoading: packetLoading, error: packetError, refetch: refetchPacket } = usePacket(packetId);
  const { data: documents, isLoading: docsLoading, error: docsError, refetch: refetchDocs } = useDocuments(packetId);
  const { data: processingStatus, refetch: refetchProcessing } = useProcessingStatus(packetId);
  const { data: batesPreview } = useBatesPreview(packetId);
  const { data: manifest } = useManifest(packetId);
  const { data: redactionCandidates } = useRedactionCandidates(packetId);
  const { data: privilegeLog } = usePrivilegeLog(packetId);

  const uploadMutation = useUploadDocuments(packetId);
  const startProcessing = useStartProcessing();
  const retryDocument = useRetryDocument();
  const assignBates = useAssignBates();
  const buildPacket = useBuildPacket();
  const validatePacket = useValidatePacket();
  const downloadPacket = useDownloadPacket(packetId);
  const detectRedactions = useDetectRedactions();
  const downloadDocument = useDownloadDocument(packetId);
  const reorderDocument = useReorderDocument(packetId);
  const deleteDocument = useDeleteDocument(packetId);

  const sortedDocs = useMemo(() => {
    const docs = [...(documents ?? [])];
    docs.sort((a, b) => a.display_order - b.display_order);
    return docs;
  }, [documents]);

  const selectedDoc = sortedDocs.find((d) => d.id === selectedDocId) ?? sortedDocs[0] ?? null;

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      const result = await uploadMutation.mutateAsync(files);
      toast({
        title: "Documents uploaded",
        description: `${result.documents.length} document(s) uploaded and processed.`,
      });
      refetchDocs();
    } catch (err: any) {
      toast({
        title: "Upload failed",
        description: err?.message ?? "An unexpected error occurred.",
        variant: "destructive",
      });
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleProcess = async () => {
    try {
      const result = await startProcessing.mutateAsync(packetId);
      toast({
        title: "Processing started",
        description: `${result.documents_queued?.length ?? 0} document(s) queued for processing.`,
      });
      refetchProcessing();
    } catch (err: any) {
      toast({ title: "Processing failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleAssignBates = async () => {
    try {
      await assignBates.mutateAsync(packetId);
      toast({ title: "Bates assigned", description: "Bates numbers assigned to all documents." });
      refetchDocs();
    } catch (err: any) {
      toast({ title: "Bates assignment failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleBuild = async () => {
    try {
      await validatePacket.mutateAsync(packetId);
      const result = await buildPacket.mutateAsync(packetId);
      toast({
        title: "Packet built",
        description: `${result.total_documents} documents, ${result.total_pages} pages (covers included).`,
      });
    } catch (err: any) {
      toast({ title: "Build failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleExport = async () => {
    try {
      const blob = await downloadPacket.mutateAsync();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${packet?.name ?? "packet"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Export started", description: "Packet download initiated." });
    } catch (err: any) {
      toast({ title: "Export failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleDetectRedactions = async () => {
    try {
      const result = await detectRedactions.mutateAsync(packetId);
      toast({
        title: "Detection started",
        description: `${result.documents_queued ?? 0} document(s) queued for PII scan.`,
      });
    } catch (err: any) {
      toast({ title: "Detection failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleDownloadDocument = async (doc: DocumentListResponse) => {
    try {
      const blob = await downloadDocument.mutateAsync(doc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast({ title: "Download failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleMoveDocument = async (doc: DocumentListResponse, direction: "up" | "down") => {
    const index = sortedDocs.findIndex((d) => d.id === doc.id);
    if (index < 0) return;
    const newOrder =
      direction === "up" ? index : index + 2;
    try {
      await reorderDocument.mutateAsync({ documentId: doc.id, newOrder });
      toast({ title: "Document reordered", description: "Bates numbers will be reassigned." });
    } catch (err: any) {
      toast({ title: "Reorder failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleDeleteDocument = async (doc: DocumentListResponse) => {
    if (!window.confirm(`Delete ${doc.filename} from this packet? This cannot be undone.`)) return;
    try {
      await deleteDocument.mutateAsync(doc.id);
      toast({ title: "Document deleted" });
      if (selectedDoc?.id === doc.id) setSelectedDocId(null);
    } catch (err: any) {
      toast({ title: "Delete failed", description: err?.message, variant: "destructive" });
    }
  };

  if (packetLoading) return <LoadingState message="Loading packet..." />;
  if (packetError) return <ErrorState message={packetError.message} onRetry={refetchPacket} />;
  if (!packet) return <ErrorState message="Packet not found." />;

  const batesStartLabel = packet.bates_prefix
    ? `${packet.bates_prefix}${String(packet.bates_start_number ?? 1).padStart(packet.bates_padding ?? 6, "0")}+`
    : "Not configured";

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-gray-200 bg-white">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{packet.name}</h1>
            <p className="text-sm text-gray-500">
              Packet ID: {packet.id} | Bates: {batesStartLabel} |{" "}
              {documents ? documents.length : 0} documents |{" "}
              {documents?.reduce((sum, d) => sum + (d.page_count ?? 0), 0) ?? 0} pages
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.docx,.png,.jpg,.jpeg,.tiff,.tif"
              className="hidden"
              onChange={handleUpload}
            />
            <Button
              variant="outline"
              className="gap-1"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              Upload
            </Button>
            <Button variant="outline" className="gap-1" onClick={handleProcess} disabled={startProcessing.isPending}>
              {startProcessing.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUpDown className="h-4 w-4" />}
              Process
            </Button>
            <Button variant="outline" className="gap-1" onClick={handleAssignBates} disabled={assignBates.isPending}>
              {assignBates.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
              Assign Bates
            </Button>
            <Button variant="outline" className="gap-1" onClick={handleBuild} disabled={buildPacket.isPending || validatePacket.isPending}>
              {buildPacket.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              Build Packet
            </Button>
            <Button className="gap-1" onClick={handleExport} disabled={downloadPacket.isPending}>
              {downloadPacket.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Export
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-72 border-r border-gray-200 bg-white flex flex-col overflow-hidden">
          <div className="p-3 border-b border-gray-200">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="documents" className="text-xs py-1">Documents</TabsTrigger>
                <TabsTrigger value="processing" className="text-xs py-1">Processing</TabsTrigger>
                <TabsTrigger value="review" className="text-xs py-1">Review</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {activeTab === "documents" && (
              <div className="space-y-2">
                {docsLoading && <LoadingState message="Loading documents..." />}
                {docsError && <ErrorState message={docsError.message} onRetry={refetchDocs} />}
                {!docsLoading && !docsError && (!documents || documents.length === 0) && (
                  <div className="text-center py-8 text-gray-500">
                    <FileText className="h-10 w-10 mx-auto mb-2 text-gray-300" />
                    <p className="text-sm">No documents yet.</p>
                    <p className="text-xs mt-1">Upload a PDF, DOCX, or image to get started.</p>
                  </div>
                )}
                {sortedDocs.map((doc, index) => (
                  <div
                    key={doc.id}
                    className={clsx(
                      "p-3 rounded-lg border transition-colors",
                      selectedDoc?.id === doc.id
                        ? "border-primary-500 bg-primary-50"
                        : "border-transparent hover:border-gray-200 hover:bg-gray-50"
                    )}
                  >
                    <button
                      onClick={() => setSelectedDocId(doc.id)}
                      className="w-full text-left"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-gray-900 truncate">{doc.filename}</p>
                          <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                            <span className={clsx("px-1.5 py-0.5 rounded text-xs", statusColors[doc.status] ?? "bg-gray-100 text-gray-700")}>
                              {doc.status.replace("_", " ")}
                            </span>
                            <span className={clsx("px-1.5 py-0.5 rounded text-xs", privilegeColors[doc.privilege_status] ?? "bg-gray-100 text-gray-700")}>
                              {(doc.privilege_status ?? "pending").replace("_", " ")}
                            </span>
                          </div>
                          {doc.bates_range && (
                            <p className="text-xs text-primary-600 mt-1 font-mono">{doc.bates_range}</p>
                          )}
                        </div>
                      </div>
                    </button>
                    <div className="flex items-center gap-1 mt-2 pt-2 border-t border-gray-100">
                      <button
                        title="Move up"
                        onClick={() => handleMoveDocument(doc, "up")}
                        disabled={index === 0 || reorderDocument.isPending}
                        className="p-1 rounded hover:bg-gray-200 text-gray-500 disabled:opacity-30"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Move down"
                        onClick={() => handleMoveDocument(doc, "down")}
                        disabled={index === sortedDocs.length - 1 || reorderDocument.isPending}
                        className="p-1 rounded hover:bg-gray-200 text-gray-500 disabled:opacity-30"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Download original"
                        onClick={() => handleDownloadDocument(doc)}
                        disabled={downloadDocument.isPending}
                        className="p-1 rounded hover:bg-gray-200 text-gray-500 disabled:opacity-30"
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Delete document"
                        onClick={() => handleDeleteDocument(doc)}
                        disabled={deleteDocument.isPending}
                        className="p-1 rounded hover:bg-red-100 text-red-500 disabled:opacity-30 ml-auto"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
                {!docsLoading && !docsError && (
                  <Button variant="outline" className="w-full justify-start gap-2 mt-2" onClick={() => fileInputRef.current?.click()}>
                    <Plus className="h-4 w-4" />
                    Add Documents
                  </Button>
                )}
              </div>
            )}

            {activeTab === "processing" && (
              <div className="space-y-3">
                <div className="p-3 bg-blue-50 rounded-lg border border-blue-200">
                  <p className="text-sm font-medium text-blue-800">Processing Queue</p>
                  <p className="text-xs text-blue-600 mt-1">
                    {processingStatus?.status_breakdown?.queued ?? 0} queued |{" "}
                    {processingStatus?.status_breakdown?.processing ?? 0} processing |{" "}
                    {processingStatus?.status_breakdown?.failed ?? 0} failed
                  </p>
                </div>
                <div className="space-y-2">
                  {processingStatus?.documents?.filter((d) => d.status !== "completed").map((doc) => (
                    <div key={doc.id} className="p-3 bg-gray-50 rounded-lg border">
                      <p className="text-sm font-medium text-gray-900">{doc.filename}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={clsx("px-1.5 py-0.5 rounded text-xs", statusColors[doc.status] ?? "bg-gray-100 text-gray-700")}>
                          {doc.status.replace("_", " ")}
                        </span>
                        {doc.error && <span className="text-xs text-red-600 truncate">{doc.error}</span>}
                      </div>
                      {doc.status === "failed" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="mt-2"
                          onClick={() => retryDocument.mutate({ packetId, documentId: doc.id })}
                          disabled={retryDocument.isPending}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Retry
                        </Button>
                      )}
                    </div>
                  ))}
                  {(!processingStatus?.documents || processingStatus.documents.length === 0) && (
                    <p className="text-center text-sm text-gray-500 py-6">
                      No documents in the queue.
                    </p>
                  )}
                  {processingStatus?.documents?.every((d) => d.status === "completed") && (
                    <p className="text-center text-sm text-gray-500 py-6">
                      All documents processed.
                    </p>
                  )}
                </div>
              </div>
            )}

            {activeTab === "review" && (
              <div className="space-y-3">
                <div className="p-3 bg-purple-50 rounded-lg border border-purple-200">
                  <p className="text-sm font-medium text-purple-800">AI Review Queue</p>
                  <p className="text-xs text-purple-600 mt-1">
                    {processingStatus?.status_breakdown?.waiting_review ?? 0} documents awaiting AI review
                  </p>
                </div>
                <div className="space-y-2">
                  {processingStatus?.documents
                    ?.filter((d) => d.status === "waiting_review" || d.status === "ai_analysis")
                    .map((doc) => (
                      <div key={doc.id} className="p-3 bg-gray-50 rounded-lg border">
                        <p className="text-sm font-medium text-gray-900">{doc.filename}</p>
                        <p className="text-xs text-gray-500 mt-1">
                          {doc.status === "waiting_review" ? "Awaiting approval of AI changes" : "AI analysis in progress"}
                        </p>
                      </div>
                    ))}
                  {(!processingStatus?.documents?.some((d) => d.status === "waiting_review" || d.status === "ai_analysis")) && (
                    <p className="text-center text-sm text-gray-500 py-6">No documents awaiting review.</p>
                  )}
                  <Button variant="outline" className="w-full justify-start gap-2" onClick={() => setActiveTab("ai-changes")}>
                    <Send className="h-4 w-4" />
                    Go to AI Review Panel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden min-w-0">
          <div className="p-4 border-b border-gray-200 bg-white">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="hidden md:flex">
              <TabsList>
                <TabsTrigger value="documents">Document Viewer</TabsTrigger>
                <TabsTrigger value="ai-changes">AI Changes</TabsTrigger>
                <TabsTrigger value="privilege">Privilege</TabsTrigger>
                <TabsTrigger value="redactions">Redactions</TabsTrigger>
                <TabsTrigger value="audit">Audit</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="flex-1 overflow-auto p-4 bg-gray-100">
            {activeTab === "ai-changes" && selectedDoc && (
              <AiChangesPanel packetId={packetId} selectedDoc={selectedDoc} />
            )}
            {activeTab === "ai-changes" && !selectedDoc && (
              <div className="max-w-4xl mx-auto bg-white rounded-lg border p-6 text-center text-gray-500">
                Select a document to run AI analysis.
              </div>
            )}
            {activeTab === "privilege" && <PrivilegePanel packetId={packetId} documents={documents} />}
            {activeTab === "redactions" && <RedactionsPanel packetId={packetId} candidates={redactionCandidates} />}
            {activeTab === "audit" && <AuditPanel packetId={packetId} />}

            {activeTab === "documents" && (
              <div className="max-w-4xl mx-auto bg-white rounded-lg shadow-sm border p-6">
                {selectedDoc ? (
                  <>
                    <div className="flex items-center justify-between mb-4">
                      <h2 className="text-lg font-medium text-gray-900">{selectedDoc.filename}</h2>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1"
                          onClick={() => handleDownloadDocument(selectedDoc)}
                          disabled={downloadDocument.isPending}
                        >
                          {downloadDocument.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                          Download
                        </Button>
                        <span className={clsx("px-2 py-1 rounded text-xs", statusColors[selectedDoc.status] ?? "bg-gray-100 text-gray-700")}>
                          {selectedDoc.status.replace("_", " ")}
                        </span>
                        <span className={clsx("px-2 py-1 rounded text-xs", privilegeColors[selectedDoc.privilege_status] ?? "bg-gray-100 text-gray-700")}>
                          {(selectedDoc.privilege_status ?? "pending").replace("_", " ")}
                        </span>
                      </div>
                    </div>

                    <div className="aspect-video bg-gray-100 rounded-lg border flex items-center justify-center">
                      <div className="text-center text-gray-500">
                        <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                        <p>PDF Document Viewer</p>
                        <p className="text-sm mt-1">{selectedDoc.page_count} pages</p>
                        {selectedDoc.bates_range && (
                          <p className="text-xs text-primary-600 mt-1 font-mono">{selectedDoc.bates_range}</p>
                        )}
                      </div>
                    </div>

                    <div className="mt-4 grid grid-cols-3 gap-4 text-sm text-gray-600">
                      <div>
                        <p className="font-medium text-gray-900">Document Type</p>
                        <p>{selectedDoc.document_type.toUpperCase()}</p>
                      </div>
                      <div>
                        <p className="font-medium text-gray-900">Pages</p>
                        <p>{selectedDoc.page_count}</p>
                      </div>
                      <div>
                        <p className="font-medium text-gray-900">Bates Range</p>
                        <p className="font-mono">{selectedDoc.bates_range || "Not assigned"}</p>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-12 text-gray-500">
                    <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                    <p>Select a document to view details.</p>
                  </div>
                )}
              </div>
            )}

            {activeTab === "processing" && (
              <div className="max-w-4xl mx-auto bg-white rounded-lg shadow-sm border p-6">
                <h2 className="text-lg font-medium text-gray-900">Processing Status</h2>
                <div className="mt-3 space-y-2">
                  {processingStatus?.documents?.map((doc) => (
                    <div key={doc.id} className="flex items-center justify-between border border-gray-100 rounded-lg p-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                        <p className="text-xs text-gray-500">
                          {doc.page_count} pages | {doc.is_searchable ? "searchable" : "not searchable"}
                          {doc.error && ` | ${doc.error}`}
                        </p>
                      </div>
                      <span className={clsx("px-2 py-1 rounded text-xs flex-shrink-0", statusColors[doc.status] ?? "bg-gray-100 text-gray-700")}>
                        {doc.status.replace("_", " ")}
                      </span>
                    </div>
                  ))}
                  {(!processingStatus?.documents || processingStatus.documents.length === 0) && (
                    <p className="text-center text-sm text-gray-500 py-6">No documents yet.</p>
                  )}
                </div>
              </div>
            )}

            {activeTab === "review" && (
              <div className="max-w-4xl mx-auto bg-white rounded-lg shadow-sm border p-6">
                <h2 className="text-lg font-medium text-gray-900">AI Review Queue</h2>
                <p className="text-sm text-gray-500 mt-1">
                  Documents awaiting AI analysis or human approval of proposed changes. Use the AI Changes tab to
                  request and review analysis for a selected document.
                </p>
              </div>
            )}
          </div>
        </main>

        <aside className="w-80 border-l border-gray-200 bg-white overflow-y-auto p-4 hidden lg:block">
          <div className="space-y-4">
            <div className="p-3 bg-primary-50 rounded-lg border border-primary-200">
              <h3 className="font-medium text-primary-800 flex items-center gap-2">
                <Shield className="h-4 w-4" />
                Quick Actions
              </h3>
              <div className="mt-3 space-y-2">
                <Button variant="outline" className="w-full justify-start gap-2" disabled>
                  <Eye className="h-4 w-4" />
                  View in SuperDocs
                </Button>
                <Button variant="outline" className="w-full justify-start gap-2" onClick={handleAssignBates} disabled={assignBates.isPending}>
                  {assignBates.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
                  Assign Bates Numbers
                </Button>
                <Button variant="outline" className="w-full justify-start gap-2" onClick={() => setActiveTab("ai-changes")}>
                  <Send className="h-4 w-4" />
                  AI Review
                </Button>
                <Button variant="outline" className="w-full justify-start gap-2" onClick={handleDetectRedactions} disabled={detectRedactions.isPending}>
                  {detectRedactions.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Detect Redactions
                </Button>
                <Button variant="outline" className="w-full justify-start gap-2" onClick={handleBuild} disabled={buildPacket.isPending || validatePacket.isPending}>
                  {buildPacket.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                  Build Packet
                </Button>
              </div>
            </div>

            {selectedDoc && (
              <div className="p-3 bg-gray-50 rounded-lg border">
                <h3 className="font-medium text-gray-800">Document Info</h3>
                <dl className="mt-2 space-y-1 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Status</dt>
                    <dd className="font-medium capitalize">{selectedDoc.status.replace("_", " ")}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Privilege</dt>
                    <dd className="font-medium capitalize">{(selectedDoc.privilege_status ?? "pending").replace("_", " ")}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Pages</dt>
                    <dd className="font-medium">{selectedDoc.page_count}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Bates Range</dt>
                    <dd className="font-medium font-mono text-xs">{selectedDoc.bates_range || "Not assigned"}</dd>
                  </div>
                </dl>
              </div>
            )}

            <div className="p-3 bg-gray-50 rounded-lg border">
              <h3 className="font-medium text-gray-800">Packet Summary</h3>
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-gray-500">Documents</dt>
                  <dd className="font-medium">{documents?.length ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Total Pages</dt>
                  <dd className="font-medium">{documents?.reduce((sum, d) => sum + (d.page_count ?? 0), 0) ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Privileged</dt>
                  <dd className="font-medium">{privilegeLog?.total_privileged_documents ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-gray-500">Redaction Candidates</dt>
                  <dd className="font-medium">{redactionCandidates?.length ?? 0}</dd>
                </div>
                {batesPreview?.start_label && (
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Preview Range</dt>
                    <dd className="font-medium font-mono text-xs">
                      {batesPreview.start_label} - {batesPreview.end_label}
                    </dd>
                  </div>
                )}
                {manifest && (
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Build Status</dt>
                    <dd className="font-medium flex items-center gap-1">
                      {manifest.validation_passed === true ? (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                          Valid
                        </>
                      ) : manifest.validation_passed === false ? (
                        <>
                          <AlertCircle className="h-3.5 w-3.5 text-red-600" />
                          Invalid
                        </>
                      ) : (
                        "Not built"
                      )}
                    </dd>
                  </div>
                )}
              </dl>
            </div>

            <div className="p-3 bg-gray-50 rounded-lg border">
              <h3 className="font-medium text-gray-800">Redactions</h3>
              <p className="text-sm text-gray-500 mt-2">
                {redactionCandidates?.length ?? 0} candidate(s) detected
              </p>
              <Button variant="outline" className="w-full mt-2 justify-start gap-2" onClick={handleDetectRedactions} disabled={detectRedactions.isPending}>
                {detectRedactions.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Scan for PII
              </Button>
              <Button variant="outline" className="w-full mt-2 justify-start gap-2" onClick={() => setActiveTab("redactions")}>
                <Check className="h-4 w-4" />
                Review Candidates
              </Button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}