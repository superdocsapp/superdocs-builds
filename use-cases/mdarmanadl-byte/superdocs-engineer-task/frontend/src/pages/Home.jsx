import { useState } from "react";

import Upload from "../components/Upload";
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
  const hasChanges = Boolean(updatedHtml) && updatedHtml !== originalHtml;

  return (
    <div className="app-shell">
      {/* Top navigation */}
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">S</div>

          <div className="brand-name">SuperDocs</div>

          <div className="brand-divider" />

          <div className="brand-page">Document Editor</div>
        </div>

        <div className="topbar-actions">
          {sessionId && (
            <div className="status-pill">
              <span className="status-dot" />
              Ready
            </div>
          )}

          {sessionId && <ExportButton sessionId={sessionId} />}
        </div>
      </header>

      {/* Main workspace */}
      <main className="workspace">
        {/* Document side */}
        <section className="document-panel">
          <div className="panel-toolbar">
            <div className="toolbar-title">Document</div>

            {hasDocument && (
              <div className="toolbar-meta">
                {hasChanges ? (
                  <>
                    <span className="change-dot" />
                    Changes proposed
                  </>
                ) : (
                  "No changes"
                )}
              </div>
            )}
          </div>

          <div className="document-area">
            {!hasDocument ? (
              <div className="empty-workspace">
                <div className="empty-content">
                  <div className="empty-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path
                        d="M7 3h7l5 5v13H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"
                        strokeWidth="1.7"
                      />
                      <path d="M14 3v6h5" strokeWidth="1.7" />
                    </svg>
                  </div>

                  <h1>Start with a document</h1>

                  <p>
                    Upload a document and use AI to review, rewrite and improve
                    it.
                  </p>

                  <div className="upload-card">
                    <Upload
                      setSessionId={setSessionId}
                      setDocumentHtml={(html) => {
                        setOriginalHtml(html);
                        setUpdatedHtml(html);
                      }}
                    />
                  </div>

                  <div className="feature-row">
                    <span>AI editing</span>
                    <span>Human approval</span>
                    <span>PDF export</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="document-view">
                {/* Original */}
                <div className="document-column">
                  <div className="document-label">
                    <span>Original</span>
                    <small>Source</small>
                  </div>

                  <div className="paper">
                    <div
                      dangerouslySetInnerHTML={{
                        __html: originalHtml,
                      }}
                    />
                  </div>
                </div>

                {/* Updated */}
                <div className="document-column">
                  <div className="document-label">
                    <span className="ai-label">AI Version</span>

                    {hasChanges && (
                      <small className="updated-label">Updated</small>
                    )}
                  </div>

                  <div className={`paper ${hasChanges ? "paper-updated" : ""}`}>
                    <div
                      dangerouslySetInnerHTML={{
                        __html: updatedHtml || originalHtml,
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* AI panel */}
        <aside className="ai-panel">
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
        </aside>
      </main>

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
