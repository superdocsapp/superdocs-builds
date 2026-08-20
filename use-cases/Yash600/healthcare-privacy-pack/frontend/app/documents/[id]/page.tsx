"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, DocumentOut, ReferenceOut, REFERENCE_STATUS_COLORS, REFERENCE_STATUS_LABELS } from "@/lib/api";
import { IconFileText, IconArrowRight, IconLayers } from "../../icons";

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const [doc, setDoc] = useState<DocumentOut | null>(null);
  const [references, setReferences] = useState<ReferenceOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.id) return;
    api
      .getDocument(params.id, true)
      .then((d) => {
        setDoc(d);
        // References are a procedure-side concept only -- a policy is the
        // thing being implemented, not itself an implementer of anything,
        // so there's nothing meaningful to show on a policy's own page.
        // Skip the fetch entirely for policies rather than fetch-then-hide.
        if (d.doc_type === "policy") return [];
        return api.listReferences(d.workspace_id);
      })
      .then(setReferences)
      .catch((e) => setError(String(e)));
  }, [params?.id]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!doc) return <div className="empty">Loading...</div>;

  const isPolicy = doc.doc_type === "policy";
  const relevantRefs = references.filter((r) => r.procedure_document_id === doc.id);

  return (
    <div>
      <Link href={`/w/${doc.workspace_id}`} className="row muted" style={{ marginBottom: 14, fontSize: 13 }}>
        <IconLayers size={14} /> Back to workspace
      </Link>

      <div className="eyebrow"><IconFileText size={13} /> {isPolicy ? "Policy" : "Procedure"}</div>
      <h1>{doc.title}</h1>

      <div className="section-head">
        <h2>Document</h2>
      </div>
      {doc.html ? (
        <div className="card"><div className="doc-native-preview" dangerouslySetInnerHTML={{ __html: doc.html }} /></div>
      ) : (
        <div className="muted">No content available for this document yet.</div>
      )}

      {!isPolicy && (
        <>
          <div className="section-head">
            <h2>Implements ({relevantRefs.length})</h2>
          </div>
          {relevantRefs.length === 0 && <div className="empty">No references yet.</div>}
          {relevantRefs.map((r) => (
            <div key={r.id} className="card row between">
              <div>
                <Link href={`/documents/${r.policy_document_id}`} className="row" style={{ fontWeight: 600, fontSize: 13.5 }}>
                  {r.policy_section?.title || "..."} <IconArrowRight size={13} />
                </Link>
                {r.evidence && <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{r.evidence}</div>}
              </div>
              <span className="badge" style={{ background: `${REFERENCE_STATUS_COLORS[r.status]}22`, color: REFERENCE_STATUS_COLORS[r.status] }}>
                {REFERENCE_STATUS_LABELS[r.status]}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
