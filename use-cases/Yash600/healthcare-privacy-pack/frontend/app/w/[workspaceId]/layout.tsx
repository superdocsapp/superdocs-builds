"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, DocType, DocumentOut, FindingOut, WorkspaceOut, fileToBase64 } from "@/lib/api";
import NavTabs from "../../NavTabs";
import { IconPlus, IconClipboard, IconWorkflow, IconFileText, IconUpload, IconAlertTriangle, IconTrash, IconSparkle } from "../../icons";

function DocumentTree({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedDocId = searchParams.get("doc") || "";

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [findings, setFindings] = useState<FindingOut[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [docType, setDocType] = useState<DocType>("policy");
  const [parentPolicyId, setParentPolicyId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Second creation path alongside upload: ask the AI to draft a document
  // from scratch, using this account's uploaded SuperDocs templates (see
  // backend's TEMPLATE_LIBRARY / POST /workspaces/{id}/documents/draft).
  const [addMode, setAddMode] = useState<"upload" | "draft">("upload");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [drafting, setDrafting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, finds] = await Promise.all([
        api.listWorkspaceDocuments(workspaceId),
        api.listFindings(workspaceId, "open"),
      ]);
      setDocuments(docs);
      setFindings(finds);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const policies = documents.filter((d) => d.doc_type === "policy");
  const proceduresFor = (policyId: string) => documents.filter((d) => d.parent_policy_id === policyId);

  const select = (id: string) => {
    const hubHref = `/w/${workspaceId}`;
    router.push(`${hubHref}?doc=${id}`);
  };

  const remove = async (doc: DocumentOut, e: React.MouseEvent) => {
    e.stopPropagation();
    const isPolicy = doc.doc_type === "policy";
    const childCount = isPolicy ? proceduresFor(doc.id).length : 0;
    if (childCount > 0) {
      setError(
        `"${doc.title}" still has ${childCount} procedure(s) grouped under it. Delete those first, then delete the policy.`
      );
      return;
    }
    const confirmed = window.confirm(
      `Delete "${doc.title}" permanently? This removes it and everything tied to it (sections, references, proposed changes) from this workspace. This can't be undone.`
    );
    if (!confirmed) return;

    setDeletingId(doc.id);
    setError(null);
    try {
      await api.deleteDocument(doc.id);
      if (selectedDocId === doc.id) {
        router.push(pathname);
      }
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setDeletingId(null);
    }
  };

  const upload = async () => {
    if (!file || !title.trim()) return;
    if (docType === "procedure" && !parentPolicyId) return;
    setUploading(true);
    setError(null);
    try {
      const fileBase64 = await fileToBase64(file);
      await api.uploadDocument(workspaceId, {
        filename: file.name, fileBase64, docType, title: title.trim(),
        parentPolicyId: docType === "procedure" ? parentPolicyId : undefined,
      });
      setTitle("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setShowAdd(false);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  };

  const draft = async () => {
    if (!draftPrompt.trim() || !title.trim()) return;
    if (docType === "procedure" && !parentPolicyId) return;
    setDrafting(true);
    setError(null);
    try {
      await api.draftDocument(workspaceId, {
        docType, title: title.trim(), prompt: draftPrompt.trim(),
        parentPolicyId: docType === "procedure" ? parentPolicyId : undefined,
      });
      setTitle("");
      setDraftPrompt("");
      setShowAdd(false);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div className="sidebar-section">
      <div className="row between" style={{ padding: "0 12px 6px" }}>
        <div className="sidebar-section-label" style={{ padding: 0 }}>Documents</div>
        <button className="ghost" onClick={() => setShowAdd((v) => !v)} title="Add a document" style={{ padding: 2 }}>
          <IconPlus size={14} />
        </button>
      </div>

      {error && <div className="error-banner" style={{ margin: "0 8px 8px", fontSize: 11.5, padding: "8px 10px" }}>{error}</div>}

      {policies.length === 0 && <div className="faint" style={{ padding: "0 12px 8px" }}>No policies uploaded yet.</div>}

      {policies.map((policy) => (
        <div key={policy.id}>
          <div
            className={`doc-nav-item row between${selectedDocId === policy.id ? " active" : ""}`}
            onClick={() => select(policy.id)}
          >
            <span className="row" style={{ gap: 6, minWidth: 0 }}>
              <IconFileText size={13} /> <span className="truncate">{policy.title}</span>
            </span>
            <button
              className="ghost doc-delete-btn"
              onClick={(e) => remove(policy, e)}
              disabled={deletingId === policy.id}
              title={`Delete ${policy.title}`}
            >
              <IconTrash size={13} />
            </button>
          </div>
          <div style={{ paddingLeft: 12 }}>
            {proceduresFor(policy.id).map((proc) => (
              <div
                key={proc.id}
                className={`doc-nav-item row between${selectedDocId === proc.id ? " active" : ""}`}
                onClick={() => select(proc.id)}
              >
                <span className="row" style={{ gap: 6, minWidth: 0 }}>
                  <span className="dot synced" /> <span className="truncate">{proc.title}</span>
                </span>
                <button
                  className="ghost doc-delete-btn"
                  onClick={(e) => remove(proc, e)}
                  disabled={deletingId === proc.id}
                  title={`Delete ${proc.title}`}
                >
                  <IconTrash size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}

      {showAdd && (
        <div style={{ margin: "8px 8px 0", padding: "10px 10px 12px", borderTop: "1px solid var(--glass-border-soft)" }}>
          <div className="row" style={{ gap: 4, marginBottom: 8 }}>
            <button
              className={addMode === "upload" ? "primary" : "ghost"}
              style={{ flex: 1, justifyContent: "center", fontSize: 11.5, padding: "4px 6px" }}
              onClick={() => setAddMode("upload")}
            >
              <IconUpload size={12} /> Upload file
            </button>
            <button
              className={addMode === "draft" ? "primary" : "ghost"}
              style={{ flex: 1, justifyContent: "center", fontSize: 11.5, padding: "4px 6px" }}
              onClick={() => setAddMode("draft")}
              title="Ask the AI to draft this document from a SuperDocs template"
            >
              <IconSparkle size={12} /> Draft with AI
            </button>
          </div>

          <select value={docType} onChange={(e) => setDocType(e.target.value as DocType)} style={{ marginBottom: 8, fontSize: 12.5 }}>
            <option value="policy">Policy</option>
            <option value="procedure">Procedure</option>
          </select>

          {docType === "procedure" && (
            <select value={parentPolicyId} onChange={(e) => setParentPolicyId(e.target.value)} style={{ marginBottom: 8, fontSize: 12.5 }}>
              <option value="">Choose a policy...</option>
              {policies.map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          )}

          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" style={{ marginBottom: 8, fontSize: 12.5 }} />

          {addMode === "upload" ? (
            <>
              <div
                className={`dropzone${dragging ? " dragging" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); }}
                style={{ padding: "16px 10px" }}
              >
                <div className="dropzone-icon" style={{ width: 30, height: 30 }}><IconUpload size={13} /></div>
                <div className="dropzone-title" style={{ fontSize: 12 }}>{file ? file.name : "Drop or click"}</div>
              </div>
              <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={(e) => setFile(e.target.files?.[0] || null)} />

              <button
                className="primary" style={{ marginTop: 10, width: "100%", justifyContent: "center", fontSize: 12.5 }}
                onClick={upload} disabled={uploading || !file || !title.trim() || (docType === "procedure" && !parentPolicyId)}
              >
                {uploading ? "Uploading..." : "Upload"}
              </button>
            </>
          ) : (
            <>
              <textarea
                value={draftPrompt}
                onChange={(e) => setDraftPrompt(e.target.value)}
                placeholder='e.g. "Draft a data breach notification policy for a mid-size clinic"'
                rows={4}
                style={{ marginBottom: 8, fontSize: 12.5, width: "100%", resize: "vertical" }}
              />
              <div className="faint" style={{ fontSize: 11, marginBottom: 8 }}>
                The AI drafts from one of this account&apos;s SuperDocs templates -- structure only, no content is
                invented for you to skip reviewing.
              </div>
              <button
                className="primary" style={{ width: "100%", justifyContent: "center", fontSize: 12.5 }}
                onClick={draft}
                disabled={drafting || !draftPrompt.trim() || !title.trim() || (docType === "procedure" && !parentPolicyId)}
              >
                {drafting ? "Drafting..." : "Draft with AI"}
              </button>
            </>
          )}
        </div>
      )}

      {findings.length > 0 && (
        <div className="sidebar-section">
          <div className="sidebar-section-label">
            <span className="row" style={{ gap: 5 }}><IconAlertTriangle size={12} /> Findings ({findings.length})</span>
          </div>
          <div className="col" style={{ gap: 6, padding: "0 12px" }}>
            {findings.map((f) => (
              <div key={f.id} style={{ fontSize: 11.5 }}>
                <span className="badge stale" style={{ fontSize: 10.5 }}>{f.finding_type.replace(/_/g, " ")}</span>
                <div className="muted" style={{ marginTop: 3, fontSize: 11.5 }}>{f.description}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const pathname = usePathname();
  const router = useRouter();
  const workspaceId = String(params.workspaceId);
  const [workspace, setWorkspace] = useState<WorkspaceOut | null>(null);
  const [deletingWorkspace, setDeletingWorkspace] = useState(false);

  useEffect(() => {
    api
      .getWorkspace(workspaceId)
      .then(setWorkspace)
      .catch(() => {});
  }, [workspaceId]);

  async function handleDeleteWorkspace() {
    if (!workspace) return;
    if (
      !window.confirm(
        `Delete "${workspace.pack_name}" (${workspace.organization_name})? This permanently removes every policy, procedure, reference, proposed change, finding, and report in this workspace. This cannot be undone.`
      )
    ) {
      return;
    }
    setDeletingWorkspace(true);
    try {
      await api.deleteWorkspace(workspaceId);
      router.push("/");
    } catch (e) {
      alert(String(e));
      setDeletingWorkspace(false);
    }
  }

  const docsHref = `/w/${workspaceId}`;
  const analyzeHref = `/w/${workspaceId}/analyze`;
  const onDocs = pathname === docsHref;
  const onAnalyze = pathname.startsWith(analyzeHref);

  return (
    <div className="app-shell">
      <aside className="app-sidebar glass">
        <div className="app-sidebar-heading">
          <div className="row between" style={{ alignItems: "flex-start" }}>
            <div>
              <div className="name">{workspace?.pack_name || "Workspace"}</div>
              <div className="org">{workspace?.organization_name || " "}</div>
            </div>
            <button
              className="icon-btn-remove"
              onClick={handleDeleteWorkspace}
              disabled={deletingWorkspace || !workspace}
              title="Delete compliance pack"
            >
              <IconTrash size={14} />
            </button>
          </div>
        </div>

        <div className="sidebar-nav-item" onClick={() => router.push("/")}>
          <IconPlus size={15} /> New Compliance
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-label">Workspace</div>
          <div className={`sidebar-nav-item${onDocs ? " active" : ""}`} onClick={() => router.push(docsHref)}>
            <IconClipboard size={15} /> Policies &amp; Procedures
          </div>
          <div className={`sidebar-nav-item${onAnalyze ? " active" : ""}`} onClick={() => router.push(analyzeHref)}>
            <IconWorkflow size={15} /> Analyze
          </div>
        </div>

        <Suspense fallback={null}>
          <DocumentTree workspaceId={workspaceId} />
        </Suspense>
      </aside>

      <main className="app-main">
        <div className="content-topbar glass">
          <NavTabs workspaceId={workspaceId} />
        </div>
        {children}
      </main>
    </div>
  );
}
