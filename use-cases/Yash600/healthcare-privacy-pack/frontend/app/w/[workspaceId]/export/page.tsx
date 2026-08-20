"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, DocumentOut } from "@/lib/api";
import { IconDownload, IconFileText } from "../../../icons";

const FORMATS = ["docx", "pdf", "html", "markdown", "txt"];

export default function ExportPage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId);

  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [fmt, setFmt] = useState("docx");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const docs = await api.listWorkspaceDocuments(workspaceId);
      setDocuments(docs);
    } catch (e) {
      setError(String(e));
    }
  }, [workspaceId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div style={{ maxWidth: 760 }}>
      <div className="eyebrow"><IconDownload size={13} /> Export</div>
      <h1>Export</h1>
      <p className="lede">
        Export bundles every document's current active version -- only what's been approved.
      </p>

      {error && <div className="error-banner">{error}</div>}

      <div className="card glass-strong">
        <div className="row between" style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Format</h3>
          <select value={fmt} onChange={(e) => setFmt(e.target.value)} style={{ width: 140 }}>
            {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <a className="btn dark" href={api.exportWorkspaceUrl(workspaceId, fmt)} style={{ marginBottom: 14, display: "inline-flex" }}>
          <IconDownload size={14} /> Export whole workspace (.zip)
        </a>
        <div className="col" style={{ gap: 6 }}>
          {documents.map((d) => (
            <div key={d.id} className="row between" style={{ fontSize: 13 }}>
              <span className="row"><IconFileText size={14} /> {d.title}</span>
              <a className="btn" href={api.exportDocumentUrl(d.id, fmt)}>Download</a>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
