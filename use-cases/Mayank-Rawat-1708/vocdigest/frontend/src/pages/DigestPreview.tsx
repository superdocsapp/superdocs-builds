/**
 * @file src/pages/DigestPreview.tsx
 * @description Final digest view: themes in volume order with their evidence, plus the
 *   export download. Shows what was rejected as well as what shipped, so the reader can
 *   see the digest is a filtered view rather than everything the analysis produced.
 * @flow load themes + run detail -> render theme cards -> link to the export endpoint
 * @dependencies lib/api, ThemeCard
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, Download, ExternalLink, Loader2 } from "lucide-react";
import { api, type RunDetail, type Theme } from "../lib/api";
import { ThemeCard } from "../components/ThemeCard";
import { RunStatusBadge } from "../components/RunStatusBadge";

export default function DigestPreview() {
  const { runId } = useParams<{ runId: string }>();
  const [themes, setThemes] = useState<Theme[] | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    void Promise.all([api.getThemes(runId), api.getRun(runId)])
      .then(([t, d]) => { setThemes(t); setDetail(d); })
      .catch((e) => setError((e as Error).message));
  }, [runId]);

  if (error) return (
    <div className="card p-6 flex items-center gap-3 text-red-600"><AlertCircle className="w-5 h-5" /> {error}</div>
  );
  if (!themes || !detail) return (
    <div className="flex items-center gap-2 text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading digest…</div>
  );

  const s = detail.summary;
  return (
    <div className="space-y-6">
      <header className="flex items-start gap-4">
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">{detail.quarter_label} Voice-of-Customer Digest</h1>
          <p className="mt-1 text-sm text-slate-500">
            {s.conversations.relevant} conversations · {themes.length} themes
            {s.comparison_available ? " · compared to prior quarter" : " · no prior-quarter comparison"}
          </p>
        </div>
        <RunStatusBadge status={detail.status} />
      </header>

      <div className="flex flex-wrap gap-3">
        {detail.export_available ? (
          <a href={api.exportUrl(detail.id)} className="btn-primary" download>
            <Download className="w-4 h-4" /> Download DOCX
          </a>
        ) : (
          <span className="text-sm text-slate-500">Export not available yet.</span>
        )}
        <Link to={`/runs/${detail.id}`} className="btn-ghost">
          <ExternalLink className="w-4 h-4" /> Run detail
        </Link>
      </div>

      {!s.comparison_available && (
        <p className="card p-4 text-sm text-slate-600 dark:text-slate-400">
          No prior-quarter digest was supplied, so this report contains no growth figures.
          Themes are not labelled as new or growing.
        </p>
      )}

      <section className="space-y-4">
        <h2 className="font-semibold">Themes by volume</h2>
        {themes.map((theme, i) => <ThemeCard key={theme.id} theme={theme} rank={i + 1} />)}
      </section>
    </div>
  );
}
