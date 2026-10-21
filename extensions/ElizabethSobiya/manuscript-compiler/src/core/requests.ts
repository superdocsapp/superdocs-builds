/**
 * What to do when a compile is asked for while one is already running.
 *
 * This is policy, not plumbing, so it lives in core where it can be tested without
 * an Obsidian app around it.
 *
 * The rule is *coalesce*, never drop and never queue a backlog:
 *
 *   drop   — the original behaviour, and a bug. Compile-on-save debounces 1.5s and
 *            a cold compile of a long book takes seconds, so an edit made while a
 *            compile was running was discarded. The output then disagreed with the
 *            vault, silently, because background compiles are quiet by design.
 *   queue  — ten saves during one compile would run ten more compiles. The only
 *            one whose result anybody wants is the last.
 *   merge  — one trailing run that satisfies every request folded into it.
 */

export interface CompileRequest {
  exportFormats?: Array<"pdf" | "docx" | "html">;
  quiet?: boolean;
}

/**
 * Fold a request that arrived mid-compile into whatever is already queued.
 *
 * An export request wins over a plain compile, because someone who asked for a PDF
 * still wants a PDF. The merged request is quiet only if every request folded into
 * it was quiet — a deliberate compile must not be silenced by a background one.
 */
export function mergeRequests(
  existing: CompileRequest | null,
  incoming: CompileRequest,
): CompileRequest {
  if (!existing) return { ...incoming };

  const formats = [
    ...new Set([...(existing.exportFormats ?? []), ...(incoming.exportFormats ?? [])]),
  ] as CompileRequest["exportFormats"];

  return {
    ...(formats && formats.length ? { exportFormats: formats } : {}),
    quiet: Boolean(existing.quiet) && Boolean(incoming.quiet),
  };
}
