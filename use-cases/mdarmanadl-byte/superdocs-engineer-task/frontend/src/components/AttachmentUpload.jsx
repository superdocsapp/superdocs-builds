import { useState } from "react";

import Upload from "../components/Upload";
import AttachmentUpload from "../components/AttachmentUpload";
import Chat from "../components/Chat";
import ApprovalModal from "../components/ApprovalModel";
import ExportButton from "../components/ExportButton";

export default function Home() {
  const [sessionId, setSessionId] = useState("");
  const [originalHtml, setOriginalHtml] = useState("");
  const [updatedHtml, setUpdatedHtml] = useState("");
  const [response, setResponse] = useState("");
  const [jobId, setJobId] = useState("");
  const [pendingChanges, setPendingChanges] = useState([]);
  const [showApproval, setShowApproval] = useState(false);
  const [lastPrompt, setLastPrompt] = useState("");

  const hasDocument = Boolean(originalHtml);
  const hasChanges = updatedHtml && updatedHtml !== originalHtml;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* =====================================================
          HEADER
      ===================================================== */}

      <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="flex h-16 w-full items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Logo */}

          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 shadow-sm">
              <svg
                className="h-5 w-5 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
                />

                <polyline
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  points="14 2 14 8 20 8"
                />

                <line
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  x1="8"
                  y1="13"
                  x2="16"
                  y2="13"
                />

                <line
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  x1="8"
                  y1="17"
                  x2="13"
                  y2="17"
                />
              </svg>
            </div>

            <div>
              <h1 className="text-xl font-bold tracking-tight text-slate-900">
                SuperDocs
                <span className="text-indigo-600"> AI</span>
              </h1>

              <p className="hidden text-xs text-slate-500 sm:block">
                Intelligent document editing
              </p>
            </div>
          </div>

          {/* Right side */}

          <div className="flex items-center gap-3">
            {sessionId && (
              <div className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 sm:flex">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />

                <span className="text-xs font-semibold text-emerald-700">
                  Active Session
                </span>
              </div>
            )}

            {sessionId && <ExportButton sessionId={sessionId} />}
          </div>
        </div>
      </header>

      {/* =====================================================
          FULL WIDTH WORKSPACE
      ===================================================== */}

      <main className="w-full p-3 sm:p-5 lg:p-6">
        <div className="grid w-full gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          {/* =================================================
              LEFT SIDE — DOCUMENT WORKSPACE
          ================================================= */}

          <section className="min-w-0 space-y-5">
            {/* ===============================================
                UPLOAD
            =============================================== */}

            <div className="w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <h2 className="text-sm font-bold text-slate-900">Document</h2>

                  <p className="mt-0.5 text-xs text-slate-500">
                    Upload and prepare your document for AI editing
                  </p>
                </div>

                {sessionId && (
                  <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                    Ready
                  </span>
                )}
              </div>

              <div className="p-5">
                <Upload
                  setSessionId={setSessionId}
                  setDocumentHtml={(html) => {
                    setOriginalHtml(html);
                    setUpdatedHtml(html);
                  }}
                />

                {sessionId && (
                  <div className="mt-5 border-t border-slate-100 pt-5">
                    <AttachmentUpload sessionId={sessionId} />
                  </div>
                )}
              </div>
            </div>

            {/* ===============================================
                DOCUMENT AREA
            =============================================== */}

            {hasDocument ? (
              <div className="w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                {/* Document toolbar */}

                <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                  <div>
                    <h2 className="text-sm font-bold text-slate-900 sm:text-base">
                      Document Preview
                    </h2>

                    <p className="mt-0.5 text-xs text-slate-500">
                      Compare the original document with the AI-edited version
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5">
                      <span className="h-2 w-2 rounded-full bg-slate-400" />

                      <span className="text-xs font-medium text-slate-600">
                        Original
                      </span>
                    </div>

                    <div
                      className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 ${
                        hasChanges
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-slate-50 text-slate-400"
                      }`}
                    >
                      <span
                        className={`h-2 w-2 rounded-full ${
                          hasChanges ? "bg-emerald-500" : "bg-slate-300"
                        }`}
                      />

                      <span className="text-xs font-medium">AI Version</span>
                    </div>
                  </div>
                </div>

                {/* ===========================================
                    SIDE BY SIDE DOCUMENTS
                =========================================== */}

                <div className="grid w-full grid-cols-1 lg:grid-cols-2">
                  {/* ORIGINAL */}

                  <div className="min-w-0 border-b border-slate-200 lg:border-b-0 lg:border-r">
                    <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-200">
                        <svg
                          className="h-4 w-4 text-slate-600"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="2"
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                          />
                        </svg>
                      </div>

                      <div>
                        <p className="text-sm font-semibold text-slate-800">
                          Original Document
                        </p>

                        <p className="text-[11px] text-slate-400">
                          Before AI changes
                        </p>
                      </div>
                    </div>

                    <div className="h-[75vh] overflow-auto bg-slate-100 p-4 sm:p-6">
                      <div
                        className="mx-auto min-h-[1000px] w-full max-w-[794px] bg-white p-8 shadow-md sm:p-10"
                        dangerouslySetInnerHTML={{
                          __html: originalHtml,
                        }}
                      />
                    </div>
                  </div>

                  {/* UPDATED */}

                  <div className="min-w-0">
                    <div className="flex items-center gap-3 border-b border-indigo-100 bg-indigo-50/60 px-5 py-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-100">
                        <svg
                          className="h-4 w-4 text-indigo-600"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="2"
                            d="M13 10V3L4 14h7v7l9-11h-7z"
                          />
                        </svg>
                      </div>

                      <div>
                        <p className="text-sm font-semibold text-slate-800">
                          AI Version
                        </p>

                        <p className="text-[11px] text-slate-400">
                          Latest proposed document
                        </p>
                      </div>
                    </div>

                    <div className="h-[75vh] overflow-auto bg-slate-100 p-4 sm:p-6">
                      <div
                        className={`mx-auto min-h-[1000px] w-full max-w-[794px] bg-white p-8 shadow-md sm:p-10 ${
                          hasChanges ? "ring-1 ring-emerald-200" : ""
                        }`}
                        dangerouslySetInnerHTML={{
                          __html: updatedHtml || originalHtml,
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              /* =============================================
                 EMPTY DOCUMENT STATE
              ============================================= */

              <div className="flex min-h-[650px] w-full items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white">
                <div className="max-w-md px-6 text-center">
                  <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-3xl bg-indigo-50">
                    <svg
                      className="h-9 w-9 text-indigo-500"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.8"
                        d="M7 3h10a2 2 0 012 2v14a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2z"
                      />

                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.8"
                        d="M9 8h6M9 12h6M9 16h4"
                      />
                    </svg>
                  </div>

                  <h3 className="mt-6 text-xl font-bold text-slate-900">
                    No document yet
                  </h3>

                  <p className="mt-2 text-sm leading-6 text-slate-500">
                    Upload a document above and start making intelligent edits
                    with SuperDocs AI.
                  </p>
                </div>
              </div>
            )}
          </section>

          {/* =================================================
              RIGHT SIDE — AI
          ================================================= */}

          <aside className="min-w-0">
            <div className="xl:sticky xl:top-[84px]">
              <div className="flex h-fit w-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                {/* AI HEADER */}

                <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-5 py-5 text-white">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15">
                        <svg
                          className="h-5 w-5"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth="1.8"
                            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                          />
                        </svg>
                      </div>

                      <div>
                        <h2 className="font-bold">AI Editor</h2>

                        <p className="text-xs text-indigo-100">
                          Describe what you want to change
                        </p>
                      </div>
                    </div>

                    <span className="rounded-full bg-white/15 px-2.5 py-1 text-[10px] font-bold tracking-wider">
                      AI
                    </span>
                  </div>
                </div>

                {/* CHAT */}

                <div className="p-5">
                  <Chat
                    sessionId={sessionId}
                    response={response}
                    setResponse={setResponse}
                    setJobId={setJobId}
                    setLastPrompt={setLastPrompt}
                    setPendingChanges={setPendingChanges}
                    setUpdatedDocumentHtml={setUpdatedHtml}
                    openApproval={() => setShowApproval(true)}
                  />
                </div>

                {/* SESSION */}

                {sessionId && (
                  <div className="border-t border-slate-100 bg-slate-50 px-5 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-medium text-slate-500">
                        Session ID
                      </span>

                      <span className="max-w-[220px] truncate rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-mono text-[10px] text-slate-500">
                        {sessionId}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </aside>
        </div>
      </main>

      {/* =====================================================
          APPROVAL
      ===================================================== */}

      <ApprovalModal
        open={showApproval}
        onClose={() => setShowApproval(false)}
        sessionId={sessionId}
        jobId={jobId}
        pendingChanges={pendingChanges}
        setResponse={setResponse}
        lastPrompt={lastPrompt}
        setUpdatedDocumentHtml={setUpdatedHtml}
      />
    </div>
  );
}
