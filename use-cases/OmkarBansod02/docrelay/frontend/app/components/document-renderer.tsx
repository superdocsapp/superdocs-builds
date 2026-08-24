import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { FrozenPreviewBlock } from "../lib/api";
import type { DocumentReviewMark } from "../lib/conversation";

/**
 * Truthful read-only page.
 *
 * Every element on this page comes from the frozen preview the API returned:
 * the block order, the block text, and the Google named style. No pagination,
 * word count, zoom or formatting chrome is invented, because none of it is
 * proven by the contract.
 */
export function DocumentRenderer({
  title,
  blocks,
  reviewMarks,
}: {
  title: string;
  blocks: FrozenPreviewBlock[];
  reviewMarks?: DocumentReviewMark[];
}) {
  return (
    <article aria-label={`${title} (read-only)`} className="document-page">
      <div className="flex min-w-0 flex-col">
        {blocks.map((block, index) => (
          <PreviewBlock
            key={`${block.kind}-${index}`}
            block={block}
            marks={(reviewMarks ?? []).filter((mark) => mark.blockIndex === index)}
          />
        ))}
      </div>
    </article>
  );
}

function PreviewBlock({
  block,
  marks,
}: {
  block: FrozenPreviewBlock;
  marks: DocumentReviewMark[];
}) {
  const style = block.named_style;
  if (block.kind === "heading") {
    return (
      <p className={cn("document-heading break-words first:mt-0", headingClass(style))}>
        {block.text}
      </p>
    );
  }
  return (
    <p className="document-body mt-[1.15em] break-words first:mt-0">
      <MarkedText text={block.text} marks={marks} />
    </p>
  );
}

/**
 * Renders the untouched baseline text, marking only spans whose location the
 * frozen mapping evidence identified. The baseline wording is never replaced.
 */
function MarkedText({ text, marks }: { text: string; marks: DocumentReviewMark[] }) {
  if (marks.length === 0) return <>{text}</>;
  const ordered = [...marks].sort((a, b) => a.start - b.start);
  const parts: ReactNode[] = [];
  let cursor = 0;
  ordered.forEach((mark, index) => {
    if (mark.start < cursor || mark.end > text.length) return;
    parts.push(text.slice(cursor, mark.start));
    parts.push(
      <mark
        key={`${mark.start}-${index}`}
        className="rounded-[2px] bg-review-mark px-[2px] text-foreground shadow-[inset_0_-2px_0_var(--review-mark-line)]"
        title="Awaiting your review"
      >
        {text.slice(mark.start, mark.end)}
      </mark>,
    );
    cursor = mark.end;
  });
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

/**
 * Heading rhythm on the reader page. Sizes step down clearly and the space
 * above a heading is always larger than the space below it, so a section
 * visibly belongs to the heading that opens it.
 */
function headingClass(style: string | null): string {
  switch (style) {
    case "TITLE":
      return "mb-10 text-[31px] font-semibold tracking-[-0.021em] leading-[1.16]";
    case "SUBTITLE":
      // Pulls back against the title's trailing space when one precedes it,
      // and still reads as a standalone deck when one does not.
      return "-mt-[1.75rem] mb-10 text-[17.5px] font-normal italic leading-[1.55] text-muted";
    case "HEADING_1":
      return "mt-[3.25rem] mb-2 text-[21.5px] font-semibold tracking-[-0.012em] leading-[1.28]";
    case "HEADING_2":
      return "mt-[2.5rem] mb-1.5 text-[18.5px] font-semibold tracking-[-0.008em] leading-[1.34]";
    default:
      return "mt-[2rem] mb-1 text-[16.5px] font-semibold tracking-[-0.004em] leading-[1.4]";
  }
}

export function DocumentPreviewUnavailable() {
  return (
    <div className="m-auto flex max-w-[24rem] flex-col items-center px-8 py-16 text-center">
      <span
        className="grid size-10 place-items-center rounded-[11px] border border-border-light bg-surface text-muted shadow-[var(--shadow-subtle)]"
        aria-hidden="true"
      >
        <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d="M3.5 2.5h5l4 4v7a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1Z" />
          <path d="M8.5 2.5v4h4" />
        </svg>
      </span>
      <p className="mt-4 text-[14.5px] font-medium text-foreground">
        Document preview isn&apos;t available.
      </p>
      <p className="mt-1.5 text-[13.25px] leading-[1.6] text-muted">
        This does not affect the frozen source used by DocRelay.
      </p>
    </div>
  );
}
