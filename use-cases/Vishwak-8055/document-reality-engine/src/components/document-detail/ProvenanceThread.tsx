import { AlertCircle, Building2, CheckCircle2, Quote, Stamp } from "lucide-react";
import clsx from "clsx";
import type { ProvenanceNode } from "../../domain/provenance";
import { formatDateTime } from "../../domain/utils";

const KIND_ICON: Record<ProvenanceNode["kind"], typeof Quote> = {
  claim: Quote,
  evidence: Stamp,
  source: Building2,
  verification: CheckCircle2,
};

const KIND_LABEL: Record<ProvenanceNode["kind"], string> = {
  claim: "Claim",
  evidence: "Evidence",
  source: "Source",
  verification: "Verification",
};

/**
 * Renders the chain a claim can be traced through. A present link is a
 * solid node with a solid connector; a missing link (no evidence, no named
 * source, not yet verified) is a hollow node with a dashed connector — the
 * chain visibly breaks instead of silently omitting the step.
 */
export function ProvenanceThread({ nodes }: { nodes: ProvenanceNode[] }) {
  return (
    <ol className="relative">
      {nodes.map((node, index) => {
        const isLast = index === nodes.length - 1;
        const Icon = node.present ? KIND_ICON[node.kind] : AlertCircle;
        return (
          <li key={`${node.kind}-${index}`} className="relative flex gap-3 pb-6 last:pb-0">
            {!isLast && (
              <span
                aria-hidden="true"
                className={clsx(
                  "absolute left-[13px] top-7 h-[calc(100%-1rem)] w-0 border-l-2",
                  node.present ? "border-line-strong" : "border-dashed border-critical/40",
                )}
              />
            )}
            <span
              className={clsx(
                "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2",
                node.present ? "border-trust bg-trust-soft text-trust" : "border-dashed border-critical/50 bg-critical-soft text-critical",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">{KIND_LABEL[node.kind]}</p>
              <p className="mt-0.5 text-sm font-medium text-text-primary">{node.title}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-text-tertiary">{node.detail}</p>
              {node.timestamp && <p className="font-numeric mt-1 text-[11px] text-text-tertiary">{formatDateTime(node.timestamp)}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
