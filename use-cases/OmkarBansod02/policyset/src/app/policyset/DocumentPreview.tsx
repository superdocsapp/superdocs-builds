import type { ReactNode } from "react";
import {
  ATTORNEY_REVIEW_DISCLAIMER,
  type PolicyDocumentType,
  type PolicyProfile,
} from "@/domain";
import { parseRendererHtml } from "@/documents/parse-html";
import { POLICY_DOCUMENT_TITLES } from "@/documents/spec";

/**
 * The rendered policy document. This is the primary artifact of the product,
 * so it is presented as a page — editorial type on a white sheet — rather than
 * as another panel of application chrome.
 */
export function DocumentPreview({
  documentType,
  html,
  profile,
  source = "deterministic",
}: {
  documentType: PolicyDocumentType;
  html: string;
  profile: PolicyProfile;
  source?: "deterministic" | "superdocs";
}) {
  const body = previewBody(html, profile.company.legalName);
  const title = body.title ?? POLICY_DOCUMENT_TITLES[documentType];

  return (
    <article
      className="mx-auto w-full max-w-[46rem] rounded-[var(--radius-card)] border border-line bg-surface shadow-sheet"
      data-preview-surface={
        source === "superdocs" ? "superdocs-html" : "deterministic-html"
      }
      data-policy-document={documentType}
    >
      <div className="px-7 py-10 sm:px-14 sm:py-14">
        <header>
          <h1 className="font-serif text-[1.75rem] font-semibold leading-[1.2] tracking-[-0.015em] text-ink text-balance">
            {title}
          </h1>
          <p className="mt-3 text-[11px] font-medium uppercase tracking-[0.1em] text-muted">
            {profile.company.legalName}
            <span aria-hidden="true" className="px-1.5 text-faint">
              ·
            </span>
            Effective {formatEffectiveDate(profile.company.effectiveDate)}
          </p>
        </header>

        <hr className="my-9 border-t border-line" />

        <div className="policy-document">{body.nodes}</div>

        <footer className="mt-12 border-t border-line pt-5">
          <p className="text-xs leading-relaxed text-muted">
            {ATTORNEY_REVIEW_DISCLAIMER}
          </p>
        </footer>
      </div>
    </article>
  );
}

function previewBody(
  html: string,
  legalName: string,
): { title: string | null; nodes: ReactNode[] } {
  const blocks = parseRendererHtml(html);
  let title: string | null = null;
  const nodes: ReactNode[] = [];
  let skippedCompanyLine = false;

  for (const [index, block] of blocks.entries()) {
    if (block.kind === "fact") {
      continue;
    }

    if (block.kind === "heading" && block.level === 1 && title === null) {
      title = block.text;
      continue;
    }

    if (
      !skippedCompanyLine &&
      block.kind === "paragraph" &&
      block.text === legalName
    ) {
      skippedCompanyLine = true;
      continue;
    }

    if (block.kind === "heading") {
      nodes.push(<h2 key={`${block.kind}-${index}`}>{block.text}</h2>);
      continue;
    }

    nodes.push(<p key={`${block.kind}-${index}`}>{block.text}</p>);
  }

  return { title, nodes };
}

function formatEffectiveDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) {
    return iso;
  }

  const date = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  );

  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
