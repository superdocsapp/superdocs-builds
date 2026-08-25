/**
 * @file src/pages/Upload.tsx
 * @description Start a run by dragging in a conversations file and, optionally, last
 *   quarter's digest. The prior digest is explicitly marked optional and the UI states
 *   what is lost without it, so a user is never surprised by a missing comparison.
 * @flow drop or pick files -> POST multipart -> navigate to the new run's detail page
 * @dependencies lib/api, react-router-dom
 */
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud, FileText, X, Loader2, AlertCircle } from "lucide-react";
import clsx from "clsx";
import { api } from "../lib/api";

function DropZone({
  label, hint, accept, file, onFile,
}: {
  label: string; hint: string; accept: string; file: File | null;
  onFile: (f: File | null) => void;
}) {
  const [over, setOver] = useState(false);
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  }, [onFile]);

  return (
    <div>
      <label className="text-sm font-medium">{label}</label>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={clsx("mt-2 card border-2 border-dashed p-6 text-center transition",
          over ? "border-accent bg-blue-50/50 dark:bg-blue-900/10" : "border-slate-300 dark:border-slate-700")}
      >
        {file ? (
          <div className="flex items-center justify-center gap-3">
            <FileText className="w-5 h-5 text-accent" />
            <span className="text-sm font-medium truncate max-w-xs">{file.name}</span>
            <span className="text-xs text-slate-500">{(file.size / 1024).toFixed(0)} KB</span>
            <button onClick={() => onFile(null)} className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded">
              <X className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <>
            <UploadCloud className="w-8 h-8 mx-auto text-slate-400" />
            <p className="mt-2 text-sm">Drop a file here, or{" "}
              <label className="text-accent cursor-pointer hover:underline">
                browse
                <input type="file" accept={accept} className="hidden"
                  onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
              </label>
            </p>
            <p className="mt-1 text-xs text-slate-500">{hint}</p>
          </>
        )}
      </div>
    </div>
  );
}

export default function Upload() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<File | null>(null);
  const [lastDigest, setLastDigest] = useState<File | null>(null);
  const [quarter, setQuarter] = useState("Q3 2026");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!conversations) return;
    setSubmitting(true); setError(null);
    try {
      const { run_id } = await api.startRunFromUpload(conversations, lastDigest, quarter);
      navigate(`/runs/${run_id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">New digest run</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a quarter of support conversations. The run pauses for your review before anything is published.
        </p>
      </div>

      <DropZone
        label="Support conversations"
        hint="CSV with a text column, JSON array, or plain TXT (one per line)"
        accept=".csv,.json,.txt"
        file={conversations}
        onFile={setConversations}
      />

      <DropZone
        label="Last quarter's digest (optional)"
        hint="DOCX, TXT, or Markdown — used for quarter-over-quarter comparison"
        accept=".docx,.txt,.md,.html"
        file={lastDigest}
        onFile={setLastDigest}
      />

      {!lastDigest && (
        <p className="text-xs rounded-lg bg-slate-100 dark:bg-slate-800/60 p-3 text-slate-600 dark:text-slate-400">
          Without a prior digest the report will state that no comparison was available.
          It will not estimate growth rates.
        </p>
      )}

      <div>
        <label className="text-sm font-medium">Quarter label</label>
        <input
          value={quarter}
          onChange={(e) => setQuarter(e.target.value)}
          className="mt-2 w-full card px-3 py-2 text-sm bg-transparent"
        />
      </div>

      {error && (
        <div className="card p-4 flex items-start gap-3 text-red-600 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> {error}
        </div>
      )}

      <button onClick={submit} disabled={!conversations || submitting} className="btn-primary w-full justify-center">
        {submitting ? <><Loader2 className="w-4 h-4 animate-spin" /> Starting…</> : "Start run"}
      </button>
    </div>
  );
}
