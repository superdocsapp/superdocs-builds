import { Link } from "react-router-dom";
import { CheckCircle2, ChevronRight } from "lucide-react";
import type { AttentionItem } from "../../domain/attention";
import { Badge, riskLevelTone } from "../ui/Badge";
import { EmptyState } from "../ui/EmptyState";

export function AttentionList({ items, limit = 12 }: { items: AttentionItem[]; limit?: number }) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="Nothing needs attention"
        description="Every open finding across the workspace has been resolved or is within policy."
      />
    );
  }

  const visible = items.slice(0, limit);

  return (
    <div>
      <ul className="divide-y divide-line rounded-md border border-line bg-paper-0">
        {visible.map((item) => (
          <li key={item.id}>
            <Link to={item.navigateTo} className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-paper-50">
              <Badge tone={riskLevelTone(item.severity)} className="mt-0.5 shrink-0">
                {item.severity}
              </Badge>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-text-primary">{item.title}</p>
                <p className="mt-0.5 truncate text-xs text-text-tertiary">
                  {item.kind} · {item.documentTitle}
                </p>
              </div>
              <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
      {items.length > limit && <p className="mt-2 text-xs text-text-tertiary">+{items.length - limit} more across the workspace.</p>}
    </div>
  );
}
