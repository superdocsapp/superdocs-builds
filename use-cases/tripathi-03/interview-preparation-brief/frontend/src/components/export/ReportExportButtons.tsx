import { useState } from "react";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { exportBriefReport, type ReportExportFormat } from "@/services/api";

const FORMATS: { format: ReportExportFormat; label: string }[] = [
  { format: "pdf", label: "PDF" },
  { format: "docx", label: "DOCX" },
  { format: "markdown", label: "Markdown" },
  { format: "html", label: "HTML" },
];

export function ReportExportButtons({ briefId }: { briefId: string }) {
  const [busy, setBusy] = useState<ReportExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onExport(format: ReportExportFormat) {
    setBusy(format);
    setError(null);
    try {
      const { blob, filename } = await exportBriefReport(briefId, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {FORMATS.map(({ format, label }) => (
          <Button
            key={format}
            type="button"
            variant="outline"
            size="sm"
            disabled={busy !== null}
            onClick={() => onExport(format)}
          >
            <Download className="h-3.5 w-3.5" />
            {busy === format ? "Exporting…" : label}
          </Button>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
