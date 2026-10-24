import { downloadVersion } from "../api";

export default function VersionHistory({ matterId, documentId, userId, versions }) {
  return (
    <section className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-4">Version history</h2>
      <ul className="divide-y divide-slate/20">
        {versions.map((v) => (
          <li key={v.version_number} className="py-3 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium">v{v.version_number}</div>
              <div className="text-xs text-slate">{v.comment}</div>
              <div className="text-xs text-slate/70">
                {v.created_by} - {new Date(v.created_at).toLocaleString()}
              </div>
            </div>
            {v.has_exported_file ? (
              <button
                onClick={() =>
                  downloadVersion(matterId, documentId, v.version_number, userId, `${documentId}-v${v.version_number}.docx`)
                }
                className="text-xs font-medium text-ink underline"
              >
                Download
              </button>
            ) : (
              <span className="text-xs text-slate/50">No file</span>
            )}
          </li>
        ))}
        {versions.length === 0 && (
          <li className="py-6 text-sm text-slate text-center">No versions yet.</li>
        )}
      </ul>
    </section>
  );
}