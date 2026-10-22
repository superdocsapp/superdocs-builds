import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Upload, Download, ArrowUpDown, Shield, FileText, Plus,
  Loader2, AlertCircle, AlertTriangle, CheckCircle2, RefreshCw, Send, Check, X, XCircle,
  ArrowUp, ArrowDown, Trash2, Info, Eye, Sparkles, Lock, CheckSquare
} from "lucide-react";
import { clsx } from "clsx";
import { usePacket } from "@/hooks/usePackets";
import {
  useDocuments, useUploadDocuments, useDeleteDocument, useReorderDocument, useDownloadDocument,
} from "@/hooks/useDocuments";
import { useProcessingStatus, useStartProcessing, useRetryDocument } from "@/hooks/useProcessing";
import { useAssignBates } from "@/hooks/useBates";
import { useBuildPacket, useDownloadPacket, useValidatePacket, useVerifyPacket } from "@/hooks/useExports";
import {
  useDetectRedactions, useRedactionCandidates, useApproveRedaction,
  useApplyRedaction, useApplyAllRedactions,
} from "@/hooks/useRedactions";
import { usePrivilegeDecisions, useMarkPrivilege } from "@/hooks/usePrivilege";
import { useAuditTrail } from "@/hooks/useAudit";
import {
  useRequestAIAnalysis, useAnalysisStatus, useApproveAIChanges, useContinueAIJob,
} from "@/hooks/useReview";
import { useToast } from "@/components/ui/use-toast";
import { DocumentPdfViewer } from "@/components/DocumentPdfViewer";
import { Modal } from "@/components/ui/modal";
import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import type {
  DocumentListResponse, PrivilegeDecision, PrivilegeStatus, PrivilegeCategory, RedactionCandidate,
} from "@/types/api";

const statusBadgeVariants: Record<string, "success" | "indigo" | "warning" | "purple" | "danger" | "default"> = {
  completed: "success",
  processing: "indigo",
  ocr: "warning",
  ai_analysis: "purple",
  waiting_review: "warning",
  queued: "default",
  failed: "danger",
  bates_assigned: "success",
  assembling: "indigo",
  approved: "success",
};

const privilegeBadgeVariants: Record<string, "danger" | "success" | "default"> = {
  privileged: "danger",
  not_privileged: "success",
  pending: "default",
};

