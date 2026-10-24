const KNOWN_USERS = [
  { id: "attorney-priya", label: "Priya Nair (attorney)" },
  { id: "attorney-sam", label: "Sam Okafor (attorney)" },
  { id: "paralegal-rina", label: "Rina Fernandes (paralegal)" },
];

export default function MatterDocumentList({
  matterId, userId, documents, selectedDocumentId, busy,
  onMatterIdChange, onUserIdChange, onLoad, onSelect,
}) {
  return (
    <section className="rounded-lg border border-slate/30 bg-white p-5">
      <h2 className="font-doc text-lg mb-4">Matter</h2>

      <label className="block text-xs uppercase tracking-wide text-slate mb-1">Matter ID</label>
      <input
        className="w-full rounded border border-slate/40 px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-ink/20"
        value={matterId}
        onChange={(e) => onMatterIdChange(e.target.value)}
      />

      <label className="block text-xs uppercase tracking-wide text-slate mb-1">Signed in as</label>
      <select
        className="w-full rounded border border-slate/40 px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-ink/20"
        value={userId}
        onChange={(e) => onUserIdChange(e.target.value)}
      >
        {KNOWN_USERS.map((u) => (
          <option key={u.id} value={u.id}>{u.label}</option>
        ))}
      </select>

      <button
        onClick={onLoad}
        disabled={busy}
        className="w-full rounded bg-ink text-paper py-2 text-sm font-medium disabled:opacity-50"
      >
        Load documents
      </button>

      <ul className="mt-5 divide-y divide-slate/20">
        {documents.map((doc) => (
          <li key={doc.document_id}>
            <button
              onClick={() => onSelect(doc)}
              className={`w-full text-left py-3 ${selectedDocumentId === doc.document_id ? "bg-ink/5" : ""}`}
            >
              <div className="font-doc text-sm">{doc.title}</div>
              <div className="text-xs text-slate mt-0.5">
                v{doc.current_version}
                {doc.checked_out_by ? ` - checked out by ${doc.checked_out_by}` : ""}
              </div>
            </button>
          </li>
        ))}
        {documents.length === 0 && (
          <li className="py-6 text-sm text-slate text-center">No documents loaded yet.</li>
        )}
      </ul>
    </section>
  );
}