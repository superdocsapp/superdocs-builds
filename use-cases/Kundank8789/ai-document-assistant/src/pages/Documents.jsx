import {
  FileText,
  Search,
  Upload,
  Sparkles,
  FileCheck2,
  Clock,
  MoreHorizontal,
  Trash2,
  Download,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { useRef, useState, useEffect } from "react";
import {
  uploadDocument,
  generateReport,
  getJobStatus,
  approveChanges,
  exportDocument,
} from "../services/superdocs";

function Documents() {
  const [searchQuery, setSearchQuery] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isClearing, setIsClearing] = useState(false);
  const [documents, setDocuments] = useState([]);

  // SuperDocs session state
  const [sessionId] = useState(() => `session_${Date.now()}`);
  const [jobId, setJobId] = useState(null);
  const [report, setReport] = useState(""); // Now holds HTML from SuperDocs
  const [pendingChanges, setPendingChanges] = useState([]);

  // New approval-specific states
  const [approvalChanges, setApprovalChanges] = useState([]);
  const [approvalJobId, setApprovalJobId] = useState(null);
  const [approvalStatus, setApprovalStatus] = useState(null);

  // Human review queue
  const [reviewItems, setReviewItems] = useState([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewActionId, setReviewActionId] = useState(null);

  const fileInputRef = useRef(null);

  // Load documents from server on mount
  useEffect(() => {
    const fetchDocuments = async () => {
      try {
        setIsLoading(true);
        const response = await fetch("http://localhost:5000/api/documents");
        const data = await response.json();
        if (response.ok) {
          const formattedDocs = data.documents.map((doc, index) => ({
            id: Date.now() + index,
            name: doc.originalName || doc.filename,
            type: doc.fileType?.toUpperCase() || "FILE",
            updated: doc.uploadedAt ? new Date(doc.uploadedAt).toLocaleString() : "Just now",
            status: "Ready",
            statusClass: "bg-emerald-50 text-emerald-700",
            serverFilename: doc.filename,
            size: doc.size || 0,
          }));
          setDocuments(formattedDocs);
        }
      } catch (error) {
        console.error("Error fetching documents:", error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchDocuments();
  }, []);

  // Load human review queue on page load
  useEffect(() => {
    fetchReviewItems();
  }, []);

  // Upload document via SuperDocs
  const handleUpload = async (event) => {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;

    setIsUploading(true);

    try {
      const uploadedDocs = [];
      for (const file of files) {
        const result = await uploadDocument(file, sessionId);
        // Keep local document list for UI
        uploadedDocs.push({
          id: Date.now() + Math.random(),
          name: result.document.originalName,
          type: file.name.split(".").pop().toUpperCase(),
          updated: "Just now",
          status: "Uploaded",
          statusClass: "bg-blue-50 text-blue-700",
          serverFilename: result.document.filename,
          size: result.document.size,
        });
      }
      setDocuments((prev) => [...prev, ...uploadedDocs]);
      console.log("Uploaded successfully:", uploadedDocs);
      event.target.value = "";
    } catch (error) {
      console.error("Upload failed:", error);
      alert(`Upload failed: ${error.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  // Clear all documents
  const handleClearAll = async () => {
    if (!confirm("Are you sure you want to clear all documents?")) return;
    try {
      setIsClearing(true);
      const response = await fetch("http://localhost:5000/api/clear", { method: "DELETE" });
      if (response.ok) {
        setDocuments([]);
        setReport("");
        setJobId(null);
        setPendingChanges([]);
        setApprovalChanges([]);
        setApprovalJobId(null);
        setApprovalStatus(null);
        setReviewItems([]);
        console.log("All documents cleared");
      } else {
        const data = await response.json();
        alert(data.message || "Failed to clear documents");
      }
    } catch (error) {
      console.error("Clear error:", error);
      alert("Failed to clear documents");
    } finally {
      setIsClearing(false);
    }
  };

  // Poll SuperDocs job until it completes (updated)
  const pollJob = async (id) => {
    try {
      while (true) {
        const result = await getJobStatus(id);

        console.log("SuperDocs job status:", result);

        // -----------------------------------------
        // JOB COMPLETED
        // -----------------------------------------
        if (result.status === "completed") {
          const jobResult = result.result || {};
          const documentChanges = jobResult.document_changes || {};

          console.log("Completed SuperDocs job:", jobResult);

          // -----------------------------------------
          // 1. Prefer the actual generated document
          // -----------------------------------------
          if (documentChanges.updated_html) {
            setReport(documentChanges.updated_html);
          } else if (jobResult.response) {
            setReport(jobResult.response);
          }

          // -----------------------------------------
          // 2. Handle proposed/pending changes
          // -----------------------------------------
          const changes = Array.isArray(documentChanges.changes)
            ? documentChanges.changes
            : [];

          const pending = changes.filter(
            (change) =>
              change.status !== "auto_approved" &&
              change.status !== "approved"
          );

          if (pending.length > 0) {
            setPendingChanges(pending);
            setApprovalChanges(pending);
            setApprovalJobId(id);
            setApprovalStatus("pending");
          } else {
            setPendingChanges([]);
            setApprovalChanges([]);

            if (changes.some((change) => change.status === "auto_approved")) {
              setApprovalStatus("auto_approved");
            } else {
              setApprovalStatus("completed");
            }

            setApprovalJobId(null);
          }

          // Save the completed job
          setJobId(id);

          return jobResult;
        }

        // -----------------------------------------
        // JOB FAILED
        // -----------------------------------------
        if (
          result.status === "failed" ||
          result.status === "error" ||
          result.status === "cancelled"
        ) {
          throw new Error(
            result.message ||
              result.error ||
              "SuperDocs job failed"
          );
        }

        // -----------------------------------------
        // STILL PROCESSING
        // -----------------------------------------
        await new Promise((resolve) =>
          setTimeout(resolve, 1500)
        );
      }
    } catch (error) {
      console.error("Job polling failed:", error);
      throw error;
    }
  };

  // ============================================================
  // HUMAN REVIEW QUEUE
  // ============================================================

  const fetchReviewItems = async () => {
    try {
      setReviewLoading(true);

      const response = await fetch(
        "http://localhost:5000/api/review"
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.message || "Failed to load review items"
        );
      }

      console.log("Review queue:", data);

      setReviewItems(data.items || []);
    } catch (error) {
      console.error("Failed to load review queue:", error);
    } finally {
      setReviewLoading(false);
    }
  };

  const handleReviewDecision = async (
    id,
    decision
  ) => {
    try {
      setReviewActionId(id);

      const reviewerNote =
        window.prompt(
          `${decision === "approved" ? "Approve" : "Reject"} this finding? Add an optional note:`
        ) || "";

      const response = await fetch(
        `http://localhost:5000/api/review/${id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision,
            reviewerNote,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.message || "Failed to update review"
        );
      }

      console.log("Review decision:", data);

      // Update UI immediately
      setReviewItems((prev) =>
        prev.map((item) =>
          item.id === id
            ? {
                ...item,
                status: decision,
                decision,
                reviewerNote,
              }
            : item
        )
      );
    } catch (error) {
      console.error(
        "Review decision failed:",
        error
      );

      alert(error.message);
    } finally {
      setReviewActionId(null);
    }
  };

  // Generate report via SuperDocs chat
  const handleGenerateReport = async () => {
    if (documents.length === 0) {
      alert("Please upload at least one document first.");
      return;
    }

    // Prevent duplicate requests
    if (isGenerating) {
      return;
    }

    setIsGenerating(true);
    setReport("");
    setPendingChanges([]);
    setApprovalChanges([]);
    setApprovalJobId(null);
    setApprovalStatus(null);

    try {
      const result = await generateReport({
        sessionId,
        documentHtml: report,
        message:
          "Analyze the uploaded event documents and generate a grounded post-event impact report. Identify important facts, conflicts, recommendations, and proposed changes.",
      });

      console.log("SuperDocs chat response:", result);

      const newJobId = result.job_id || result.jobId;

      if (newJobId) {
        setJobId(newJobId);

        await pollJob(newJobId);

        // Load AI findings created by backend
        await fetchReviewItems();
      } else {
        // Handle direct/synchronous response
        const jobResult = result.result || result;

        if (jobResult.response) {
          setReport(jobResult.response);
        }

        if (jobResult.document_changes) {
          const changes =
            jobResult.document_changes.changes || [];

          if (Array.isArray(changes)) {
            setPendingChanges(changes);
            setApprovalChanges(changes);
            setApprovalJobId(null); // no job id for direct response
            setApprovalStatus("direct");
          }
        }
      }
    } catch (error) {
      console.error("Report generation failed:", error);
      alert(error.message);
    } finally {
      // Only becomes false AFTER the job has finished
      setIsGenerating(false);
    }
  };

  // Approve pending changes
  const handleApproveChanges = async () => {
    // Use the main jobId if available, otherwise fallback to approvalJobId
    const targetJobId = jobId || approvalJobId;
    if (!targetJobId) {
      alert("No SuperDocs job is available.");
      return;
    }
    setIsApproving(true);
    try {
      const result = await approveChanges({
        sessionId,
        jobId: targetJobId,
        changes: pendingChanges, // using pendingChanges for approval
      });
      console.log("Approval result:", result);
      if (result.report) setReport(result.report);
      if (result.document_html) setReport(result.document_html);
      setPendingChanges([]);
      setApprovalChanges([]);
      setApprovalJobId(null);
      setApprovalStatus("approved");
    } catch (error) {
      console.error("Approval failed:", error);
      alert(error.message);
    } finally {
      setIsApproving(false);
    }
  };

  // Export report as PDF
  const handleExport = async () => {
    if (!report) {
      alert("No report to export. Generate a report first.");
      return;
    }
    setIsExporting(true);
    try {
      const blob = await exportDocument({
        sessionId,
        format: "pdf",
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "impact-report.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Export failed:", error);
      alert(error.message);
    } finally {
      setIsExporting(false);
    }
  };

  // Filtered documents
  const filteredDocuments = documents.filter((doc) =>
    doc.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const totalDocuments = documents.length;
  const aiReadyDocuments = documents.filter((doc) => doc.status === "Ready").length;

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <FileText size={18} />
          <span>Events / Tech Summit 2026</span>
        </div>
        <div className="mt-3 flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h1 className="text-4xl font-bold text-slate-900">Documents</h1>
            <p className="mt-2 text-lg text-slate-500">
              Manage event documents and use AI to prepare your report.
            </p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleClearAll}
              disabled={isClearing || documents.length === 0}
              className="flex items-center justify-center gap-2 rounded-xl bg-red-500 px-5 py-3 font-semibold text-white transition hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Trash2 size={20} />
              {isClearing ? "Clearing..." : "Clear All"}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-3 font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Upload size={20} />
              {isUploading ? "Uploading..." : "Upload Document"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleUpload}
              accept=".pdf,.docx,.xlsx,.csv,.txt"
            />
          </div>
        </div>
      </div>

      {/* AI Assistant Card */}
      <section className="rounded-3xl bg-gradient-to-r from-indigo-600 to-violet-600 p-8 text-white shadow-lg">
        <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-center">
          <div>
            <div className="flex items-center gap-2 text-indigo-100">
              <Sparkles size={20} />
              <span className="text-sm font-semibold tracking-wide">
                AI DOCUMENT ASSISTANT
              </span>
            </div>
            <h2 className="mt-4 text-3xl font-bold">
              Turn your event documents into insights
            </h2>
            <p className="mt-3 max-w-2xl text-indigo-100">
              Upload event files and let AI help you analyze content,
              extract important information, and prepare your post-event report.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <button
              onClick={handleGenerateReport}
              disabled={isGenerating || isUploading || documents.length === 0}
              className="flex items-center justify-center gap-3 rounded-2xl bg-white px-8 py-5 font-semibold text-indigo-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isGenerating ? "Generating..." : "Generate Report"}
            </button>
            {report && (
              <button
                onClick={handleExport}
                disabled={isExporting}
                className="flex items-center justify-center gap-3 rounded-2xl bg-emerald-500 px-8 py-5 font-semibold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Download size={20} />
                {isExporting ? "Exporting..." : "Export PDF"}
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Pending Changes – Approval Section */}
      {pendingChanges.length > 0 && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
          <h3 className="text-lg font-bold text-amber-800 flex items-center gap-2">
            <Clock size={20} /> Proposed Changes
          </h3>
          <ul className="mt-2 list-disc pl-5 text-amber-700">
            {pendingChanges.map((change, idx) => (
              <li key={idx}>{change}</li>
            ))}
          </ul>
          <div className="mt-4 flex gap-3">
            <button
              onClick={handleApproveChanges}
              disabled={isApproving}
              className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2 font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
            >
              <CheckCircle size={18} />
              {isApproving ? "Approving..." : "Approve Changes"}
            </button>
            <button
              onClick={() => {
                setPendingChanges([]);
                setApprovalChanges([]);
                setApprovalJobId(null);
                setApprovalStatus("rejected");
              }}
              className="flex items-center gap-2 rounded-xl bg-slate-200 px-5 py-2 font-semibold text-slate-700 transition hover:bg-slate-300"
            >
              <XCircle size={18} />
              Reject
            </button>
          </div>
        </div>
      )}

      {/* Generated Report Display - now renders HTML */}
      {report && (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-indigo-600">
                Generated Report
              </p>

              <h2 className="mt-1 text-2xl font-bold text-slate-900">
                Post-Event Impact Report
              </h2>
            </div>

            <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
              Complete
            </span>
          </div>

          <div className="mt-6 rounded-xl bg-slate-50 p-6 prose prose-slate max-w-none leading-7">
            <div dangerouslySetInnerHTML={{ __html: report }} />
          </div>

          <p className="mt-6 text-sm text-slate-400">
            Generated at: {new Date().toLocaleString()}
          </p>
        </section>
      )}

      {/* Search + Stats */}
      <section className="grid gap-6 lg:grid-cols-[1fr_auto]">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-5 shadow-sm">
          <Search size={21} className="text-slate-400" />
          <input
            type="text"
            placeholder="Search documents..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full border-0 py-4 text-slate-700 outline-none placeholder:text-slate-400"
          />
        </div>
        <div className="flex items-center gap-6 rounded-2xl border border-slate-200 bg-white px-6 py-4 shadow-sm">
          <div>
            <p className="text-sm text-slate-500">Total Documents</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{totalDocuments}</p>
          </div>
          <div className="h-10 w-px bg-slate-200" />
          <div>
            <p className="text-sm text-slate-500">AI Ready</p>
            <p className="mt-1 text-2xl font-bold text-emerald-600">{aiReadyDocuments}</p>
          </div>
        </div>
      </section>

      {/* Document List */}
      <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-8 py-6">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Event Documents</h2>
            <p className="mt-1 text-slate-500">
              {isLoading ? "Loading..." : `${documents.length} documents available for AI analysis.`}
            </p>
          </div>
          <span className="rounded-full bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700">
            {filteredDocuments.length} Files
          </span>
        </div>
        <div className="divide-y divide-slate-100">
          {isLoading ? (
            <div className="px-8 py-12 text-center text-slate-500">Loading documents...</div>
          ) : filteredDocuments.length > 0 ? (
            filteredDocuments.map((document) => (
              <div
                key={document.id}
                className="flex flex-col gap-4 px-8 py-6 transition hover:bg-slate-50 md:flex-row md:items-center md:justify-between"
              >
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                    <FileText size={24} />
                  </div>
                  <div>
                    <h3 className="font-semibold text-slate-800">{document.name}</h3>
                    <div className="mt-1 flex items-center gap-3 text-sm text-slate-500">
                      <span>{document.type}</span>
                      <span className="h-1 w-1 rounded-full bg-slate-300" />
                      <span>{document.updated}</span>
                      {document.size && (
                        <>
                          <span className="h-1 w-1 rounded-full bg-slate-300" />
                          <span>{(document.size / 1024).toFixed(1)} KB</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-5">
                  <span className={`rounded-full px-3 py-1.5 text-sm font-medium ${document.statusClass}`}>
                    {document.status}
                  </span>
                  <button className="text-slate-400 transition hover:text-slate-700">
                    <MoreHorizontal size={22} />
                  </button>
                </div>
              </div>
            ))
          ) : (
            <div className="px-8 py-12 text-center text-slate-500">
              No documents uploaded yet. Click "Upload Document" to get started.
            </div>
          )}
        </div>
      </section>

      {/* AI Workflow Info */}
      <section className="grid gap-6 md:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Upload size={23} />
          </div>
          <h3 className="mt-5 text-lg font-bold text-slate-800">1. Upload</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Add event reports, feedback, sponsor documents, and other files.
          </p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-violet-50 text-violet-600">
            <Sparkles size={23} />
          </div>
          <h3 className="mt-5 text-lg font-bold text-slate-800">2. Generate</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            AI processes your documents and generates a comprehensive impact report.
          </p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
            <FileCheck2 size={23} />
          </div>
          <h3 className="mt-5 text-lg font-bold text-slate-800">3. Export</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Download the final report in PDF format for sharing.
          </p>
        </div>
      </section>
    </div>
  );
}

export default Documents;