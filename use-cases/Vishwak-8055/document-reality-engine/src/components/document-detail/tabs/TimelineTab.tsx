import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  Clock,
  FilePlus,
  History,
  ListTodo,
  MessageSquare,
  Paperclip,
  Pencil,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  UserPlus,
  XCircle,
  type LucideProps,
} from "lucide-react";
import type { ComponentType } from "react";
import type { ReviewEventType, SDDocument } from "../../../types/domain";
import { formatDateTime } from "../../../domain/utils";
import { EmptyState } from "../../ui/EmptyState";

const EVENT_ICON: Record<ReviewEventType, ComponentType<LucideProps>> = {
  "Document Created": FilePlus,
  "Evidence Attached": Paperclip,
  "Claim Verified": CheckCircle2,
  "Claim Contradicted": XCircle,
  "Requirement Failed": AlertTriangle,
  "Requirement Satisfied": ShieldCheck,
  "Reviewer Assigned": UserPlus,
  "Comment Added": MessageSquare,
  "Content Changed": Pencil,
  "Risk Recalculated": RefreshCw,
  "Evidence Marked Stale": Clock,
  "Approval Requested": Send,
  "Approval Granted": BadgeCheck,
  "Changes Requested": RotateCcw,
  "Finding Resolved": CheckCircle2,
  "Action Assigned": ListTodo,
  "Action Completed": CheckCircle2,
};

export function TimelineTab({ document }: { document: SDDocument }) {
  const events = [...document.reviewEvents].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  if (events.length === 0) {
    return <EmptyState icon={History} title="No audit history yet" description="Events will appear here as this document is reviewed and changed." />;
  }

  return (
    <ol className="relative">
      {events.map((event, index) => {
        const isLast = index === events.length - 1;
        const Icon = EVENT_ICON[event.type];
        return (
          <li key={event.id} className="relative flex gap-3 pb-6 last:pb-0">
            {!isLast && <span aria-hidden="true" className="absolute left-[13px] top-7 h-[calc(100%-1rem)] w-0 border-l-2 border-line-strong" />}
            <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 border-trust bg-trust-soft text-trust">
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-x-2">
                <p className="text-sm font-medium text-text-primary">{event.type}</p>
                <span className="font-numeric text-xs text-text-tertiary">{formatDateTime(event.timestamp)}</span>
              </div>
              <p className="mt-0.5 text-sm text-text-secondary">{event.explanation}</p>
              <p className="mt-0.5 text-xs text-text-tertiary">{event.actor}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
