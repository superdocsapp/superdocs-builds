import type { ProposedChange } from "@/lib/api/types";
import { Button } from "@/components/ui/Button";

interface ChangeCardProps {
  change: ProposedChange;
  index: number;
  onApprove: (changeId: string | undefined) => void;
  onReject: (changeId: string | undefined) => void;
  approving: boolean;
  rejecting: boolean;
}

export function ChangeCard({ change, index, onApprove, onReject, approving, rejecting }: ChangeCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-3 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-700">Proposed Change {index + 1}</p>
        {change.change_id && (
          <span className="font-mono text-xs text-slate-400">{change.change_id}</span>
        )}
      </div>
      <div className="px-5 py-4 space-y-3">
        {change.description && (
          <p className="text-sm text-slate-700">{change.description}</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          {change.original !== undefined && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Original</p>
              <div className="rounded-md bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-800 font-mono">
                {String(change.original)}
              </div>
            </div>
          )}
          {change.proposed !== undefined && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Proposed</p>
              <div className="rounded-md bg-green-50 border border-green-100 px-3 py-2 text-sm text-green-800 font-mono">
                {String(change.proposed)}
              </div>
            </div>
          )}
        </div>
        {change.reason && (
          <p className="text-xs text-slate-500 italic">{change.reason}</p>
        )}
        {/* Raw data if no structured fields */}
        {change.original === undefined && change.proposed === undefined && !change.description && (
          <pre className="rounded-md bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-700 overflow-auto">
            {JSON.stringify(change, null, 2)}
          </pre>
        )}
      </div>
      <div className="border-t border-slate-100 px-5 py-3 flex justify-end gap-2">
        <Button
          variant="secondary"
          size="sm"
          loading={rejecting}
          disabled={approving}
          onClick={() => onReject(change.change_id)}
        >
          Reject
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={approving}
          disabled={rejecting}
          onClick={() => onApprove(change.change_id)}
        >
          Approve
        </Button>
      </div>
    </div>
  );
}
