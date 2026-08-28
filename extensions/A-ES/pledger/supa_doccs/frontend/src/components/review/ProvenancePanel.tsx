import type { QueueItem } from "@/types/review";

interface ProvenancePanelProps {
  item: QueueItem;
}

const ESCALATION_REASON_LABELS: Record<string, string> = {
  non_compliant_verdict: "Non-compliant verdict",
  low_confidence: "Low confidence",
  flagged_for_human_review: "Flagged for human review",
  permanent_error_escalation: "Permanent-error escalation",
  no_verdict_recorded: "No verdict recorded (safety escalation)",
  unclassified: "Unclassified (safety escalation)",
};

function shortId(id: unknown): string | null {
  if (typeof id !== "string" || !id) return null;
  return id.length > 8 ? id.slice(0, 8) : id;
}

/**
 * Renders the provenance fields the pipeline already computed but that
 * were previously invisible to reviewers:
 * - confidence score vs the threshold it was compared against
 * - why the item reached the human queue (escalation reason)
 * - retry counts per node
 * - the actual playbook rule text a finding was checked against
 *
 * Pure rendering: every value arrives via the enriched queue payload.
 */
export function ProvenancePanel({ item }: ProvenancePanelProps) {
  const details = item.payload.details ?? {};
  const hasConfidence =
    details.confidence !== undefined &&
    details.confidence !== null &&
    details.confidence !== "";
  const hasThreshold =
    details.confidence_threshold !== undefined &&
    details.confidence_threshold !== null;
  const reason =
    typeof details.escalation_reason === "string"
      ? details.escalation_reason
      : null;
  const retries =
    details.retries && typeof details.retries === "object"
      ? Object.entries(details.retries as Record<string, unknown>).filter(
          ([, count]) => typeof count === "number" && count > 0
        )
      : [];
  const ruleText =
    typeof details.rule_description === "string"
      ? details.rule_description
      : null;
  const ruleCheck =
    typeof details.rule_check_description === "string"
      ? details.rule_check_description
      : null;

  if (
    !hasConfidence &&
    !hasThreshold &&
    !reason &&
    retries.length === 0 &&
    !ruleText
  ) {
    return null;
  }

  return (
    <section aria-label="Provenance">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-white/40">
        Provenance
      </h3>
      <div className="space-y-2 rounded-lg border border-white/[0.06] bg-surface-card p-3 text-sm">
        {(hasConfidence || hasThreshold) && (
          <div className="flex gap-2 items-baseline">
            <span className="font-mono text-white/30 text-xs">confidence:</span>
            <span className="text-white/70">
              {hasConfidence ? Number(details.confidence).toFixed(2) : "—"}
              {hasThreshold && (
                <span className="text-white/40">
                  {" "}
                  / threshold {Number(details.confidence_threshold).toFixed(2)}
                </span>
              )}
              {hasConfidence && hasThreshold && (
                <span
                  className={`ml-2 text-xs ${
                    Number(details.confidence) <
                    Number(details.confidence_threshold)
                      ? "text-amber-300"
                      : "text-emerald-400"
                  }`}
                >
                  {Number(details.confidence) <
                  Number(details.confidence_threshold)
                    ? "below threshold"
                    : "at or above threshold"}
                </span>
              )}
            </span>
          </div>
        )}

        {reason && (
          <div className="flex gap-2 items-baseline">
            <span className="font-mono text-white/30 text-xs">
              escalated:
            </span>
            <span className="text-white/70">
              {ESCALATION_REASON_LABELS[reason] ?? reason}
            </span>
          </div>
        )}

        {retries.length > 0 && (
          <div className="flex gap-2 items-baseline">
            <span className="font-mono text-white/30 text-xs">retries:</span>
            <span className="font-mono text-xs text-amber-300/90">
              {retries.map(([node, count]) => `${node} ×${count}`).join(", ")}
            </span>
          </div>
        )}

        {details.playbook_id != null && (
          <div className="flex gap-2 items-baseline">
            <span className="font-mono text-white/30 text-xs">playbook:</span>
            <span className="text-white/70">{String(details.playbook_id)}</span>
          </div>
        )}

        {(ruleText || ruleCheck) && (
          <div className="pt-1">
            <span className="font-mono text-white/30 text-xs block mb-1">
              rule {typeof details.rule_id === "string" ? shortId(details.rule_id) ?? details.rule_id : ""}:
            </span>
            <blockquote className="rounded border-l-2 border-indigo-500/40 bg-indigo-500/[0.04] px-3 py-1.5 text-xs leading-relaxed text-white/70">
              {ruleText}
              {ruleCheck && (
                <span className="block mt-1 text-white/45 italic">
                  {ruleCheck}
                </span>
              )}
            </blockquote>
          </div>
        )}
      </div>
    </section>
  );
}