const redactionBadgeVariants: Record<string, "default" | "warning" | "indigo" | "danger" | "success"> = {
  proposed: "default",
  pending_approval: "warning",
  approved: "indigo",
  rejected: "danger",
  applied: "success",
  verified: "success",
  failed: "danger",
};

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 dark:text-slate-400 text-slate-500">
      <Loader2 className="h-9 w-9 animate-spin text-indigo-500 mb-3" />
      <span className="text-xs font-mono dark:text-slate-300 text-slate-600">{message}</span>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="dark:bg-rose-950/40 bg-rose-50 border dark:border-rose-800/80 border-rose-200 rounded-2xl p-6 backdrop-blur-md shadow-xl">
      <div className="flex items-center gap-2.5">
        <AlertCircle className="h-5 w-5 text-rose-500" />
        <span className="text-sm font-semibold dark:text-rose-200 text-rose-800">Operation Error</span>
      </div>
      <p className="text-xs dark:text-rose-300 text-rose-700 mt-2 font-mono">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 px-3 py-1.5 text-xs font-medium bg-rose-600 hover:bg-rose-500 text-white rounded-xl transition-colors shadow-sm"
        >
          Retry Action
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
  const { data: status } = useAnalysisStatus(packetId, selectedDoc.id, jobId ?? "");

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

  const handleApprove = async (approve: boolean) => {
    if (!jobId || !status?.changes) return;
    try {
      await approveAIChanges.mutateAsync({
        packetId,
        documentId: selectedDoc.id,
        data: { job_id: jobId, approved: approve, changes: status.changes ?? [] },
      });
      toast({ title: approve ? "Changes approved" : "Changes rejected" });
    } catch (err: any) {
      toast({ title: "Failed to process changes", description: err?.message, variant: "destructive" });
    }
  };

  const handleContinue = async (decision: boolean) => {
    if (!jobId) return;
    try {
      await continueAIJob.mutateAsync({
        packetId,
        documentId: selectedDoc.id,
        data: { job_id: jobId, continue_job: decision },
      });
      toast({ title: decision ? "Job continued" : "Job stopped" });
    } catch (err: any) {
      toast({ title: "Failed to continue job", description: err?.message, variant: "destructive" });
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="dark:bg-slate-900/80 bg-white rounded-2xl shadow-sm border dark:border-slate-800/90 border-slate-200 p-6 backdrop-blur-md">
        <div className="flex items-center gap-2.5 text-indigo-500">
          <Sparkles className="h-5 w-5" />
          <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">SuperDocs Intelligence Review</h2>
        </div>
        <p className="text-xs dark:text-slate-400 text-slate-600 mt-1">
          Target Exhibit: <span className="font-semibold dark:text-slate-200 text-slate-800">{selectedDoc.filename}</span> ({selectedDoc.page_count} pages)
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-xs font-mono uppercase tracking-wider dark:text-slate-400 text-slate-600 font-medium">
            Review Instructions
          </label>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={3}
            className="w-full px-4 py-3 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-100 text-slate-900 dark:placeholder-slate-500 placeholder-slate-400 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
            placeholder="Describe the review task for this exhibit..."
          />
          <button
            onClick={handleRequest}
            disabled={requestAIAnalysis.isPending}
            className="px-5 py-2.5 bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/25 disabled:opacity-50 transition-all flex items-center gap-2"
          >
            {requestAIAnalysis.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Request SuperDocs Analysis
          </button>
        </div>
      </div>

      {status?.status === "awaiting_approval" && status.changes && status.changes.length > 0 ? (
        <div className="dark:bg-slate-900/80 bg-white rounded-2xl shadow-sm border dark:border-slate-800/90 border-slate-200 p-6 space-y-4 backdrop-blur-md">
          <h3 className="text-sm font-semibold dark:text-white text-slate-900 uppercase tracking-wider font-mono">Proposed Changes Awaiting Review</h3>
          {status.changes.map((change: any) => (
            <div key={change.change_id} className="p-4 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-2">
              <p className="text-xs font-semibold text-sky-500 font-mono">{change.operation || "EDIT"}</p>
              {change.old_html && (
                <p className="text-xs dark:text-slate-400 text-slate-600">
                  <span className="font-semibold text-rose-500">Original:</span> {stripHtml(change.old_html).slice(0, 300)}
                </p>
              )}
              {change.new_html && (
                <p className="text-xs dark:text-slate-400 text-slate-600">
                  <span className="font-semibold text-emerald-500">Proposed:</span> {stripHtml(change.new_html).slice(0, 300)}
                </p>
              )}
            </div>
          ))}
          <div className="flex gap-2.5 pt-2">
            <button
              onClick={() => handleApprove(true)}
              disabled={approveAIChanges.isPending}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl shadow-md transition-all flex items-center gap-1.5"
            >
              <Check className="h-3.5 w-3.5" /> Approve All
            </button>
            <button
              onClick={() => handleApprove(false)}
              disabled={approveAIChanges.isPending}
              className="px-4 py-2 dark:bg-slate-800 dark:hover:bg-slate-700 bg-slate-100 hover:bg-slate-200 dark:text-slate-300 text-slate-700 text-xs font-semibold rounded-xl border dark:border-slate-700 border-slate-300 transition-all flex items-center gap-1.5"
            >
              <X className="h-3.5 w-3.5" /> Reject All
            </button>
          </div>
        </div>
      ) : status?.status === "awaiting_approval" && status.continue_prompt ? (
        <div className="dark:bg-slate-900/80 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-6 space-y-3 shadow-sm">
          <p className="text-sm dark:text-slate-300 text-slate-700">{String(status.continue_prompt)}</p>
          <div className="flex gap-2.5">
            <button
              onClick={() => handleContinue(true)}
              disabled={continueAIJob.isPending}
              className="px-4 py-2 bg-indigo-600 text-white text-xs font-semibold rounded-xl"
            >
              <Check className="h-3.5 w-3.5 inline mr-1" /> Continue
            </button>
            <button
              onClick={() => handleContinue(false)}
              disabled={continueAIJob.isPending}
              className="px-4 py-2 dark:bg-slate-800 bg-slate-100 dark:text-slate-300 text-slate-700 text-xs font-semibold rounded-xl border dark:border-slate-700 border-slate-300"
            >
              <X className="h-3.5 w-3.5 inline mr-1" /> Stop
            </button>
          </div>
        </div>
      ) : status?.error ? (
        <div className="dark:bg-rose-950/40 bg-rose-50 border dark:border-rose-800/80 border-rose-200 rounded-2xl p-4 flex items-center gap-2 text-rose-600 dark:text-rose-300 text-xs font-mono">
          <AlertCircle className="h-4 w-4 text-rose-500" />
          <span>{status.error}</span>
        </div>
      ) : (
        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800/80 border-slate-200 p-5 space-y-2 text-xs font-mono shadow-sm">
          <p className="dark:text-slate-400 text-slate-500">Analysis status: <span className="dark:text-white text-slate-900 font-semibold">{status?.status ?? "idle"}</span></p>
          {status?.result && (
            <pre className="p-3 dark:bg-slate-950 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 overflow-x-auto text-[11px] dark:text-slate-300 text-slate-700 max-h-64">
              {JSON.stringify(status.result, null, 2).slice(0, 2000)}
            </pre>
          )}
          {jobId && (
            <button
              onClick={() => setJobId(null)}
              className="mt-2 px-3 py-1.5 dark:bg-slate-800 bg-slate-100 dark:text-slate-400 text-slate-600 hover:text-slate-900 dark:hover:text-white rounded-lg text-xs"
            >
              Cancel Job
            </button>
          )}
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
    <div className="dark:bg-slate-900/70 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200 p-5 shadow-sm space-y-3 dark:hover:border-slate-700/80 hover:border-slate-300 transition-all">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-sm dark:text-white text-slate-900 truncate">{doc.filename}</p>
          <div className="flex items-center gap-2 mt-1.5 text-xs">
            <Badge variant={privilegeBadgeVariants[status] ?? "default"}>
              {status.replace("_", " ")}
            </Badge>
            {doc.bates_range && <span className="font-mono text-sky-500 text-[11px] dark:bg-sky-950/50 bg-sky-50 px-2 py-0.5 rounded border dark:border-sky-800/50 border-sky-200 font-semibold">{doc.bates_range}</span>}
            {decision?.reviewer && <span className="dark:text-slate-400 text-slate-500 text-xs">by {decision.reviewer}</span>}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as PrivilegeStatus)}
          className="px-3 py-2 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-200 text-slate-800 text-xs font-medium focus:ring-2 focus:ring-indigo-500 outline-none"
        >
          <option value="pending">Pending</option>
          <option value="privileged">Privileged</option>
          <option value="not_privileged">Not Privileged</option>
        </select>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as PrivilegeCategory | "")}
          disabled={status !== "privileged"}
          className="px-3 py-2 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-200 text-slate-800 text-xs font-medium focus:ring-2 focus:ring-indigo-500 outline-none disabled:opacity-40"
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
          className="px-3 py-2 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-200 text-slate-800 dark:placeholder-slate-500 placeholder-slate-400 text-xs focus:ring-2 focus:ring-indigo-500 outline-none disabled:opacity-40"
        />
      </div>
      {invalid && <p className="text-xs text-rose-500 font-mono">Reason is required for privileged documents.</p>}
      <div className="flex justify-end pt-1">
        <Button
          size="sm"
          variant="outline"
          disabled={isSaving || invalid || (status === "pending" && !decision)}
          onClick={() => onSave(doc.id, { status, category: category || undefined, reason: reason || undefined })}
          className="gap-1.5 text-xs font-semibold"
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
    <div className="max-w-4xl mx-auto space-y-5 animate-fade-in">
      <div className="dark:bg-slate-900/80 bg-white rounded-2xl shadow-sm border dark:border-slate-800/90 border-slate-200 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 backdrop-blur-md">
        <div>
          <div className="flex items-center gap-2">
            <Lock className="h-5 w-5 text-indigo-500" />
            <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">Privilege Review & Logging</h2>
          </div>
          <p className="text-xs dark:text-slate-400 text-slate-600 mt-1">
            Categorize privileged documents with legal rationale. Included in final privilege log.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-mono dark:text-slate-400 text-slate-600 uppercase">Reviewer:</label>
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className="px-3 py-1.5 dark:bg-slate-950 bg-white border dark:border-slate-700 border-slate-300 rounded-xl text-xs dark:text-white text-slate-900 w-36 focus:ring-2 focus:ring-indigo-500 outline-none"
          />
        </div>
      </div>
      {!documents || documents.length === 0 ? (
        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-12 text-center dark:text-slate-400 text-slate-500">
          No documents in packet. Upload documents to review privilege.
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
    () => [...new Set((candidates ?? []).filter((c: RedactionCandidate) => c.status === "approved").map((c: RedactionCandidate) => c.document_id))],
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
      toast({ title: "Redaction applied", description: "Byte-scrubbed and verified absent." });
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
    <div className="max-w-4xl mx-auto space-y-5 animate-fade-in">
      <div className="dark:bg-slate-900/80 bg-white rounded-2xl shadow-sm border dark:border-slate-800/90 border-slate-200 p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 backdrop-blur-md">
        <div>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-rose-500" />
            <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">PII Redaction Studio</h2>
          </div>
          <p className="text-xs dark:text-slate-400 text-slate-600 mt-1">
            {candidates?.length ?? 0} candidate(s) detected. Approve/reject candidates before applying byte-level scrubs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-mono dark:text-slate-400 text-slate-600 uppercase">Approver:</label>
          <input
            type="text"
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
            className="px-3 py-1.5 dark:bg-slate-950 bg-white border dark:border-slate-700 border-slate-300 rounded-xl text-xs dark:text-white text-slate-900 w-32 focus:ring-2 focus:ring-indigo-500 outline-none"
          />
          <Button
            onClick={handleApplyAll}
            disabled={approvedDocIds.length === 0 || applyAll.isPending}
            className="gap-1.5 text-xs font-semibold bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 shadow-md shadow-indigo-600/20"
          >
            {applyAll.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Apply All Approved ({approvedDocIds.length})
          </Button>
        </div>
      </div>

      {!candidates || candidates.length === 0 ? (
        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-12 text-center dark:text-slate-400 text-slate-500">
          No redaction candidates yet. Run "Detect Redactions" to scan for PII.
        </div>
      ) : (
        candidates.map((candidate) => (
          <div key={candidate.id} className="dark:bg-slate-900/70 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200 p-5 shadow-sm space-y-3 dark:hover:border-slate-700/80 hover:border-slate-300 transition-all">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-mono font-bold text-sm dark:text-white text-slate-900 dark:bg-slate-950/80 bg-slate-100 px-2.5 py-1 rounded-lg border dark:border-slate-800 border-slate-200 inline-block">
                  {candidate.matched_text}
                </p>
                <div className="flex flex-wrap items-center gap-2 mt-2 text-xs">
                  <Badge variant="purple">{candidate.category}</Badge>
                  <span className="dark:text-slate-400 text-slate-600 text-xs">{candidate.document_name}</span>
                  <span className="font-mono text-xs dark:text-slate-400 text-slate-500">Page {candidate.page_number}</span>
                  <Badge variant={redactionBadgeVariants[candidate.status] ?? "default"}>
                    {candidate.status.replace("_", " ")}
                  </Badge>
                  {candidate.proposed_by && (
                    <span className={clsx(
                      "px-2 py-0.5 rounded-full text-[10px] font-mono border",
                      candidate.proposed_by === "superdocs"
                        ? "dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800/60 bg-sky-50 text-sky-700 border-sky-200"
                        : "dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800/60 bg-amber-50 text-amber-700 border-amber-200"
                    )}>
                      {candidate.proposed_by === "superdocs" ? "SuperDocs AI" : "Local Fallback"}
                    </span>
                  )}
                  {candidate.approval?.approver && <span className="dark:text-slate-400 text-slate-500 text-xs">by {candidate.approval.approver}</span>}
                </div>
                {(candidate.context_before || candidate.context_after) && (
                  <p className="text-xs dark:text-slate-400 text-slate-600 mt-2.5 p-3 rounded-xl dark:bg-slate-950/60 bg-slate-50 border dark:border-slate-800/80 border-slate-200 font-mono">
                    {candidate.context_before && <span className="dark:text-slate-500 text-slate-400">…{candidate.context_before}</span>}
                    <span className="font-bold text-rose-500 dark:text-rose-300 dark:bg-rose-950/40 bg-rose-50 px-1 py-0.5 rounded border border-rose-200 dark:border-transparent"> {candidate.matched_text} </span>
                    {candidate.context_after && <span className="dark:text-slate-500 text-slate-400">{candidate.context_after}…</span>}
                  </p>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                {(candidate.status === "proposed" || candidate.status === "pending_approval") && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => handleApprove(candidate, true)} disabled={approveRedaction.isPending} className="gap-1 text-xs">
                      <Check className="h-3.5 w-3.5 text-emerald-500" /> Approve
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => handleApprove(candidate, false)} disabled={approveRedaction.isPending} className="gap-1 text-xs">
                      <X className="h-3.5 w-3.5 text-rose-500" /> Reject
                    </Button>
                  </>
                )}
                {candidate.status === "approved" && (
                  <Button size="sm" onClick={() => handleApply(candidate)} disabled={applyRedaction.isPending} className="gap-1 text-xs bg-emerald-600 hover:bg-emerald-500">
                    {applyRedaction.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                    Apply
                  </Button>
                )}
                {candidate.status === "applied" && (
                  <span className="text-xs text-emerald-500 flex items-center gap-1 font-mono">
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    Applied
                    {candidate.approval?.verified_at && <span className="text-teal-600 dark:text-teal-400">• Verified Absent</span>}
                  </span>
                )}
                {candidate.status === "rejected" && (
                  <span className="text-xs text-rose-500 flex items-center gap-1 font-mono">
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
    <div className="max-w-4xl mx-auto space-y-4 animate-fade-in">
      <div className="dark:bg-slate-900/80 bg-white rounded-2xl shadow-sm border dark:border-slate-800/90 border-slate-200 p-5 backdrop-blur-md">
        <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">Immutable Audit Trail & Ledger</h2>
        <p className="text-xs dark:text-slate-400 text-slate-600 mt-1 font-mono">{trail?.total_events ?? 0} total lifecycle events recorded.</p>
      </div>
      {isLoading ? (
        <LoadingState message="Loading audit trail..." />
      ) : !trail || trail.events.length === 0 ? (
        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-12 text-center dark:text-slate-400 text-slate-500">
          No audit events recorded yet.
        </div>
      ) : (
        trail.events.map((event) => (
          <div key={event.id} className="dark:bg-slate-900/70 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200 p-4 shadow-sm space-y-2">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="indigo">{event.event_type.replace(/_/g, " ")}</Badge>
                  {event.user_id && <span className="text-xs dark:text-slate-400 text-slate-500 font-mono">by {event.user_id}</span>}
                  {event.document_name && <span className="text-xs dark:text-slate-300 text-slate-700 font-medium">{event.document_name}</span>}
                </div>
                {event.metadata && (
                  <pre className="text-[11px] dark:bg-slate-950 bg-slate-50 border dark:border-slate-800/90 border-slate-200 rounded-xl p-3 mt-2 overflow-x-auto dark:text-slate-300 text-slate-700 font-mono">
                    {JSON.stringify(event.metadata, null, 2).slice(0, 500)}
                  </pre>
                )}
              </div>
              <span className="text-xs dark:text-slate-400 text-slate-500 font-mono shrink-0">
                {new Date(event.timestamp).toLocaleString()}
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ---------- Main Workspace Component ----------

export function PacketWorkspace() {
  const { packetId = "" } = useParams();
  const [activeTab, setActiveTab] = useState("documents");
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<any>(null);
  const [isBuildModalOpen, setIsBuildModalOpen] = useState(false);
  const [isDocInspectorOpen, setIsDocInspectorOpen] = useState(false);
  const [inspectingDoc, setInspectingDoc] = useState<DocumentListResponse | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const { data: packet, isLoading: packetLoading, error: packetError, refetch: refetchPacket } = usePacket(packetId);
  const { data: documents, isLoading: docsLoading, error: docsError, refetch: refetchDocs } = useDocuments(packetId);
  const { data: processingStatus, refetch: refetchProcessing } = useProcessingStatus(packetId);
  const { data: redactionCandidates, refetch: refetchRedactions } = useRedactionCandidates(packetId);

  const uploadMutation = useUploadDocuments(packetId);
  const startProcessing = useStartProcessing();
  const retryDocument = useRetryDocument();
  const assignBates = useAssignBates();
  const buildPacket = useBuildPacket();
  const validatePacket = useValidatePacket();
  const verifyPacket = useVerifyPacket();
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

  const handleConfirmBuild = async () => {
    setIsBuildModalOpen(false);
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

  const handleVerify = async () => {
    try {
      const result = await verifyPacket.mutateAsync(packetId);
      setVerifyResult(result);
      if (result.status === "VERIFIED") {
        toast({
          title: "Packet verified",
          description: `All ${result.checks.length} checks passed.`,
        });
      } else {
        const failed = result.checks.filter((c: any) => !c.passed);
        toast({
          title: "Verification failed",
          description: `${failed.length} check(s) failed.`,
          variant: "destructive",
        });
      }
    } catch (err: any) {
      setVerifyResult(null);
      toast({ title: "Verification failed", description: err?.message, variant: "destructive" });
    }
  };

  const handleDetectRedactions = async () => {
    try {
      const result = await detectRedactions.mutateAsync(packetId);
      refetchRedactions();
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
    const newOrder = direction === "up" ? index : index + 2;
    try {
      await reorderDocument.mutateAsync({ documentId: doc.id, newOrder });
      toast({ title: "Document reordered", description: "Bates numbers reassigned contiguously." });
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

  if (packetLoading) return <LoadingState message="Loading exhibit packet..." />;
  if (packetError) return <ErrorState message={packetError.message} onRetry={refetchPacket} />;
  if (!packet) return <ErrorState message="Packet not found." />;

  const batesStartLabel = packet.bates_prefix
    ? `${packet.bates_prefix}${String(packet.bates_start_number ?? 1).padStart(packet.bates_padding ?? 6, "0")}+`
    : "Not configured";

  const totalPagesCount = documents?.reduce((sum, d) => sum + (d.page_count ?? 0), 0) ?? 0;
  const unapprovedCandidates = (redactionCandidates ?? []).filter((c: RedactionCandidate) => c.status === "proposed" || c.status === "pending_approval");

  return (
    <div className="h-full flex flex-col dark:bg-slate-950 bg-slate-50 dark:text-slate-100 text-slate-900 font-sans transition-colors duration-200">
      {/* Top Workspace Header Bar */}
      <div className="p-4 px-6 border-b dark:border-slate-800/90 border-slate-200/90 dark:bg-slate-900/80 bg-white/90 backdrop-blur-xl shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-display font-bold dark:text-white text-slate-900 tracking-tight">{packet.name}</h1>
              <Badge variant="indigo" size="md">
                {batesStartLabel}
              </Badge>
            </div>
            <p className="text-xs font-mono dark:text-slate-400 text-slate-500 mt-1 flex items-center gap-2">
              <span>ID: {packet.id.slice(0, 8)}...</span>
              <span>•</span>
              <span className="dark:text-slate-200 text-slate-800 font-bold">{documents ? documents.length : 0}</span> documents
              <span>•</span>
              <span className="dark:text-slate-200 text-slate-800 font-bold">{totalPagesCount}</span> pages
            </p>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
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
              size="sm"
              className="gap-1.5 shadow-sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              Upload
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5 shadow-sm" onClick={handleProcess} disabled={startProcessing.isPending}>
              {startProcessing.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowUpDown className="h-3.5 w-3.5" />}
              Process
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5 shadow-sm" onClick={handleAssignBates} disabled={assignBates.isPending}>
              {assignBates.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Shield className="h-3.5 w-3.5" />}
              Assign Bates
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5 shadow-sm" onClick={handleDetectRedactions} disabled={detectRedactions.isPending}>
              {detectRedactions.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Lock className="h-3.5 w-3.5" />}
              Detect PII
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 shadow-sm dark:bg-indigo-950/40 dark:border-indigo-700/60 dark:text-indigo-300 bg-indigo-50 border-indigo-300 text-indigo-700 dark:hover:bg-indigo-900/60 hover:bg-indigo-100"
              onClick={() => setIsBuildModalOpen(true)}
              disabled={buildPacket.isPending || validatePacket.isPending}
            >
              {buildPacket.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
              Build Packet
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5 shadow-sm" onClick={handleVerify} disabled={verifyPacket.isPending}>
              {verifyPacket.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
              Verify
            </Button>
            <Button
              size="sm"
              className="gap-1.5 bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 text-white shadow-md shadow-indigo-600/25"
              onClick={handleExport}
              disabled={downloadPacket.isPending}
            >
              {downloadPacket.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              Export
            </Button>
          </div>
        </div>
      </div>

      {/* Pre-Flight Build Confirmation Modal */}
      <Modal
        isOpen={isBuildModalOpen}
        onClose={() => setIsBuildModalOpen(false)}
        title="Pre-Flight Packet Build Checklist"
        description="Verify packet parameters before compiling covers, stamps, exhibit index, and cryptographic manifest."
        footer={
          <>
            <button
              type="button"
              onClick={() => setIsBuildModalOpen(false)}
              className="px-4 py-2 text-xs font-medium dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:bg-slate-800 bg-slate-100 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmBuild}
              disabled={buildPacket.isPending || validatePacket.isPending}
              className="px-5 py-2 text-xs font-semibold bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 text-white rounded-xl shadow-lg shadow-indigo-600/25 flex items-center gap-2"
            >
              {(buildPacket.isPending || validatePacket.isPending) ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Compiling...
                </>
              ) : (
                <>
                  <CheckSquare className="h-4 w-4" />
                  Proceed & Build Final Packet
                </>
              )}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
              <span className="text-[10px] font-mono dark:text-slate-400 text-slate-500 uppercase">Total Exhibits</span>
              <p className="text-lg font-bold dark:text-white text-slate-900 font-mono mt-0.5">{documents?.length ?? 0}</p>
            </div>
            <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
              <span className="text-[10px] font-mono dark:text-slate-400 text-slate-500 uppercase">Total Pages</span>
              <p className="text-lg font-bold dark:text-white text-slate-900 font-mono mt-0.5">{totalPagesCount}</p>
            </div>
          </div>

          <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-1 text-xs">
            <div className="flex justify-between items-center">
              <span className="dark:text-slate-400 text-slate-600">Bates Stamping Range:</span>
              <span className="font-mono font-bold text-sky-500">{batesStartLabel}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="dark:text-slate-400 text-slate-600">Unapproved Redactions:</span>
              <span className={clsx("font-mono font-bold", unapprovedCandidates.length > 0 ? "text-amber-500" : "text-emerald-500")}>
                {unapprovedCandidates.length} pending
              </span>
            </div>
          </div>

          {unapprovedCandidates.length > 0 && (
            <div className="p-3 dark:bg-amber-950/40 bg-amber-50 border dark:border-amber-800/80 border-amber-300 rounded-xl text-xs dark:text-amber-300 text-amber-800 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
              <span>You have unapproved redactions. Only approved redactions will be byte-scrubbed in the final deliverable.</span>
            </div>
          )}
        </div>
      </Modal>

      {/* Slide-out Document Quick Inspector Drawer */}
      <Drawer
        isOpen={isDocInspectorOpen}
        onClose={() => {
          setIsDocInspectorOpen(false);
          setInspectingDoc(null);
        }}
        title={
          <div className="flex items-center gap-2 truncate">
            <FileText className="h-5 w-5 text-indigo-500 shrink-0" />
            <span className="truncate">{inspectingDoc?.filename}</span>
          </div>
        }
        subtitle={inspectingDoc ? `Document ID: ${inspectingDoc.id}` : undefined}
        footer={
          inspectingDoc && (
            <div className="flex items-center justify-between w-full">
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs"
                onClick={() => handleDownloadDocument(inspectingDoc)}
              >
                <Download className="h-3.5 w-3.5" />
                Download Original
              </Button>
              <Button
                size="sm"
                className="gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white"
                onClick={() => {
                  setSelectedDocId(inspectingDoc.id);
                  setActiveTab("documents");
                  setIsDocInspectorOpen(false);
                }}
              >
                <Eye className="h-3.5 w-3.5" />
                View in Workspace
              </Button>
            </div>
          )
        }
      >
        {inspectingDoc && (
          <div className="space-y-6 text-xs">
            {/* Properties Grid */}
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
                <span className="text-[10px] font-mono dark:text-slate-500 text-slate-400 uppercase">Format Type</span>
                <p className="text-sm font-bold dark:text-slate-200 text-slate-800 font-mono mt-0.5">{inspectingDoc.document_type.toUpperCase()}</p>
              </div>
              <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
                <span className="text-[10px] font-mono dark:text-slate-500 text-slate-400 uppercase">Pages</span>
                <p className="text-sm font-bold dark:text-slate-200 text-slate-800 font-mono mt-0.5">{inspectingDoc.page_count}</p>
              </div>
            </div>

            {/* Bates & Privilege */}
            <div className="p-4 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-3">
              <div className="flex items-center justify-between">
                <span className="dark:text-slate-400 text-slate-600 font-mono uppercase text-[10px]">Bates Range</span>
                <span className="font-mono text-sky-500 font-bold dark:bg-sky-950/60 bg-sky-50 px-2 py-0.5 rounded border dark:border-sky-800/60 border-sky-200">
                  {inspectingDoc.bates_range || "Not Assigned"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="dark:text-slate-400 text-slate-600 font-mono uppercase text-[10px]">Privilege Classification</span>
                <Badge variant={privilegeBadgeVariants[inspectingDoc.privilege_status] ?? "default"}>
                  {(inspectingDoc.privilege_status ?? "pending").replace("_", " ")}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="dark:text-slate-400 text-slate-600 font-mono uppercase text-[10px]">Processing State</span>
                <Badge variant={statusBadgeVariants[inspectingDoc.status] ?? "default"}>
                  {inspectingDoc.status.replace("_", " ")}
                </Badge>
              </div>
            </div>

            {/* Description Summary */}
            {inspectingDoc.description && (
              <div className="p-4 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-1">
                <span className="text-[10px] font-mono dark:text-slate-500 text-slate-400 uppercase">Content Summary</span>
                <p className="dark:text-slate-300 text-slate-700 leading-relaxed pt-1">{inspectingDoc.description}</p>
                {inspectingDoc.description_source && (
                  <span className="inline-block mt-2 text-[10px] font-mono text-sky-500 dark:bg-sky-950/40 bg-sky-50 px-2 py-0.5 rounded border dark:border-sky-800/40 border-sky-200">
                    Source: {inspectingDoc.description_source.replace("_", " ")}
                  </span>
                )}
              </div>
            )}

            {/* Ingestion & Searchability */}
            <div className="p-3.5 dark:bg-slate-950/70 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-1">
              <span className="text-[10px] font-mono dark:text-slate-500 text-slate-400 uppercase">OCR / Searchable Status</span>
              <p className="dark:text-slate-300 text-slate-700 font-mono font-medium">
                {inspectingDoc.is_searchable ? "Searchable text layer active" : "Non-searchable / Raw scan"}
              </p>
            </div>
          </div>
        )}
      </Drawer>

      {/* Verification Results Banner */}
      {verifyResult && (
        <div className={clsx(
          "border-b px-6 py-4 backdrop-blur-md animate-fade-in shadow-inner",
          verifyResult.status === "VERIFIED"
            ? "dark:bg-emerald-950/40 bg-emerald-50 dark:border-emerald-800/80 border-emerald-300"
            : verifyResult.status === "NOT_BUILT"
              ? "dark:bg-amber-950/40 bg-amber-50 dark:border-amber-800/80 border-amber-300"
              : "dark:bg-rose-950/40 bg-rose-50 dark:border-rose-800/80 border-rose-300"
        )}>
          <div className="flex items-start gap-4 max-w-6xl mx-auto">
            <div className="shrink-0 mt-0.5">
              {verifyResult.status === "VERIFIED" ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              ) : verifyResult.status === "NOT_BUILT" ? (
                <AlertTriangle className="h-6 w-6 text-amber-500" />
              ) : (
                <XCircle className="h-6 w-6 text-rose-500" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-3">
                <h3 className={clsx(
                  "text-base font-display font-bold",
                  verifyResult.status === "VERIFIED" ? "dark:text-emerald-200 text-emerald-800" :
                  verifyResult.status === "NOT_BUILT" ? "dark:text-amber-200 text-amber-800" : "dark:text-rose-200 text-rose-800"
                )}>
                  {verifyResult.status === "VERIFIED" ? "PACKET CRYPTOGRAPHICALLY VERIFIED" :
                   verifyResult.status === "NOT_BUILT" ? "NOT YET BUILT" : "VERIFICATION FAILED"}
                </h3>
                {verifyResult.bates_start && verifyResult.bates_end && (
                  <span className="text-xs dark:text-slate-300 text-slate-700 font-mono dark:bg-slate-900/80 bg-white px-2 py-0.5 rounded border dark:border-slate-700 border-slate-300">
                    {verifyResult.bates_start} → {verifyResult.bates_end}
                  </span>
                )}
              </div>
              <div className="mt-1 text-xs dark:text-slate-400 text-slate-600 font-mono">
                {verifyResult.page_count} pages · {verifyResult.exhibits} exhibits
              </div>
              <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2">
                {verifyResult.checks.map((check: any) => (
                  <div key={check.name} className="flex items-center gap-2 text-xs font-mono">
                    {check.passed ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-rose-500 shrink-0" />
                    )}
                    <span className={clsx("truncate", check.passed ? "dark:text-slate-300 text-slate-700" : "text-rose-600 font-semibold")}>
                      {check.name.replace(/_/g, " ")}
                    </span>
                    {check.detail && !check.passed && (
                      <span className="text-[10px] text-rose-500 truncate hidden lg:inline" title={check.detail}>
                        ({check.detail})
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <button
              onClick={() => setVerifyResult(null)}
              className="shrink-0 dark:text-slate-400 text-slate-500 hover:text-slate-900 dark:hover:text-white p-1 rounded-lg dark:hover:bg-slate-800 hover:bg-slate-200 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Main Workspace Split View */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Navigator Sidebar */}
        <aside className="w-72 border-r dark:border-slate-800/80 border-slate-200/90 dark:bg-slate-900/60 bg-white flex flex-col overflow-hidden backdrop-blur-md shrink-0">
          <div className="p-3 border-b dark:border-slate-800/80 border-slate-200/80">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="documents" className="text-xs py-1">Docs</TabsTrigger>
                <TabsTrigger value="processing" className="text-xs py-1">Queue</TabsTrigger>
                <TabsTrigger value="review" className="text-xs py-1">Review</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {activeTab === "documents" && (
              <div className="space-y-2">
                {docsLoading && <LoadingState message="Loading documents..." />}
                {docsError && <ErrorState message={docsError.message} onRetry={refetchDocs} />}
                {!docsLoading && !docsError && (!documents || documents.length === 0) && (
                  <div className="text-center py-12 dark:text-slate-500 text-slate-400">
                    <FileText className="h-8 w-8 mx-auto mb-2 dark:text-slate-600 text-slate-400" />
                    <p className="text-xs font-medium dark:text-slate-400 text-slate-600 font-display">No documents yet.</p>
                    <p className="text-[11px] dark:text-slate-500 text-slate-400 mt-1">Upload PDF, DOCX, or scans.</p>
                  </div>
                )}
                {sortedDocs.map((doc, index) => (
                  <div
                    key={doc.id}
                    className={clsx(
                      "p-3 rounded-xl border transition-all duration-150 group",
                      selectedDoc?.id === doc.id
                        ? "border-indigo-500/50 bg-indigo-500/10 shadow-sm"
                        : "dark:border-slate-800/80 border-slate-200/80 dark:bg-slate-900/40 bg-slate-50/70 dark:hover:border-slate-700 hover:border-slate-300 dark:hover:bg-slate-800/40 hover:bg-slate-100"
                    )}
                  >
                    <button
                      onClick={() => setSelectedDocId(doc.id)}
                      className="w-full text-left"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="font-semibold text-xs dark:text-white text-slate-900 truncate group-hover:text-indigo-500 transition-colors">{doc.filename}</p>
                          <div className="flex items-center gap-1.5 mt-1.5 text-[10px]">
                            <Badge variant={statusBadgeVariants[doc.status] ?? "default"}>
                              {doc.status.replace("_", " ")}
                            </Badge>
                            <Badge variant={privilegeBadgeVariants[doc.privilege_status] ?? "default"}>
                              {(doc.privilege_status ?? "pending").replace("_", " ")}
                            </Badge>
                          </div>
                          {doc.bates_range && (
                            <p className="text-xs text-sky-500 mt-1 font-mono font-medium">{doc.bates_range}</p>
                          )}
                          {doc.description && (
                            <div className="mt-1">
                              <p className="text-xs dark:text-slate-400 text-slate-500 truncate" title={doc.description}>{doc.description}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    </button>
                    <div className="flex items-center gap-1 mt-2.5 pt-2 border-t dark:border-slate-800/80 border-slate-200/80">
                      <button
                        title="Quick Inspect"
                        onClick={() => {
                          setInspectingDoc(doc);
                          setIsDocInspectorOpen(true);
                        }}
                        className="p-1 rounded-lg dark:hover:bg-slate-800 hover:bg-slate-200 dark:text-slate-400 text-slate-500 hover:text-indigo-500 transition-colors"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Move up"
                        onClick={() => handleMoveDocument(doc, "up")}
                        disabled={index === 0 || reorderDocument.isPending}
                        className="p-1 rounded-lg dark:hover:bg-slate-800 hover:bg-slate-200 dark:text-slate-400 text-slate-500 hover:text-slate-900 dark:hover:text-white disabled:opacity-30 transition-colors"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Move down"
                        onClick={() => handleMoveDocument(doc, "down")}
                        disabled={index === sortedDocs.length - 1 || reorderDocument.isPending}
                        className="p-1 rounded-lg dark:hover:bg-slate-800 hover:bg-slate-200 dark:text-slate-400 text-slate-500 hover:text-slate-900 dark:hover:text-white disabled:opacity-30 transition-colors"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Download original"
                        onClick={() => handleDownloadDocument(doc)}
                        disabled={downloadDocument.isPending}
                        className="p-1 rounded-lg dark:hover:bg-slate-800 hover:bg-slate-200 dark:text-slate-400 text-slate-500 hover:text-sky-500 disabled:opacity-30 transition-colors"
                      >
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        title="Delete document"
                        onClick={() => handleDeleteDocument(doc)}
                        disabled={deleteDocument.isPending}
                        className="p-1 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-500/10 dark:text-slate-400 text-slate-500 hover:text-rose-500 disabled:opacity-30 ml-auto transition-colors"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
                {!docsLoading && !docsError && (
                  <Button variant="outline" size="sm" className="w-full justify-start gap-2 mt-2" onClick={() => fileInputRef.current?.click()}>
                    <Plus className="h-4 w-4" />
                    Add Documents
                  </Button>
                )}
              </div>
            )}

            {activeTab === "processing" && (
              <div className="space-y-3">
                <div className="p-3.5 dark:bg-sky-950/30 bg-sky-50 rounded-xl border dark:border-sky-800/60 border-sky-200">
                  <p className="text-xs font-semibold dark:text-sky-300 text-sky-800">Processing Pipeline</p>
                  <p className="text-[11px] dark:text-sky-400/80 text-sky-600 font-mono mt-1">
                    {processingStatus?.status_breakdown?.queued ?? 0} queued |{" "}
                    {processingStatus?.status_breakdown?.processing ?? 0} processing |{" "}
                    {processingStatus?.status_breakdown?.failed ?? 0} failed
                  </p>
                </div>
                <div className="space-y-2">
                  {processingStatus?.documents?.filter((d) => d.status !== "completed").map((doc) => (
                    <div key={doc.id} className="p-3 dark:bg-slate-900 bg-white rounded-xl border dark:border-slate-800 border-slate-200 space-y-1.5 shadow-sm">
                      <p className="text-xs font-semibold dark:text-white text-slate-900 truncate">{doc.filename}</p>
                      <div className="flex items-center gap-2">
                        <Badge variant={statusBadgeVariants[doc.status] ?? "default"}>
                          {doc.status.replace("_", " ")}
                        </Badge>
                        {doc.error && <span className="text-[11px] text-rose-500 truncate">{doc.error}</span>}
                      </div>
                      {doc.status === "failed" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="mt-2 text-xs"
                          onClick={() => retryDocument.mutate({ packetId, documentId: doc.id })}
                          disabled={retryDocument.isPending}
                        >
                          <RefreshCw className="h-3 w-3" />
                          Retry
                        </Button>
                      )}
                    </div>
                  ))}
                  {(!processingStatus?.documents || processingStatus.documents.length === 0) && (
                    <p className="text-center text-xs dark:text-slate-500 text-slate-400 py-6">
                      No documents in the queue.
                    </p>
                  )}
                  {processingStatus?.documents?.every((d) => d.status === "completed") && (
                    <p className="text-center text-xs text-emerald-500 font-medium py-6 font-mono">
                      All documents processed.
                    </p>
                  )}
                </div>
              </div>
            )}

            {activeTab === "review" && (
              <div className="space-y-3">
                <div className="p-3.5 dark:bg-indigo-950/30 bg-indigo-50 rounded-xl border dark:border-indigo-800/60 border-indigo-200">
                  <p className="text-xs font-semibold dark:text-indigo-300 text-indigo-800">AI Review Queue</p>
                  <p className="text-[11px] dark:text-indigo-400 text-indigo-600 font-mono mt-1">
                    {processingStatus?.status_breakdown?.waiting_review ?? 0} documents awaiting review
                  </p>
                </div>
                <div className="space-y-2">
                  {processingStatus?.documents
                    ?.filter((d) => d.status === "waiting_review" || d.status === "ai_analysis")
                    .map((doc) => (
                      <div key={doc.id} className="p-3 dark:bg-slate-900 bg-white rounded-xl border dark:border-slate-800 border-slate-200 shadow-sm">
                        <p className="text-xs font-semibold dark:text-white text-slate-900 truncate">{doc.filename}</p>
                        <p className="text-[11px] dark:text-slate-400 text-slate-500 mt-1">
                          {doc.status === "waiting_review" ? "Awaiting approval of AI changes" : "AI analysis in progress"}
                        </p>
                      </div>
                    ))}
                  {(!processingStatus?.documents?.some((d) => d.status === "waiting_review" || d.status === "ai_analysis")) && (
                    <p className="text-center text-xs dark:text-slate-500 text-slate-400 py-6">No documents awaiting review.</p>
                  )}
                  <Button variant="outline" size="sm" className="w-full justify-start gap-2 text-xs" onClick={() => setActiveTab("ai-changes")}>
                    <Send className="h-3.5 w-3.5" />
                    Go to AI Review Panel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* Center Panel */}
        <main className="flex-1 flex flex-col overflow-hidden min-w-0 dark:bg-slate-950 bg-slate-50">
          <div className="p-3 px-6 border-b dark:border-slate-800 border-slate-200 dark:bg-slate-900/50 bg-white/70 flex items-center justify-between">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="hidden md:flex">
              <TabsList>
                <TabsTrigger value="documents">Document Viewer</TabsTrigger>
                <TabsTrigger value="ai-changes">AI Changes</TabsTrigger>
                <TabsTrigger value="privilege">Privilege</TabsTrigger>
                <TabsTrigger value="redactions">Redactions</TabsTrigger>
                <TabsTrigger value="audit">Audit Trail</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="flex-1 overflow-auto p-6 dark:bg-slate-950 bg-slate-50">
            {activeTab === "ai-changes" && selectedDoc && (
              <AiChangesPanel packetId={packetId} selectedDoc={selectedDoc} />
            )}
            {activeTab === "ai-changes" && !selectedDoc && (
              <div className="max-w-4xl mx-auto dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-12 text-center dark:text-slate-400 text-slate-500 shadow-sm">
                <FileText className="h-10 w-10 mx-auto dark:text-slate-600 text-slate-400 mb-3" />
                <p className="dark:text-slate-300 text-slate-700 font-medium font-display">Select a document to run AI analysis</p>
                <p className="text-xs dark:text-slate-500 text-slate-400 mt-1">Choose an exhibit from the left sidebar to generate proposals.</p>
              </div>
            )}
            {activeTab === "privilege" && <PrivilegePanel packetId={packetId} documents={documents} />}
            {activeTab === "redactions" && <RedactionsPanel packetId={packetId} candidates={redactionCandidates} />}
            {activeTab === "audit" && <AuditPanel packetId={packetId} />}

            {activeTab === "documents" && (
              <div className="max-w-5xl mx-auto dark:bg-slate-900/70 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200/90 p-6 shadow-sm space-y-6">
                {selectedDoc ? (
                  <>
                    <div className="flex items-center justify-between pb-4 border-b dark:border-slate-800/80 border-slate-200/80">
                      <div>
                        <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">{selectedDoc.filename}</h2>
                        <p className="text-xs dark:text-slate-400 text-slate-500 font-mono mt-0.5">Exhibit Page Count: {selectedDoc.page_count}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5 text-xs"
                          onClick={() => {
                            setInspectingDoc(selectedDoc);
                            setIsDocInspectorOpen(true);
                          }}
                        >
                          <Info className="h-3.5 w-3.5 text-indigo-500" />
                          Inspect
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5 text-xs"
                          onClick={() => handleDownloadDocument(selectedDoc)}
                          disabled={downloadDocument.isPending}
                        >
                          {downloadDocument.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                          Download
                        </Button>
                        <Badge variant={statusBadgeVariants[selectedDoc.status] ?? "default"}>
                          {selectedDoc.status.replace("_", " ")}
                        </Badge>
                        <Badge variant={privilegeBadgeVariants[selectedDoc.privilege_status] ?? "default"}>
                          {(selectedDoc.privilege_status ?? "pending").replace("_", " ")}
                        </Badge>
                      </div>
                    </div>

                    <div className="flex-1 min-h-[500px]">
                      <DocumentPdfViewer
                        packetId={packetId}
                        documentId={selectedDoc.id}
                        fileName={selectedDoc.filename}
                        pageCount={selectedDoc.page_count}
                        batesRange={selectedDoc.bates_range}
                        onDownload={() => handleDownloadDocument(selectedDoc)}
                      />
                    </div>

                    <div className="grid grid-cols-3 gap-4 text-xs font-mono pt-4 border-t dark:border-slate-800/80 border-slate-200/80">
                      <div className="p-3 rounded-xl dark:bg-slate-950/60 bg-slate-50 border dark:border-slate-800 border-slate-200">
                        <p className="dark:text-slate-500 text-slate-400 uppercase tracking-wider text-[10px]">Document Type</p>
                        <p className="dark:text-slate-200 text-slate-800 font-semibold mt-1">{selectedDoc.document_type.toUpperCase()}</p>
                      </div>
                      <div className="p-3 rounded-xl dark:bg-slate-950/60 bg-slate-50 border dark:border-slate-800 border-slate-200">
                        <p className="dark:text-slate-500 text-slate-400 uppercase tracking-wider text-[10px]">Total Pages</p>
                        <p className="dark:text-slate-200 text-slate-800 font-semibold mt-1">{selectedDoc.page_count}</p>
                      </div>
                      <div className="p-3 rounded-xl dark:bg-slate-950/60 bg-slate-50 border dark:border-slate-800 border-slate-200">
                        <p className="dark:text-slate-500 text-slate-400 uppercase tracking-wider text-[10px]">Bates Range</p>
                        <p className="text-sky-500 font-semibold mt-1">{selectedDoc.bates_range || "Not assigned"}</p>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-20 dark:text-slate-500 text-slate-400">
                    <FileText className="h-12 w-12 mx-auto mb-3 dark:text-slate-600 text-slate-400" />
                    <p className="text-sm dark:text-slate-300 text-slate-700 font-medium font-display">Select a document from the left sidebar to preview</p>
                    <p className="text-xs dark:text-slate-500 text-slate-400 mt-1">Preview native PDFs, OCR extracted text layers, and Bates stamps.</p>
                  </div>
                )}
              </div>
            )}

            {activeTab === "processing" && (
              <div className="max-w-5xl mx-auto dark:bg-slate-900/70 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200/90 p-6 shadow-sm space-y-4">
                <h2 className="text-lg font-display font-bold dark:text-white text-slate-900">Document Processing Status</h2>
                <div className="space-y-2.5">
                  {processingStatus?.documents?.map((doc) => (
                    <div key={doc.id} className="flex items-center justify-between dark:bg-slate-950/60 bg-slate-50 border dark:border-slate-800 border-slate-200 rounded-xl p-4">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold dark:text-white text-slate-900 truncate">{doc.filename}</p>
                        <p className="text-xs font-mono dark:text-slate-400 text-slate-500 mt-0.5">
                          {doc.page_count} pages • {doc.is_searchable ? "searchable text" : "no text layer"}
                          {doc.error && ` • ${doc.error}`}
                        </p>
                      </div>
                      <Badge variant={statusBadgeVariants[doc.status] ?? "default"}>
                        {doc.status.replace("_", " ")}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}