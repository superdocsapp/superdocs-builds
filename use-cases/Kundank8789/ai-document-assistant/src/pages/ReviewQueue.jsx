import { useEffect, useState } from "react";
import {
  Check,
  X,
  AlertTriangle,
  Lightbulb,
  Loader2,
  RefreshCw,
  FileDown,
} from "lucide-react";

const API_BASE = "http://localhost:5000";

function ReviewQueue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);

  const loadReviewQueue = async () => {
    try {
      setLoading(true);
      setError("");

      const response = await fetch(`${API_BASE}/api/review`);

      if (!response.ok) {
        throw new Error("Failed to load review queue");
      }

      const data = await response.json();

      setItems(data.items || []);
    } catch (err) {
      console.error(err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReviewQueue();
  }, []);

  // ============================================================
  // EXPORT HANDLER (UPDATED)
  // ============================================================

  const handleExport = async () => {
    try {
      setExporting(true);

      // Get the session created when the SuperDocs report was generated
      const sessionId = localStorage.getItem("superdocs.sessionId");

      console.log("========== EXPORT FINAL REPORT ==========");
      console.log("SuperDocs session ID:", sessionId);

      if (!sessionId) {
        throw new Error(
          "SuperDocs session ID not found. Please generate the report again."
        );
      }

      const response = await fetch(
        `${API_BASE}/api/superdocs/export`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            session_id: sessionId,
            format: "pdf",
          }),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();

        console.error("Export API error:", errorText);

        throw new Error(
          `Export failed (${response.status}): ${errorText}`
        );
      }

      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);

      const link = document.createElement("a");
      link.href = url;
      link.download = "Tech-Summit-2026-Impact-Report.pdf";

      document.body.appendChild(link);
      link.click();
      link.remove();

      window.URL.revokeObjectURL(url);

      console.log("✅ FINAL REPORT EXPORTED SUCCESSFULLY");
    } catch (error) {
      console.error("Export error:", error);

      alert(
        error.message || "Failed to export final report"
      );
    } finally {
      setExporting(false);
    }
  };

  // ============================================================
  // REVIEW DECISION HANDLER
  // ============================================================

  const handleDecision = async (id, decision) => {
    try {
      setProcessing(id);

      const response = await fetch(
        `${API_BASE}/api/review/${id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision,
            reviewerNote: "",
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.message || "Failed to update review"
        );
      }

      setItems((current) =>
        current.map((item) =>
          item.id === id
            ? {
                ...item,
                status: decision,
                decision,
              }
            : item
        )
      );
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setProcessing(null);
    }
  };

  const pendingCount = items.filter(
    (item) => item.status === "pending"
  ).length;

  const approvedCount = items.filter(
    (item) => item.status === "approved"
  ).length;

  const rejectedCount = items.filter(
    (item) => item.status === "rejected"
  ).length;

  const getIcon = (type) => {
    if (type === "document_conflict") {
      return <AlertTriangle size={20} />;
    }

    return <Lightbulb size={20} />;
  };

  const getTypeLabel = (type) => {
    if (type === "document_conflict") {
      return "DOCUMENT CONFLICT";
    }

    if (type === "recommendation") {
      return "AI RECOMMENDATION";
    }

    return "PROPOSED CHANGE";
  };

  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loader2
          size={32}
          className="animate-spin text-indigo-600"
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">

      {/* Header */}

      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500">
            Events / Tech Summit 2026
          </p>

          <h1 className="mt-2 text-3xl font-bold text-slate-900">
            Review Queue
          </h1>

          <p className="mt-2 max-w-2xl text-slate-500">
            Review AI-generated findings before they are
            included in the final event impact report.
          </p>
        </div>

        <button
          onClick={loadReviewQueue}
          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>

      {/* Summary */}

      <div className="grid gap-5 md:grid-cols-3">

        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
          <p className="text-sm font-medium text-amber-700">
            Pending Review
          </p>

          <p className="mt-2 text-3xl font-bold text-amber-900">
            {pendingCount}
          </p>
        </div>

        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <p className="text-sm font-medium text-emerald-700">
            Approved
          </p>

          <p className="mt-2 text-3xl font-bold text-emerald-900">
            {approvedCount}
          </p>
        </div>

        <div className="rounded-2xl border border-red-200 bg-red-50 p-5">
          <p className="text-sm font-medium text-red-700">
            Rejected
          </p>

          <p className="mt-2 text-3xl font-bold text-red-900">
            {rejectedCount}
          </p>
        </div>

      </div>

      {/* Error */}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Empty */}

      {items.length === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center">
          <Check
            size={40}
            className="mx-auto text-emerald-500"
          />

          <h2 className="mt-4 text-lg font-bold text-slate-900">
            Review queue is clear
          </h2>

          <p className="mt-2 text-sm text-slate-500">
            There are no AI findings waiting for review.
          </p>
        </div>
      )}

      {/* Review Items */}

      <div className="space-y-5">

        {items.map((item) => {

          const isPending =
            item.status === "pending";

          const isApproved =
            item.status === "approved";

          const isRejected =
            item.status === "rejected";

          return (
            <div
              key={item.id}
              className="rounded-2xl border border-slate-200 bg-white shadow-sm"
            >

              {/* Card Header */}

              <div className="flex items-start justify-between border-b border-slate-100 p-6">

                <div className="flex gap-4">

                  <div
                    className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                      item.type ===
                      "document_conflict"
                        ? "bg-amber-50 text-amber-600"
                        : "bg-indigo-50 text-indigo-600"
                    }`}
                  >
                    {getIcon(item.type)}
                  </div>

                  <div>
                    <div className="text-xs font-semibold tracking-wide text-slate-400">
                      {getTypeLabel(item.type)}
                    </div>

                    <h2 className="mt-1 text-lg font-bold text-slate-900">
                      {item.title}
                    </h2>
                  </div>

                </div>

                {/* Status */}

                <span
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${
                    isPending
                      ? "bg-amber-50 text-amber-700"
                      : isApproved
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  {item.status.toUpperCase()}
                </span>

              </div>

              {/* Finding */}

              <div className="p-6">

                <p className="text-sm leading-7 text-slate-600">
                  {typeof item.finding === "string"
                    ? item.finding
                    : JSON.stringify(
                        item.finding
                      )}
                </p>

                {/* Confidence */}

                <div className="mt-5 flex items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium">
                    AI confidence:
                  </span>

                  <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600">
                    {item.confidence}
                  </span>
                </div>

                {/* Actions */}

                {isPending && (
                  <div className="mt-6 flex gap-3 border-t border-slate-100 pt-5">

                    <button
                      disabled={processing === item.id}
                      onClick={() =>
                        handleDecision(
                          item.id,
                          "approved"
                        )
                      }
                      className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {processing === item.id ? (
                        <Loader2
                          size={16}
                          className="animate-spin"
                        />
                      ) : (
                        <Check size={16} />
                      )}

                      Approve
                    </button>

                    <button
                      disabled={processing === item.id}
                      onClick={() =>
                        handleDecision(
                          item.id,
                          "rejected"
                        )
                      }
                      className="flex items-center gap-2 rounded-xl border border-red-200 bg-white px-5 py-2.5 text-sm font-semibold text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <X size={16} />

                      Reject
                    </button>

                  </div>
                )}

              </div>

            </div>
          );
        })}

      </div>

      {/* Completion Block */}

      {items.length > 0 && pendingCount === 0 && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <Check size={22} />
              </div>

              <div>
                <h3 className="font-bold text-emerald-900">
                  Review complete
                </h3>

                <p className="text-sm text-emerald-700">
                  All AI findings have been reviewed.
                </p>

                <p className="mt-1 text-xs text-emerald-600">
                  {approvedCount} approved · {rejectedCount} rejected
                </p>
              </div>
            </div>

            <button
              onClick={handleExport}
              disabled={exporting}
              className="flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {exporting ? (
                <>
                  <Loader2 size={17} className="animate-spin" />
                  Exporting...
                </>
              ) : (
                <>
                  <FileDown size={17} />
                  Export Final Report
                </>
              )}
            </button>

          </div>
        </div>
      )}

    </div>
  );
}

export default ReviewQueue;