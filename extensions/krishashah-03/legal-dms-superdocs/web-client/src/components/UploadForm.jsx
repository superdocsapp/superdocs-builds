import { useState } from "react";

export default function UploadForm({ busy, onUpload }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (!file) return;
    onUpload(title.trim(), file);
    setFile(null);
    setTitle("");
    e.target.reset();
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-3">Upload a document</h2>

      <label className="block text-xs uppercase tracking-wide text-slate mb-1">Title</label>
      <input
        className="w-full rounded border border-slate/40 px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ink/20"
        placeholder="e.g. Vendor Services Agreement"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />

      <label className="block text-xs uppercase tracking-wide text-slate mb-1">File</label>
      <input
        type="file"
        accept=".docx,.pdf,.doc,.txt"
        className="w-full text-sm mb-3"
        onChange={(e) => setFile(e.target.files[0] || null)}
      />

      <button
        type="submit"
        disabled={busy || !file}
        className="rounded bg-ink text-paper px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        Upload as new document
      </button>
    </form>
  );
}