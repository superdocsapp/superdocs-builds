"use client";

import { useQuery } from "@tanstack/react-query";
import { getOverdueSubmittals } from "@/lib/api/submittals";
import { RegisterStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertTriangle, ArrowRight, CheckCircle2, RefreshCcw } from "lucide-react";
import Link from "next/link";
import { formatDate, daysUntil } from "@/lib/utils";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";

export default function OverduePage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["overdue", PROJECT_ID],
    queryFn: () => getOverdueSubmittals(PROJECT_ID),
  });

  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric",
  });

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load overdue report</h2>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
            {PROJECT_NAME} · {PROJECT_ID}
          </p>
          <h1 className="mt-0.5 text-xl font-semibold text-slate-900">Overdue Submittals</h1>
          <p className="mt-1 text-sm text-slate-500">
            Submittals that have passed their due date and have not been reviewed.
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-400">Report date</p>
          <p className="text-sm font-medium text-slate-700">{today}</p>
          {!isLoading && (
            <p className="text-xs text-slate-500 mt-0.5">
              {data?.overdue_count ?? 0} overdue item{data?.overdue_count !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        {isLoading ? (
          <div className="divide-y divide-slate-100">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-4">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="px-5 py-16 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-green-400" aria-hidden />
            <p className="mt-3 text-sm font-medium text-green-700">No overdue submittals</p>
            <p className="mt-1 text-xs text-slate-500">
              All submittals are within their due dates.
            </p>
          </div>
        ) : (
          <>
            {/* Table header */}
            <div className="border-b border-slate-200 bg-slate-50 grid grid-cols-[80px_1fr_140px_120px_100px_40px] px-5 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>Number</span>
              <span>Title</span>
              <span>Required By</span>
              <span>Due Date</span>
              <span>Status</span>
              <span></span>
            </div>
            <ul className="divide-y divide-slate-100" role="list">
              {items.map((item) => {
                const days = daysUntil(item.due_date);
                const daysOverdue = days !== null ? Math.abs(days) : null;
                return (
                  <li key={item.id}>
                    <Link
                      href={`/projects/${PROJECT_ID}/submittals/${item.number}`}
                      className="grid grid-cols-[80px_1fr_140px_120px_100px_40px] items-center px-5 py-3.5 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50 group"
                    >
                      <span className="font-mono text-xs font-semibold text-slate-600">
                        {item.number}
                      </span>
                      <div className="min-w-0 pr-4">
                        <p className="text-sm font-medium text-slate-800 truncate">{item.title}</p>
                        <p className="text-xs text-slate-400 font-mono">{item.specification_section}</p>
                      </div>
                      <span className="text-xs text-slate-500 truncate pr-3">
                        {item.required_by ?? "—"}
                      </span>
                      <div>
                        <p className="text-xs font-medium text-red-600">
                          {formatDate(item.due_date)}
                        </p>
                        {daysOverdue !== null && (
                          <p className="text-[10px] text-red-500">
                            {daysOverdue} day{daysOverdue !== 1 ? "s" : ""} overdue
                          </p>
                        )}
                      </div>
                      <RegisterStatusBadge status={item.register_status} />
                      <ArrowRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-slate-500 justify-self-end" aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {items.length > 0 && (
        <p className="text-xs text-slate-400 print:hidden">
          Click any item to open its detail page and update the status.
        </p>
      )}
    </div>
  );
}
