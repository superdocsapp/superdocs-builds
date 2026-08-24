import { FileText } from "lucide-react";
import type { SourceRegistration } from "../lib/api";

export function SourceSummary({
  source,
  compact,
}: {
  source: SourceRegistration;
  compact?: boolean;
}) {
  const rev = source.baseline.revision_id;
  const shortRev = rev.length > 12 ? `${rev.slice(0, 6)}…${rev.slice(-4)}` : rev;

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-[13px] text-muted">
        <FileText className="w-3.5 h-3.5 text-accent flex-shrink-0" />
        <span className="text-ink font-medium truncate">{source.source.name}</span>
        <span className="text-border">·</span>
        <span className="font-mono text-xs">{shortRev}</span>
      </div>
    );
  }

  return (
    <div className="rounded-[10px] border border-border-light bg-surface p-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded bg-accent-soft flex items-center justify-center flex-shrink-0">
          <FileText className="w-4.5 h-4.5 text-accent" />
        </div>
        <div className="min-w-0">
          <p className="text-[14px] font-medium text-ink truncate">
            {source.source.name}
          </p>
          <p className="text-[12px] text-muted mt-0.5">Google Docs</p>
          <p className="text-[12px] text-muted mt-1 font-mono">
            Revision {shortRev}
          </p>
        </div>
      </div>
    </div>
  );
}
