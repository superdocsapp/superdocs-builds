import { useState } from "react";
import { exportDocument } from "../api/export";

export default function ExportButton({
  sessionId,
  documentId = "doc_primary",
}) {
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    try {
      setLoading(true);

      const blob = await exportDocument(sessionId, documentId, "pdf");

      const url = window.URL.createObjectURL(blob);

      const link = document.createElement("a");

      link.href = url;
      link.download = "document.pdf";

      document.body.appendChild(link);

      link.click();

      link.remove();

      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error(error);

      alert("Unable to export document.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button className="export-button" onClick={handleExport} disabled={loading}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M12 3v12" strokeWidth="1.8" strokeLinecap="round" />

        <path
          d="m7 10 5 5 5-5"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        <path d="M5 21h14" strokeWidth="1.8" strokeLinecap="round" />
      </svg>

      {loading ? "Exporting..." : "Export PDF"}
    </button>
  );
}
