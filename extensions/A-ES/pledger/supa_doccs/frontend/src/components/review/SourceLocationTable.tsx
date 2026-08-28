import { Fragment } from "react";
import type { SourceCitation } from "@/types/review";

interface SourceLocationTableProps {
  citations: SourceCitation[];
}

function shortId(id: string | null | undefined): string | null {
  if (!id) return null;
  return id.length > 8 ? id.slice(0, 8) : id;
}

/**
 * Renders source location metadata in an accessible table.
 * Only includes citations with non-null source_location.
 *
 * Each located citation also shows:
 * - its document identity (short document id · version prefix), because a
 *   span alone cannot be traced to a source once documents are re-uploaded
 *   or piles contain multiple documents;
 * - the actual quoted text resolved at the persisted offsets, so a reviewer
 *   never has to manually resolve bare offset numbers against the raw file.
 */
export function SourceLocationTable({ citations }: SourceLocationTableProps) {
  const locatedCitations = citations.filter(
    (c) => c.source_location !== null
  );

  if (locatedCitations.length === 0) {
    return null;
  }

  return (
    <section aria-label="Source locations">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-white/40">
        Source Locations
      </h3>
      <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
        <table className="w-full text-sm text-white/70">
          <thead className="bg-white/[0.03] text-[10px] uppercase tracking-wider text-white/30">
            <tr>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Document
              </th>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Page
              </th>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Section
              </th>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Clause Ref
              </th>
              <th scope="col" className="px-3 py-2.5 text-left font-medium">
                Offset Range
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {locatedCitations.map((citation) => {
              const loc = citation.source_location!;
              const doc = shortId(citation.document_id);
              const ver = shortId(citation.document_version_id);
              return (
                <Fragment key={citation.claim_id}>
                  <tr className="transition-colors hover:bg-white/[0.03]">
                    <td className="px-3 py-2.5 font-mono text-xs text-white/60">
                      {doc ? (
                        <span title={`document ${citation.document_id ?? ""} · version ${citation.document_version_id ?? ""}`}>
                          doc {doc}
                          {ver ? ` · v${ver}` : ""}
                        </span>
                      ) : (
                        <span className="text-amber-400/80" title="No document reference — citation is not auditable">
                          unlinked
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-white/60">
                      {loc.page_number !== null ? loc.page_number : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-white/60">
                      {loc.section_id ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 text-white/60">
                      {loc.clause_ref ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-white/50">
                      {loc.start_offset}–{loc.end_offset}
                    </td>
                  </tr>
                  {citation.snippet && (
                    <tr className="hover:bg-white/[0.02]">
                      <td colSpan={5} className="px-3 pb-2.5 pt-0">
                        <blockquote
                          aria-label={`Quoted source text for claim ${citation.claim_id}`}
                          className="rounded border-l-2 border-indigo-500/40 bg-indigo-500/[0.04] px-3 py-1.5 font-mono text-xs leading-relaxed text-white/70"
                        >
                          “{citation.snippet}”
                        </blockquote>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
