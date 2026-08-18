import { cn } from "@/lib/utils";
import type { SuperDocsProposal } from "./superdocs-contract";

/**
 * Readable before/after presentation of one SuperDocs proposal. Proposal HTML
 * is reduced to plain text: reviewers approve language, not markup.
 */
export function ProposalCard({
  proposal,
  index,
  layout = "split",
}: {
  proposal: SuperDocsProposal;
  index: number;
  layout?: "split" | "stacked";
}) {
  const before = readableHtml(proposal.beforeHtml, "No previous text");
  const after = readableHtml(proposal.afterHtml, "Text removed");

  return (
    <article className="overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface">
      <div className="flex items-baseline gap-2.5 border-b border-line bg-canvas/60 px-3.5 py-2.5">
        <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint tabular-nums">
          Change {index + 1}
        </span>
        <p className="text-[13px] leading-relaxed text-ink-soft">
          {proposal.explanation || "SuperDocs proposed a language edit."}
        </p>
      </div>
      <div
        className={cn(
          "grid",
          layout === "split" ? "sm:grid-cols-2 sm:divide-x" : "divide-y",
          "divide-line",
        )}
      >
        <Side label="Before" text={before} />
        <Side label="After" text={after} tone="after" />
      </div>
    </article>
  );
}

function Side({
  label,
  text,
  tone = "before",
}: {
  label: string;
  text: string;
  tone?: "before" | "after";
}) {
  return (
    <div className={cn("px-3.5 py-3", tone === "after" && "bg-ok-soft/45")}>
      <p
        className={cn(
          "mb-1.5 text-[10px] font-semibold uppercase tracking-[0.1em]",
          tone === "after" ? "text-ok" : "text-faint",
        )}
      >
        {label}
      </p>
      <p
        className={cn(
          "whitespace-pre-line font-serif text-[13.5px] leading-relaxed",
          tone === "after" ? "text-ink" : "text-muted",
        )}
      >
        {text}
      </p>
    </div>
  );
}

export function readableHtml(value: string | null, fallback: string): string {
  if (value === null || value.trim() === "") {
    return fallback;
  }
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replaceAll("&nbsp;", " ")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&gt;", ">")
    .replaceAll("&lt;", "<")
    .replaceAll("&amp;", "&")
    .replace(/\s*\n\s*/g, "\n")
    .replace(/[ \t]+/g, " ")
    .trim();
}
