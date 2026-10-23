import { useState } from "react";
import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { exportElementToPdf } from "@/lib/pdf";

type PdfExportButtonProps = {
  targetId: string;
  filename?: string;
};

export function PdfExportButton({
  targetId,
  filename = "interview-preparation-brief.pdf",
}: PdfExportButtonProps) {
  const [loading, setLoading] = useState(false);

  async function onExport() {
    const el = document.getElementById(targetId);
    if (!el) return;
    setLoading(true);
    try {
      await exportElementToPdf(el, filename);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button type="button" variant="outline" onClick={onExport} disabled={loading}>
      <Download className="h-4 w-4" />
      {loading ? "Exporting…" : "Export PDF"}
    </Button>
  );
}
