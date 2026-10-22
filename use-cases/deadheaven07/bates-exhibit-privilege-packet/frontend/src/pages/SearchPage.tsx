import { useState } from "react";
import { Link } from "react-router-dom";
import { Search, Loader2, AlertCircle } from "lucide-react";
import { usePackets } from "@/hooks/usePackets";
import { useSearchPacket } from "@/hooks/useSearch";

export function SearchPage() {
  const [packetId, setPacketId] = useState("");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const { data: packets, isLoading: packetsLoading } = usePackets();
  const { data: searchResult, isLoading, error, refetch } = useSearchPacket(packetId, submittedQuery);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittedQuery(query);
    refetch();
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900">Search</h1>
      <p className="text-gray-500 mt-1">Search documents, extracted text, and Bates numbers within a packet.</p>

      <form onSubmit={handleSubmit} className="mt-6 bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex flex-col sm:flex-row gap-3">
          <select
            value={packetId}
            onChange={(e) => setPacketId(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 sm:w-64"
          >
            <option value="">Select packet...</option>
            {packets?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search filenames, content, or Bates numbers..."
              className="w-full pl-9 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>
          <button
            type="submit"
            disabled={!packetId || !query.trim() || isLoading}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
          </button>
        </div>
      </form>

      {packetsLoading && <p className="text-sm text-gray-500 mt-4">Loading packets...</p>}

      {error && !isLoading && (
        <div className="mt-6 bg-red-50 border border-red-200 rounded-lg p-4 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-red-600" />
          <span className="text-sm text-red-800">Search failed: {error.message}</span>
        </div>
      )}

      {submittedQuery && !isLoading && !error && searchResult && (
        <div className="mt-6">
          <p className="text-sm text-gray-600 mb-3">
            {searchResult.total_results} result(s) for "{searchResult.query}"
          </p>
          <div className="space-y-3">
            {searchResult.results.length === 0 && (
              <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-gray-500">
                No matching documents found.
              </div>
            )}
            {searchResult.results.map((result) => (
              <div key={result.document_id} className="bg-white rounded-lg border border-gray-200 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      to={`/packets/${packetId}`}
                      className="font-medium text-gray-900 hover:text-primary-600"
                    >
                      {result.document_name}
                    </Link>
                    <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                      <span className="px-1.5 py-0.5 bg-gray-100 rounded">{result.document_type}</span>
                      <span>{result.page_count} pages</span>
                      <span>{result.status.replace("_", " ")}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 flex-shrink-0">
                    {result.matched_fields.map((field) => (
                      <span key={field} className="px-1.5 py-0.5 text-xs bg-primary-50 text-primary-700 rounded">
                        {field}
                      </span>
                    ))}
                  </div>
                </div>
                {result.snippets.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {result.snippets.slice(0, 3).map((s, i) => (
                      <p key={i} className="text-xs text-gray-600 bg-gray-50 rounded p-2 border border-gray-100">
                        <span className="font-medium text-gray-800">Page {s.page_number}:</span> {s.snippet}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}