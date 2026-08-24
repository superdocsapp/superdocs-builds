import type { ReactNode } from "react";

import { GoogleDocsMark } from "./brand";

export interface DocumentIdentityData {
  name: string;
  revision: string | null;
  origin?: string | null;
}

export function DocumentIdentity({
  document,
  action,
}: {
  document: DocumentIdentityData;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[72px] items-center gap-3.5 border-b border-border bg-surface px-6 py-4 sm:px-8 lg:px-10">
      <span
        className="grid size-10 shrink-0 place-items-center rounded-[11px] border border-border-light bg-surface-sunken shadow-[var(--shadow-subtle)]"
        aria-hidden="true"
      >
        <GoogleDocsMark className="size-[19px]" />
      </span>
      <div className="min-w-0">
        <h1 className="truncate text-[16px] font-semibold tracking-[-0.024em] text-ink sm:text-[17px]">
          {document.name}
        </h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.75px] text-muted">
          <span>Google Docs</span>
          {document.revision ? (
            <>
              <span className="h-3 w-px bg-border" aria-hidden="true" />
              <span>
                Revision <span className="type-mono text-[11px]">{shortId(document.revision)}</span>
              </span>
            </>
          ) : null}
          {document.origin ? (
            <>
              <span className="h-3 w-px bg-border" aria-hidden="true" />
              <span className="text-muted-soft">{document.origin}</span>
            </>
          ) : null}
        </div>
      </div>
      {action ? <div className="ml-auto shrink-0">{action}</div> : null}
    </div>
  );
}

export function shortId(value: string, length = 10): string {
  if (value.length <= length) return value;
  return `${value.slice(0, 6)}…${value.slice(-3)}`;
}
