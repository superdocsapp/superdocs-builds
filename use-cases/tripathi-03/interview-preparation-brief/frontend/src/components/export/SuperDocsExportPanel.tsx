import { useCallback, useEffect, useState } from "react";
import { Check, Download, FileText, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  approveSuperDocsChanges,
  exportSuperDocsSession,
  getSuperDocsHealth,
  getSuperDocsJob,
  startSuperDocsPolish,
  type SuperDocsPendingChange,
} from "@/services/api";

type Props = { briefId: string };

function changeLabel(change: SuperDocsPendingChange, index: number): string {
  return (
    (typeof change.ai_explanation === "string" && change.ai_explanation) ||
    (typeof change.operation === "string" && change.operation) ||
    `Change ${index + 1}`
  );
}

function changeId(change: SuperDocsPendingChange, index: number): string {
  if (typeof change.change_id === "string" && change.change_id) return change.change_id;
  return `change-${index}`;
}

export function SuperDocsExportPanel({ briefId }: Props) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState<SuperDocsPendingChange[]>([]);
  const [aiResponse, setAiResponse] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    void getSuperDocsHealth()
      .then((h) => setConfigured(h.configured))
      .catch(() => setConfigured(false));
  }, []);

  const refreshJob = useCallback(async (id: string) => {
    const job = await getSuperDocsJob(id);
    setStatus(job.status);
    setPending(job.pending_changes || []);
    setAiResponse(job.ai_response || null);
    return job;
  }, []);

  useEffect(() => {
    if (!jobId) return;
    if (status === "completed" || status === "failed") return;

    const timer = window.setInterval(() => {
      void refreshJob(jobId).catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to poll SuperDocs job");
      });
    }, 2500);

    return () => window.clearInterval(timer);
  }, [jobId, status, refreshJob]);

  async function onStart() {
    setBusy(true);
    setError(null);
    setInfo(null);
    setPending([]);
    setAiResponse(null);
    try {
      const started = await startSuperDocsPolish(briefId, {
        approval_mode: "ask_every_time",
      });
      setSessionId(started.session_id);
      setJobId(started.job_id);
      setStatus(started.status);
      setInfo(started.message);
      await refreshJob(started.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start SuperDocs polish");
    } finally {
      setBusy(false);
    }
  }

  async function onApproveAll(approved: boolean) {
    if (!sessionId || !jobId) return;
    setBusy(true);
    setError(null);
    try {
      const decisions =
        pending.length > 0
          ? pending.map((change, index) => ({
              change_id: changeId(change, index),
              approved,
            }))
          : undefined;
      const result = await approveSuperDocsChanges(sessionId, {
        job_id: jobId,
        approved,
        changes: decisions,
      });
      setInfo(result.message);
      await refreshJob(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  async function onExport(format: "docx" | "pdf") {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await exportSuperDocsSession(sessionId, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setInfo(`Downloaded ${filename} via SuperDocs export`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "SuperDocs export failed");
    } finally {
      setBusy(false);
    }
  }

  if (configured === false) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">SuperDocs polish</CardTitle>
          <CardDescription>
            SuperDocs is not configured. Set SUPERDOCS_API_KEY and SUPERDOCS_ENABLED=true in
            backend .env, then restart the API.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const awaiting = status === "awaiting_approval";
  const completed = status === "completed";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="h-4 w-4" /> SuperDocs polish &amp; export
        </CardTitle>
        <CardDescription>
          Upload → edit → approve → export on SuperDocs (Groq still powers question generation).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" disabled={busy || configured !== true} onClick={onStart}>
            {busy && !sessionId ? "Starting…" : "Polish with SuperDocs"}
          </Button>
          {awaiting && (
            <>
              <Button
                type="button"
                size="sm"
                variant="default"
                disabled={busy}
                onClick={() => onApproveAll(true)}
              >
                <Check className="h-3.5 w-3.5" /> Approve all
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onApproveAll(false)}
              >
                <X className="h-3.5 w-3.5" /> Deny all
              </Button>
            </>
          )}
          {(completed || sessionId) && (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy || !sessionId}
                onClick={() => onExport("docx")}
              >
                <Download className="h-3.5 w-3.5" /> SuperDocs DOCX
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy || !sessionId}
                onClick={() => onExport("pdf")}
              >
                <Download className="h-3.5 w-3.5" /> SuperDocs PDF
              </Button>
            </>
          )}
        </div>

        {status && (
          <p className="text-xs text-muted-foreground">
            Status: <span className="font-medium text-foreground">{status}</span>
            {sessionId ? ` · session ${sessionId}` : ""}
          </p>
        )}

        {aiResponse && (
          <p className="rounded-md bg-muted/50 p-3 text-sm text-foreground/90">{aiResponse}</p>
        )}

        {awaiting && pending.length > 0 && (
          <ul className="space-y-2 text-sm">
            {pending.map((change, index) => (
              <li key={changeId(change, index)} className="rounded-md border border-border p-3">
                <p className="font-medium">{changeLabel(change, index)}</p>
                {change.chunk_id ? (
                  <p className="mt-1 text-xs text-muted-foreground">chunk: {String(change.chunk_id)}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {info && <p className="text-xs text-muted-foreground">{info}</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
