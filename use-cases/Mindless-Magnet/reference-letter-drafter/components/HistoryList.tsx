"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ExportButton } from "@/components/ExportButton";
import { listHistory, removeHistory, type HistoryEntry } from "@/lib/history";
import { filenameFor } from "@/lib/filename";
import type { Intake } from "@/lib/types";

/**
 * Past letters, from the local history list (see lib/history.ts). This app
 * stores no letters server-side, so "view" here means asking SuperDocs for
 * the current state of that session's document, not reading a saved copy.
 */

interface JobPreview {
  status: string;
  documentHtml: string;
}

function stubIntake(entry: HistoryEntry): Intake {
  // Only what history actually stored. Evidence, reservations and tone were
  // never persisted (see lib/history.ts), so a resumed calibration audit will
  // run with less to check against than the original session had.
  return {
    writerName: entry.writerName,
    writerEmail: "",
    writerRole: "",
    subjectName: entry.subjectName,
    subjectRole: "",
    relationship: "",
    relationshipDurationMonths: 0,
    purpose: "job",
    strengthBand: entry.strengthBand,
    evidence: [],
    reservations: "",
    lengthPreference: "standard",
  };
}

function HistoryRow({
  entry,
  onResume,
  onRemove,
}: {
  entry: HistoryEntry;
  onResume: (entry: HistoryEntry) => void;
  onRemove: (sessionId: string) => void;
}) {
  const [preview, setPreview] = useState<JobPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadPreview() {
    if (!entry.jobId) {
      setError("No job was recorded for this session, so there is nothing to fetch.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/jobs/${entry.jobId}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.fix ?? body.cause ?? "Could not reach this session.");
      setPreview({ status: body.status, documentHtml: body.documentHtml ?? "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach this session.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div>
          <CardTitle className="text-sm font-medium">{entry.subjectName || "Untitled letter"}</CardTitle>
          <p className="text-muted-foreground text-xs">
            {entry.writerName} · {entry.strengthBand} · {new Date(entry.createdAt).toLocaleDateString()}
          </p>
        </div>
        <Badge variant={entry.status === "done" ? "default" : "secondary"}>{entry.status}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          {entry.jobId && (
            <Button size="sm" onClick={() => onResume(entry)}>
              {entry.status === "done" ? "Open letter" : "Continue review"}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={loadPreview} disabled={loading}>
            {loading ? "Checking…" : "Check status"}
          </Button>
          <ExportButton
            sessionId={entry.sessionId}
            filename={filenameFor(entry.subjectName)}
          />
          <Button size="sm" variant="ghost" onClick={() => onRemove(entry.sessionId)}>
            Remove from this list
          </Button>
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
        {preview && (
          <p className="text-muted-foreground text-xs">
            SuperDocs reports this session&apos;s latest job as: <strong>{preview.status}</strong>
            {!preview.documentHtml && " (no committed document text yet)."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function HistoryList({
  onResume,
  onBack,
}: {
  onResume: (sessionId: string, jobId: string, intake: Intake) => void;
  onBack: () => void;
}) {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);

  useEffect(() => {
    // localStorage does not exist during SSR. Reading it in the state
    // initializer would make the client's first render diverge from the
    // server-rendered markup; deferring to an effect avoids that hydration
    // mismatch at the cost of one extra render pass.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEntries(listHistory());
  }, []);

  function handleRemove(sessionId: string) {
    removeHistory(sessionId);
    setEntries(listHistory());
  }

  function handleResume(entry: HistoryEntry) {
    if (!entry.jobId) return;
    onResume(entry.sessionId, entry.jobId, stubIntake(entry));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-sm">
          Stored on this device only: subject, writer, band and dates. Not the evidence, reservations or
          tone notes you typed — those never leave the browser tab they were entered in.
        </p>
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back
        </Button>
      </div>

      {entries === null && <p className="text-muted-foreground text-sm">Loading…</p>}
      {entries?.length === 0 && <p className="text-muted-foreground text-sm">No letters yet.</p>}
      {entries?.map((entry) => (
        <HistoryRow key={entry.sessionId} entry={entry} onResume={handleResume} onRemove={handleRemove} />
      ))}
    </div>
  );
}
