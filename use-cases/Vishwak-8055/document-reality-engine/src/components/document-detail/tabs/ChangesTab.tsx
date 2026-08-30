import clsx from "clsx";
import { GitCommitHorizontal } from "lucide-react";
import type { SDDocument } from "../../../types/domain";
import { sortChangesByRecency, summarizeChange } from "../../../domain/changes";
import { formatDateTime } from "../../../domain/utils";
import { EmptyState } from "../../ui/EmptyState";

export function ChangesTab({ document }: { document: SDDocument }) {
  const changes = sortChangesByRecency(document.changes);

  if (changes.length === 0) {
    return (
      <EmptyState
        icon={GitCommitHorizontal}
        title="No changes recorded yet"
        description="This is the first version of the document on file — there is no prior version to compare against."
      />
    );
  }

  return (
    <ul className="space-y-4">
      {changes.map((change) => (
        <li key={change.id} className="rounded-md border border-line bg-paper-0 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-numeric text-sm font-semibold text-text-primary">
              v{change.fromVersion} → v{change.toVersion}
            </p>
            <p className="text-xs text-text-tertiary">
              {change.author} · {formatDateTime(change.occurredAt)}
            </p>
          </div>
          <p className="mt-1.5 text-sm text-text-secondary">{change.summary}</p>

          <ul className="mt-3 flex flex-wrap gap-1.5">
            {summarizeChange(change).map((line) => (
              <li
                key={line.label}
                className={clsx(
                  "rounded-md border px-2 py-0.5 text-xs font-medium",
                  line.tone === "warning" && "border-warning/30 bg-warning-soft text-warning",
                  line.tone === "positive" && "border-verified/30 bg-verified-soft text-verified",
                  line.tone === "neutral" && "border-line bg-paper-50 text-text-secondary",
                )}
              >
                {line.label}
              </li>
            ))}
          </ul>

          {change.highlights.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-text-tertiary">
              {change.highlights.map((highlight, index) => (
                <li key={index}>{highlight}</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}
