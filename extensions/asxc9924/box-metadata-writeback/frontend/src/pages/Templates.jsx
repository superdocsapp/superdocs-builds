import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Loading, EmptyState } from "../components/bits.jsx";

export default function Templates() {
  const [templates, setTemplates] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.templates().then((r) => setTemplates(r.templates)).catch((e) => setErr(e.message));
  }, []);

  if (err) return <EmptyState title="Can't reach the workflow API" body={err} />;
  if (!templates) return <Loading />;

  return (
    <div>
      <div className="page-header">
        <div>
          <p className="eyebrow">Configuration, not code</p>
          <h1 className="page-title">Retention templates</h1>
          <p className="page-sub">
            The doc-class → retention-category mapping the pipeline applies. A new document class or
            duration is a data change here, not a rewrite of the pipeline.
          </p>
        </div>
      </div>
      <div className="template-grid">
        {templates.map((t) => (
          <div className="template-card" key={t.doc_class}>
            <div className="template-class">{t.doc_class}</div>
            <div className="template-cat">{t.retention_category}</div>
            <div className="template-years">
              {t.duration_years ? `${t.duration_years} year retention` : "No scheduled disposition"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
