import { useState } from "react";
import { Link } from "react-router-dom";
import { Search, Loader2, AlertCircle, FileText, ExternalLink, Sparkles } from "lucide-react";
import { usePackets } from "@/hooks/usePackets";
import { useSearchPacket } from "@/hooks/useSearch";

const SUGGESTED_QUERIES = [
  "Acute Bronchitis",
  "Jane Smith",
  "ACC-8821-4433",
  "CASE-000001",
  "Confidential settlement",
  "123-45-6789",
];

export function SearchPage() {
  const [packetId, setPacketId] = useState("");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const { data: packets, isLoading: packetsLoading } = usePackets();
  const { data: searchResult, isLoading, error, refetch } = useSearchPacket(packetId, submittedQuery);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!packetId || !query.trim()) return;
    setSubmittedQuery(query);
    refetch();
  };

  const handleSuggestionClick = (suggested: string) => {
    setQuery(suggested);
    if (packetId) {
      setSubmittedQuery(suggested);
      refetch();
    }
  };

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8 animate-fade-in">
      {/* Header */}
      <div className="pb-2 border-b dark:border-slate-800/80 border-slate-200/80">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-display font-bold tracking-tight dark:text-white text-slate-900">Packet Search</h1>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium dark:bg-sky-500/10 dark:text-sky-400 dark:border-sky-500/20 bg-sky-50 text-sky-700 border border-sky-200">
            E-Discovery Intelligence
          </span>
        </div>
        <p className="dark:text-slate-400 text-slate-600 text-sm mt-1">
          Perform OCR full-text search across scanned pages, extracted document bodies, and sequential Bates stamping ranges.
        </p>
      </div>

      {/* Search Input Bar */}
      <form onSubmit={handleSubmit} className="p-5 rounded-2xl dark:bg-slate-900/80 bg-white border dark:border-slate-800/90 border-slate-200 shadow-sm backdrop-blur-md space-y-3">
        <div className="flex flex-col sm:flex-row gap-3">
          <select
            value={packetId}
            onChange={(e) => setPacketId(e.target.value)}
            className="px-4 py-2.5 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-100 text-slate-900 text-sm font-medium focus:ring-2 focus:ring-sky-500 focus:border-sky-500 outline-none sm:w-64 cursor-pointer"
          >
            <option value="">Select packet...</option>
            {packets?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 dark:text-slate-400 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search filenames, extracted content, or Bates numbers..."
              className="w-full pl-10 pr-4 py-2.5 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-slate-100 text-slate-900 dark:placeholder-slate-500 placeholder-slate-400 text-sm focus:ring-2 focus:ring-sky-500 focus:border-sky-500 outline-none transition-all"
            />
          </div>
          <button
            type="submit"
            disabled={!packetId || !query.trim() || isLoading}
            className="px-6 py-2.5 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-medium text-sm rounded-xl shadow-glow-sm hover:shadow-glow-md disabled:opacity-50 transition-all flex items-center justify-center gap-2 cursor-pointer"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Search
          </button>
        </div>

        {/* Suggested Quick Search Chips */}
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          <span className="text-[11px] font-mono dark:text-slate-400 text-slate-500 flex items-center gap-1">
            <Sparkles className="h-3 w-3 text-sky-500" />
            Try searching:
          </span>
          {SUGGESTED_QUERIES.map((suggested) => (
            <button
              key={suggested}
              type="button"
              onClick={() => handleSuggestionClick(suggested)}
              className="px-2.5 py-0.5 rounded-lg text-xs font-mono dark:bg-slate-800/80 dark:hover:bg-slate-700 dark:text-slate-300 bg-slate-100 hover:bg-slate-200 text-slate-700 border dark:border-slate-700/60 border-slate-200 transition-all cursor-pointer"
            >
              {suggested}
            </button>
          ))}
        </div>
      </form>

      {packetsLoading && (
        <div className="flex items-center gap-2 text-sm dark:text-slate-400 text-slate-600">
          <Loader2 className="h-4 w-4 animate-spin text-sky-500" />
          <span>Loading packets...</span>
        </div>
      )}

      {error && !isLoading && (
        <div className="dark:bg-rose-950/40 bg-rose-50 border dark:border-rose-800/80 border-rose-200 rounded-2xl p-5 backdrop-blur-md flex items-center gap-3">
          <AlertCircle className="h-5 w-5 text-rose-500 shrink-0" />
          <span className="text-sm dark:text-rose-200 text-rose-800">Search failed: {error.message}</span>
        </div>
      )}

      {submittedQuery && !isLoading && !error && searchResult && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-mono dark:text-slate-400 text-slate-600">
              Found <span className="font-bold text-sky-500">{searchResult.total_results}</span> match(es) for "<span className="dark:text-white text-slate-900 font-medium">{searchResult.query}</span>"
            </p>
          </div>

          <div className="space-y-3">
            {searchResult.results.length === 0 ? (
              <div className="dark:bg-slate-900/60 bg-white border dark:border-slate-800 border-slate-200 rounded-2xl p-12 text-center dark:text-slate-400 text-slate-500">
                <Search className="h-10 w-10 mx-auto dark:text-slate-600 text-slate-400 mb-3" />
                <p className="dark:text-slate-300 text-slate-700 font-medium font-display">No matching documents found</p>
                <p className="text-xs dark:text-slate-500 text-slate-400 mt-1">Try another keyword, phrase, or check OCR processing status.</p>
              </div>
            ) : (
              searchResult.results.map((result) => (
                <div key={result.document_id} className="dark:bg-slate-900/80 bg-white border dark:border-slate-800/90 border-slate-200 rounded-2xl p-5 shadow-sm dark:hover:border-slate-700 hover:border-slate-300 transition-all space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        to={`/packets/${packetId}`}
                        className="font-semibold text-base dark:text-white text-slate-900 hover:text-sky-500 transition-colors flex items-center gap-2 group"
                      >
                        <FileText className="h-4 w-4 text-sky-500" />
                        <span className="truncate">{result.document_name}</span>
                        <ExternalLink className="h-3.5 w-3.5 text-slate-400 group-hover:text-sky-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </Link>
                      <div className="flex items-center gap-2 mt-1.5 text-xs dark:text-slate-400 text-slate-500">
                        <span className="px-2 py-0.5 dark:bg-slate-800 dark:text-slate-300 bg-slate-100 text-slate-700 rounded-md font-mono">{result.document_type}</span>
                        <span>•</span>
                        <span>{result.page_count} pages</span>
                        <span>•</span>
                        <span className="capitalize">{result.status.replace("_", " ")}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5 flex-shrink-0">
                      {result.matched_fields.map((field) => (
                        <span key={field} className="px-2 py-0.5 text-xs font-mono dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/20 bg-sky-50 text-sky-700 border border-sky-200 rounded-md">
                          {field}
                        </span>
                      ))}
                    </div>
                  </div>

                  {result.snippets.length > 0 && (
                    <div className="space-y-2 pt-1 border-t dark:border-slate-800/60 border-slate-200">
                      {result.snippets.slice(0, 3).map((s, i) => (
                        <div key={i} className="text-xs dark:text-slate-300 text-slate-700 dark:bg-slate-950/60 bg-slate-50 rounded-xl p-3 border dark:border-slate-800/60 border-slate-200 font-mono flex items-start gap-2">
                          <span className="px-1.5 py-0.5 rounded dark:bg-sky-500/20 dark:text-sky-400 bg-sky-100 text-sky-700 text-[10px] font-bold shrink-0">
                            Page {s.page_number}
                          </span>
                          <span className="dark:text-slate-300 text-slate-700 leading-relaxed font-sans">{s.snippet}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}