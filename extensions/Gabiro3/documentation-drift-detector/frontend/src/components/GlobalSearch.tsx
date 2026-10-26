import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { searchDocuments, type SearchHit, type SearchResponse } from "../api";
import { DocumentViewer } from "./DocumentViewer";
import { Icon } from "./Icon";

const DEBOUNCE_MS = 220;
const MIN_QUERY = 2;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Render a snippet with the matched span marked.
 *
 * The server sends offsets, not markup, so document text containing angle
 * brackets can never inject anything into this list.
 */
function Snippet({ hit }: { hit: SearchHit }) {
  const { text, match_start: start, match_length: length } = hit.snippet;
  if (start < 0 || length <= 0) {
    return <p className="search-snippet">{text}</p>;
  }
  return (
    <p className="search-snippet">
      {text.slice(0, start)}
      <mark className="search-mark">{text.slice(start, start + length)}</mark>
      {text.slice(start + length)}
    </p>
  );
}

function ResultRow({
  hit,
  active,
  onPick,
  onHover,
}: {
  hit: SearchHit;
  active: boolean;
  onPick: (hit: SearchHit) => void;
  onHover: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={`search-result ${active ? "is-active" : ""}`}
        onClick={() => onPick(hit)}
        onMouseMove={onHover}
      >
        <span className="search-result-head">
          <span className="search-result-file">
            <Icon name="documents" size={13} />
            {hit.filename}
          </span>
          {hit.match_type === "exact" ? (
            <span className="badge badge-neutral">
              {hit.occurrences} match{hit.occurrences === 1 ? "" : "es"}
            </span>
          ) : (
            <span className="badge badge-neutral" title="Related by meaning, not by wording">
              related
            </span>
          )}
        </span>
        <Snippet hit={hit} />
      </button>
    </li>
  );
}

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [viewing, setViewing] = useState<{ hit: SearchHit } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setData(null);
    setError(null);
    setActive(0);
  }, []);

  // Ctrl/Cmd-K from anywhere, Escape to leave.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape" && open && !viewing) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, viewing, close]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Debounced, and every in-flight request is aborted when the query moves on:
  // without that, a slow response for "np" can land after "npm install" and
  // overwrite the newer results.
  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_QUERY) {
      setData(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      searchDocuments(q, { limit: 30, signal: controller.signal })
        .then((res) => {
          setData(res);
          setError(null);
          setActive(0);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          setError(errorMessage(err));
          setData(null);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query]);

  const results = useMemo(() => data?.results ?? [], [data]);

  function pick(hit: SearchHit) {
    setViewing({ hit });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(results[active]);
    }
  }

  const exact = results.filter((r) => r.match_type === "exact");
  const related = results.filter((r) => r.match_type === "semantic");
  const trimmed = query.trim();

  return (
    <>
      <button type="button" className="search-trigger" onClick={() => setOpen(true)}>
        <Icon name="search" size={15} />
        <span className="search-trigger-label">Search documents</span>
        <kbd className="search-kbd">Ctrl K</kbd>
      </button>

      {open && (
        <div className="search-overlay" onClick={close}>
          <div className="search-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="search-input-row">
              <Icon name="search" size={16} />
              <input
                ref={inputRef}
                className="search-input"
                placeholder="Search every document…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
              />
              {loading && <span className="search-status text-muted">Searching…</span>}
              <button type="button" className="btn btn-ghost btn-icon" onClick={close} aria-label="Close">
                <Icon name="close" size={15} />
              </button>
            </div>

            <div className="search-results">
              {error && <p className="text-danger search-message">{error}</p>}

              {!error && trimmed.length > 0 && trimmed.length < MIN_QUERY && (
                <p className="text-muted search-message">Keep typing — at least {MIN_QUERY} characters.</p>
              )}

              {!error && trimmed.length >= MIN_QUERY && !loading && results.length === 0 && (
                <p className="text-muted search-message">
                  Nothing matches &ldquo;{trimmed}&rdquo; in any document.
                </p>
              )}

              {exact.length > 0 && (
                <>
                  <p className="eyebrow search-group-label">
                    Contains &ldquo;{trimmed}&rdquo; ({exact.length})
                  </p>
                  <ul className="search-result-list">
                    {exact.map((hit) => (
                      <ResultRow
                        key={hit.chunk_row_id}
                        hit={hit}
                        active={results[active]?.chunk_row_id === hit.chunk_row_id}
                        onPick={pick}
                        onHover={() => setActive(results.indexOf(hit))}
                      />
                    ))}
                  </ul>
                </>
              )}

              {related.length > 0 && (
                <>
                  <p className="eyebrow search-group-label">
                    Related by meaning ({related.length})
                  </p>
                  <ul className="search-result-list">
                    {related.map((hit) => (
                      <ResultRow
                        key={hit.chunk_row_id}
                        hit={hit}
                        active={results[active]?.chunk_row_id === hit.chunk_row_id}
                        onPick={pick}
                        onHover={() => setActive(results.indexOf(hit))}
                      />
                    ))}
                  </ul>
                </>
              )}

              {/* Said plainly rather than letting an absent semantic half look
                  like an absence of matches. */}
              {data && !data.semantic_available && exact.length > 0 && (
                <p className="text-muted search-message search-note">
                  Showing literal matches only — no embedding provider is available for
                  related-meaning results.
                </p>
              )}
            </div>

            {results.length > 0 && (
              <footer className="search-footer text-muted">
                <span>&uarr;&darr; to move</span>
                <span>Enter to open</span>
                <span>Esc to close</span>
              </footer>
            )}
          </div>
        </div>
      )}

      {viewing && (
        <DocumentViewer
          documentId={viewing.hit.document_id}
          filename={viewing.hit.filename}
          targetChunkId={viewing.hit.chunk_id}
          onClose={() => setViewing(null)}
        />
      )}
    </>
  );
}
