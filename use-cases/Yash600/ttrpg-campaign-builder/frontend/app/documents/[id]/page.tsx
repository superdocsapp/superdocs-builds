"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  DocumentOut,
  DocumentVersionOut,
  ChatMessageOut,
  DocumentLinkOut,
  DocType,
  DOC_TYPE_LABELS,
  DOC_TYPE_BADGE_CLASS,
} from "@/lib/api";
import {
  IconSparkle,
  IconCheckCircle,
  IconX,
  IconDownload,
  IconClock,
  IconPencil,
  IconSave,
  IconTrash,
  IconAlertTriangle,
  IconLayers,
  IconImage,
  IconUpload,
} from "../../icons";

const EXPORT_FORMATS = ["docx", "pdf", "html", "markdown", "txt"];
const DOC_TYPES: DocType[] = ["campaign_bible", "character", "npc", "location", "session_log", "other"];

// Turns an internal ID-style [[code]] like "LOC-VEYR" or "SC-BIBLE:6-MAGIC"
// into a human-friendly title for the "Create linked document" quick
// action -- strips a short entity-type prefix and any :section suffix,
// then title-cases the rest. A human-written [[Title]] is returned as-is.
function titleFromRefCode(code: string): string {
  const trimmed = code.trim();
  if (!/^[A-Z][A-Z0-9]*(?:[-:][A-Z0-9]+)+$/.test(trimmed)) return trimmed;
  const withoutSection = trimmed.split(":")[0];
  const withoutPrefix = withoutSection.replace(/^[A-Za-z]{2,5}-/, "");
  const words = withoutPrefix.replace(/[-_]+/g, " ").trim().toLowerCase();
  return words.replace(/\b\w/g, (c) => c.toUpperCase()) || trimmed;
}

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const documentId = params.id as string;

  const [doc, setDoc] = useState<DocumentOut | null>(null);
  const [versions, setVersions] = useState<DocumentVersionOut[]>([]);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [links, setLinks] = useState<DocumentLinkOut[]>([]);
  const [campaignDocs, setCampaignDocs] = useState<DocumentOut[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState("docx");
  const [relinking, setRelinking] = useState(false);
  const [relinkNote, setRelinkNote] = useState<string | null>(null);
  const [creatingRefDoc, setCreatingRefDoc] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const brokenRefsRef = useRef<HTMLDivElement | null>(null);

  // illustration (Character/NPC/Location documents only)
  const [showIllustrationForm, setShowIllustrationForm] = useState(false);
  const [illustrationMode, setIllustrationMode] = useState<"generate" | "upload">("generate");
  const [illustrationPrompt, setIllustrationPrompt] = useState("");
  const [illustrationFile, setIllustrationFile] = useState<File | null>(null);
  const [illustrationBusy, setIllustrationBusy] = useState(false);

  // manual edit
  const [editing, setEditing] = useState(false);
  const [draftHtml, setDraftHtml] = useState("");
  const [saving, setSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  // rename / change-type / delete
  const [showMeta, setShowMeta] = useState(false);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameType, setRenameType] = useState<DocType>("other");
  const [patching, setPatching] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    if (!documentId) return;
    api
      .getDocument(documentId)
      .then((d) => {
        setDoc(d);
        setRenameTitle(d.title);
        setRenameType(d.doc_type);
        if (d.active_version) setLastSavedAt(d.active_version.created_at);
        api.listCampaignLinks(d.campaign_id).then(setLinks).catch(() => {});
        api.listCampaignDocuments(d.campaign_id).then(setCampaignDocs).catch(() => {});
      })
      .catch((e) => setError(String(e)));
    api.listDocumentVersions(documentId).then(setVersions).catch(() => {});
    api.listChatMessages(documentId).then(setMessages).catch(() => {});
  }, [documentId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const proposedVersion = versions.find((v) => v.status === "proposed") || null;
  const activeVersion = doc?.active_version;

  // Jump to + briefly highlight the target section when a cross-reference
  // link brought us here with a #anchor (e.g. /documents/abc#key-locations).
  useEffect(() => {
    if (!activeVersion || !contentRef.current) return;
    const hash = window.location.hash?.slice(1);
    if (!hash) return;
    const target = contentRef.current.querySelector(`#${CSS.escape(hash)}`) as HTMLElement | null;
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    target.classList.add("ref-anchor-highlight");
    const timer = setTimeout(() => target.classList.remove("ref-anchor-highlight"), 2200);
    return () => clearTimeout(timer);
  }, [activeVersion, documentId]);

  async function submitIllustration(e: React.FormEvent) {
    e.preventDefault();
    if (!doc?.entity_type || !doc?.entity_id) return;
    setIllustrationBusy(true);
    setError(null);
    try {
      if (illustrationMode === "generate") {
        if (!illustrationPrompt.trim()) return;
        await api.generateIllustration({ entity_type: doc.entity_type, entity_id: doc.entity_id, prompt: illustrationPrompt.trim(), embed: true });
      } else {
        if (!illustrationFile) return;
        await api.uploadIllustration({ entity_type: doc.entity_type, entity_id: doc.entity_id, prompt: illustrationPrompt.trim(), embed: true, file: illustrationFile });
      }
      setIllustrationPrompt("");
      setIllustrationFile(null);
      setShowIllustrationForm(false);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setIllustrationBusy(false);
    }
  }

  async function createLinkedDocument(refTitle: string) {
    if (!doc) return;
    setCreatingRefDoc(refTitle);
    setError(null);
    try {
      const created = await api.createDocument(doc.campaign_id, {
        doc_type: "other",
        title: titleFromRefCode(refTitle),
        content_html: "",
      });
      router.push(`/documents/${created.id}`);
    } catch (e) {
      setError(String(e));
      setCreatingRefDoc(null);
    }
  }

  function startEditing() {
    setDraftHtml(activeVersion?.content_html || "");
    setEditing(true);
  }

  async function saveDraft() {
    setSaving(true);
    setError(null);
    try {
      const result = await api.saveDocument(documentId, draftHtml, "Manual edit");
      setEditing(false);
      setLastSavedAt(new Date().toISOString());
      if (result.broken_references.length > 0) {
        setError(`Saved, but ${result.broken_references.length} [[reference]] link(s) don't match any document title: ${result.broken_references.join(", ")}`);
      }
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function saveMeta() {
    if (!doc) return;
    setPatching(true);
    setError(null);
    try {
      await api.patchDocument(documentId, { title: renameTitle.trim() || doc.title, doc_type: renameType });
      setShowMeta(false);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setPatching(false);
    }
  }

  async function relinkReferences() {
    setRelinking(true);
    setError(null);
    setRelinkNote(null);
    try {
      const result = await api.relinkDocumentReferences(documentId);
      if (!result.changed) {
        setRelinkNote("Already up to date -- nothing new to link.");
      } else {
        setRelinkNote(
          `Re-linked: ${result.resolved_reference_count} reference(s) now clickable` +
            (result.broken_references.length ? `, ${result.broken_references.length} still unresolved.` : ".")
        );
      }
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setRelinking(false);
    }
  }

  async function deleteDoc() {
    if (!doc) return;
    if (!window.confirm(`Delete "${doc.title}"? This removes its versions, links, and chat history. This cannot be undone.`)) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteDocument(documentId);
      router.push(`/campaigns/${doc.campaign_id}`);
    } catch (e) {
      setError(String(e));
      setDeleting(false);
    }
  }

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setSending(true);
    setError(null);
    try {
      await api.chatEditDocument(documentId, message.trim());
      setMessage("");
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  async function approve(versionId: string) {
    setApproving(true);
    setError(null);
    try {
      await api.approveVersion(documentId, versionId);
      setLastSavedAt(new Date().toISOString());
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setApproving(false);
    }
  }

  async function reject(versionId: string) {
    setApproving(true);
    setError(null);
    try {
      await api.rejectVersion(documentId, versionId);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setApproving(false);
    }
  }

  if (!doc) return <p>Loading document…</p>;

  const docById = new Map(campaignDocs.map((d) => [d.id, d]));
  const outboundLinks = links.filter((l) => l.source_document_id === documentId);
  const inboundLinks = links.filter((l) => l.target_document_id === documentId && l.source_document_id !== documentId);
  const brokenRefs = doc.broken_references || [];

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button
          className="btn ghost"
          onClick={() => router.back()}
          style={{ padding: "2px 8px", fontSize: 13 }}
          title="Return to the previous document/position"
        >
          ← Back
        </button>
        <a href={`/campaigns/${doc.campaign_id}`} style={{ color: "var(--text-muted)", fontSize: 13 }}>
          back to campaign
        </a>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
        <span className={`badge ${DOC_TYPE_BADGE_CLASS[doc.doc_type]}`}>{DOC_TYPE_LABELS[doc.doc_type]}</span>
        <h1 style={{ margin: 0 }}>{doc.title}</h1>
        <button className="btn ghost" style={{ marginLeft: "auto" }} onClick={() => setShowMeta((v) => !v)}>
          <IconPencil size={14} /> Rename / type
        </button>
        <button className="btn ghost" onClick={deleteDoc} disabled={deleting} style={{ color: "var(--danger)" }}>
          <IconTrash size={14} /> {deleting ? "Deleting…" : "Delete"}
        </button>
      </div>
      {doc.description && <p style={{ color: "var(--text-muted)" }}>{doc.description}</p>}

      {showMeta && (
        <div className="card" style={{ display: "grid", gap: 8, margin: "10px 0" }}>
          <label>
            Title
            <input value={renameTitle} onChange={(e) => setRenameTitle(e.target.value)} />
          </label>
          <label>
            Type
            <select value={renameType} onChange={(e) => setRenameType(e.target.value as DocType)}>
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {DOC_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary" onClick={saveMeta} disabled={patching}>
              {patching ? "Saving…" : "Save changes"}
            </button>
            <button className="btn ghost" onClick={() => setShowMeta(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="card" style={{ borderColor: "var(--danger)", margin: "12px 0" }}>
          {error}
        </div>
      )}

      {relinkNote && (
        <div className="card" style={{ margin: "12px 0", fontSize: 13 }}>
          {relinkNote}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, margin: "12px 0 20px", flexWrap: "wrap", alignItems: "center" }}>
        <select value={exportFormat} onChange={(e) => setExportFormat(e.target.value)}>
          {EXPORT_FORMATS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <a className="btn ghost" href={api.exportDocumentUrl(documentId, exportFormat)}>
          <IconDownload size={14} /> Export
        </a>
        <button className="btn ghost" onClick={relinkReferences} disabled={relinking} title="Re-check and re-link [[references]] against the current documents in this campaign">
          {relinking ? "Re-linking…" : "Re-link references"}
        </button>
        {lastSavedAt && (
          <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: "auto" }}>
            Last saved {timeAgo(lastSavedAt)}
          </span>
        )}
      </div>

      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Current {activeVersion ? `— v${activeVersion.version_number}` : ""}</h3>
          {!editing && !proposedVersion && (
            <button className="btn ghost" onClick={startEditing} style={{ marginLeft: "auto" }}>
              <IconPencil size={14} /> Edit
            </button>
          )}
        </div>

        {editing ? (
          <div>
            <textarea
              value={draftHtml}
              onChange={(e) => setDraftHtml(e.target.value)}
              rows={16}
              style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
              placeholder="<h1>...</h1><p>Write HTML content. Use [[Another Document Title]] to cross-link it.</p>"
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button className="btn approve" onClick={saveDraft} disabled={saving}>
                <IconSave size={14} /> {saving ? "Saving…" : "Save changes"}
              </button>
              <button className="btn ghost" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </button>
            </div>
            <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 6 }}>
              Tip: write [[Document Title]] anywhere to auto-link to another document in this campaign.
            </p>
          </div>
        ) : (
          <div
            ref={contentRef}
            className="card chunk-card"
            dangerouslySetInnerHTML={{ __html: activeVersion?.content_html || "<p><em>No content yet.</em></p>" }}
          />
        )}
      </div>

      {doc.entity_type && doc.entity_id && (
        <div style={{ margin: "20px 0" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>
              <IconImage size={16} /> Illustration
            </h3>
            {!showIllustrationForm && (
              <button className="btn ghost" onClick={() => setShowIllustrationForm(true)} style={{ marginLeft: "auto" }}>
                <IconImage size={14} /> Add illustration
              </button>
            )}
          </div>

          {doc.entity_image_url && !showIllustrationForm && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={doc.entity_image_url}
              alt={doc.title}
              style={{ maxWidth: "100%", maxHeight: 280, borderRadius: "var(--radius-sm)", display: "block" }}
            />
          )}
          {!doc.entity_image_url && !showIllustrationForm && (
            <p style={{ color: "var(--text-muted)", fontSize: 13 }}>No illustration yet.</p>
          )}

          {showIllustrationForm && (
            <form className="card" onSubmit={submitIllustration} style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className={`btn ${illustrationMode === "generate" ? "primary" : "ghost"}`}
                  onClick={() => setIllustrationMode("generate")}
                >
                  <IconSparkle size={14} /> Generate with AI
                </button>
                <button
                  type="button"
                  className={`btn ${illustrationMode === "upload" ? "primary" : "ghost"}`}
                  onClick={() => setIllustrationMode("upload")}
                >
                  <IconUpload size={14} /> Upload image
                </button>
              </div>

              {illustrationMode === "generate" ? (
                <label>
                  Prompt
                  <input
                    value={illustrationPrompt}
                    onChange={(e) => setIllustrationPrompt(e.target.value)}
                    placeholder="a ruined keep on a storm-lashed cliff, dark fantasy illustration"
                    required
                  />
                </label>
              ) : (
                <>
                  <label>
                    Image file
                    <input type="file" accept="image/*" onChange={(e) => setIllustrationFile(e.target.files?.[0] || null)} required />
                  </label>
                  <label>
                    Caption (optional)
                    <input value={illustrationPrompt} onChange={(e) => setIllustrationPrompt(e.target.value)} />
                  </label>
                </>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn approve" type="submit" disabled={illustrationBusy}>
                  {illustrationBusy ? "Saving…" : "Insert into document"}
                </button>
                <button className="btn ghost" type="button" onClick={() => setShowIllustrationForm(false)} disabled={illustrationBusy}>
                  Cancel
                </button>
              </div>
              <p style={{ color: "var(--text-muted)", fontSize: 12, margin: 0 }}>
                Saved to this campaign's Assets and inserted directly into the document.
              </p>
            </form>
          )}
        </div>
      )}

      <h3 style={{ margin: "28px 0 8px" }}>
        <IconLayers size={16} /> Linked documents
      </h3>
      {outboundLinks.length === 0 && inboundLinks.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>No links yet. Use [[Title]] in the content, or add one from the campaign's Links tab.</p>
      ) : (
        <div style={{ display: "grid", gap: 6, marginBottom: 20 }}>
          {outboundLinks.map((l) => {
            const target = docById.get(l.target_document_id);
            return (
              <a key={l.id} href={`/documents/${l.target_document_id}`} className="card hoverable" style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 12px", textDecoration: "none", color: "inherit" }}>
                <span className={`badge ${l.status === "stale" ? "pending_review" : "synced"}`}>{l.relationship_type}</span>
                <span>→ {target?.title || l.target_document_id}</span>
                {l.status === "stale" && <IconAlertTriangle size={14} />}
              </a>
            );
          })}
          {inboundLinks.map((l) => {
            const source = docById.get(l.source_document_id);
            return (
              <a key={l.id} href={`/documents/${l.source_document_id}`} className="card hoverable" style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 12px", textDecoration: "none", color: "inherit" }}>
                <span className="badge entity">referenced by</span>
                <span>← {source?.title || l.source_document_id}</span>
              </a>
            );
          })}
        </div>
      )}

      <h3 style={{ margin: "20px 0 8px" }}>Ask AI to edit this document</h3>
      <form className="card" onSubmit={sendMessage} style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="e.g. Add a new faction called the Ashen Concord…"
          style={{ flex: 1 }}
          disabled={sending || !!proposedVersion}
        />
        <button className="btn primary" type="submit" disabled={sending || !!proposedVersion}>
          {sending ? <><IconSparkle size={14} /> Thinking…</> : "Send"}
        </button>
      </form>
      {proposedVersion && (
        <div className="card" style={{ margin: "0 0 20px", borderColor: "var(--accent)" }}>
          <h3 style={{ marginTop: 0, marginBottom: 8 }}>Proposed — v{proposedVersion.version_number} (awaiting approval)</h3>
          <div className="card chunk-card is-entity" dangerouslySetInnerHTML={{ __html: proposedVersion.content_html || "" }} />
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0" }}>{proposedVersion.change_summary}</p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn approve" onClick={() => approve(proposedVersion.id)} disabled={approving}>
              <IconCheckCircle size={14} /> Approve
            </button>
            <button className="btn reject" onClick={() => reject(proposedVersion.id)} disabled={approving}>
              <IconX size={14} /> Reject
            </button>
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "10px 0 0" }}>
            Approve or reject this before requesting another edit.
          </p>
        </div>
      )}

      {messages.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ marginBottom: 8 }}>Conversation</h3>
          <div style={{ display: "grid", gap: 8 }}>
            {messages.map((m) => (
              <div key={m.id} className="card" style={{ background: m.role === "user" ? "var(--panel-raised)" : undefined }}>
                <strong style={{ textTransform: "capitalize" }}>{m.role}</strong>
                <p style={{ margin: "4px 0 0" }}>{m.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <h3 style={{ margin: "20px 0 8px" }}>
        <IconClock size={16} /> Version history
      </h3>
      <div style={{ display: "grid", gap: 6 }}>
        {versions.map((v) => (
          <div key={v.id} className="card" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px" }}>
            <span className={`badge ${v.status === "active" ? "synced" : v.status === "proposed" ? "pending_review" : "session_log"}`}>
              v{v.version_number} · {v.status}
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: 13 }}>{v.change_summary || "—"}</span>
            <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 12 }}>{v.created_by}</span>
          </div>
        ))}
      </div>

      {brokenRefs.length > 0 && (
        <div ref={brokenRefsRef} className="card" style={{ borderColor: "var(--danger)", margin: "28px 0 12px", display: "flex", gap: 8, alignItems: "flex-start" }}>
          <IconAlertTriangle size={16} />
          <div style={{ minWidth: 0 }}>
            <strong>
              {brokenRefs.length} unresolved [[reference]]{brokenRefs.length === 1 ? "" : "s"}
            </strong>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
              This document uses double-bracket text like <code className="mono">[[{brokenRefs[0]}]]</code> that doesn't match the title of
              any other document in this campaign, so it isn't linked. If it's meant as a cross-link, create or rename a document to match; if
              it's old placeholder text (e.g. from an import) rather than an intended link, it's safe to ignore or edit out.
            </p>
            <div style={{ display: "grid", gap: 4, marginTop: 10 }}>
              {brokenRefs.map((ref) => {
                const bible = campaignDocs.find((d) => d.doc_type === "campaign_bible");
                return (
                  <div key={ref} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, flexWrap: "wrap" }}>
                    <code className="mono" style={{ color: "var(--text-muted)", wordBreak: "break-word" }}>
                      [[{ref}]]
                    </code>
                    <div style={{ marginLeft: "auto", display: "flex", gap: 6, flexShrink: 0 }}>
                      {bible && (
                        <a className="btn ghost" href={`/documents/${bible.id}`} style={{ padding: "2px 8px", fontSize: 12 }}>
                          Open in Campaign Bible
                        </a>
                      )}
                      <button
                        className="btn ghost"
                        onClick={() => createLinkedDocument(ref)}
                        disabled={creatingRefDoc === ref}
                        style={{ padding: "2px 8px", fontSize: 12 }}
                      >
                        {creatingRefDoc === ref ? "Creating…" : `+ Create "${titleFromRefCode(ref)}"`}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            <button className="btn ghost" onClick={relinkReferences} disabled={relinking} style={{ marginTop: 10 }}>
              {relinking ? "Re-linking…" : "Re-link references"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
