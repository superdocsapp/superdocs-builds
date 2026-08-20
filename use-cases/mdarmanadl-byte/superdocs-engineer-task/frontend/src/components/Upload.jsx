import { useRef, useState } from "react";
import { uploadDocument } from "../api/document";

export default function Upload({ setSessionId, setDocumentHtml }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);

  const inputRef = useRef(null);

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0];

    if (selectedFile) {
      setFile(selectedFile);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      alert("Please select a PDF.");
      return;
    }

    try {
      setLoading(true);

      const data = await uploadDocument(file);

      console.log("UPLOAD RESPONSE:", data);

      setSessionId(data.session_id);

      /*
       * Your backend returns:
       *
       * {
       *   filename,
       *   size_bytes,
       *   upload_id,
       *   session_id,
       *   processed
       * }
       *
       * So the HTML comes from `processed`.
       */

      const html =
        data?.processed?.html || data?.processed?.document_html || "";

      if (html) {
        setDocumentHtml(html);
      }
    } catch (error) {
      console.error("UPLOAD ERROR:", error);

      console.error("STATUS:", error?.response?.status);

      console.error("RESPONSE:", error?.response?.data);

      alert(error?.response?.data?.detail || "Document upload failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="upload-component">
      <div
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-xl border border-dashed px-6 py-8 text-center transition ${
          file
            ? "border-indigo-300 bg-indigo-50/40"
            : "border-slate-300 bg-slate-50 hover:border-indigo-400 hover:bg-indigo-50/40"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={handleFileChange}
        />

        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600">
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <path d="M12 16V4" strokeWidth="1.8" strokeLinecap="round" />

            <path
              d="m8 8 4-4 4 4"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            <path d="M5 20h14" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </div>

        {file ? (
          <>
            <p className="mt-4 truncate text-sm font-semibold text-slate-700">
              {file.name}
            </p>

            <p className="mt-1 text-xs text-slate-400">
              Click to choose another PDF
            </p>
          </>
        ) : (
          <>
            <p className="mt-4 text-sm font-semibold text-slate-700">
              Upload your document
            </p>

            <p className="mt-1 text-xs text-slate-400">
              Click to browse · PDF only
            </p>
          </>
        )}
      </div>

      {file && (
        <div className="mt-3 flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-red-50 text-[9px] font-bold text-red-600">
            PDF
          </div>

          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-slate-700">
              {file.name}
            </p>

            <p className="text-[10px] text-slate-400">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={handleUpload}
        disabled={!file || loading}
        className="mt-3 w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {loading ? "Uploading..." : "Upload Document"}
      </button>
    </div>
  );
}
