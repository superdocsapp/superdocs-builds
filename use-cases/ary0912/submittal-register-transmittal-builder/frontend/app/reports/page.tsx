"use client";

import { useQuery } from "@tanstack/react-query";
import { getOverdueSubmittals, getProjectSubmittals } from "@/lib/api/submittals";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatCard } from "@/components/dashboard/StatCard";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clock,
  RefreshCcw,
} from "lucide-react";
import Link from "next/link";
import { formatDate, daysUntil } from "@/lib/utils";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";

export default function ReportsPage() {
  const { data: register, isLoading: registerLoading } = useQuery({
    queryKey: ["register", PROJECT_ID],
    queryFn: () => getProjectSubmittals(PROJECT_ID),
  });

  const {
    data: overdueData,
    isLoading: overdueLoading,
    isError: overdueError,
    refetch,
  } = useQuery({
    queryKey: ["overdue", PROJECT_ID],
    queryFn: () => getOverdueSubmittals(PROJECT_ID),
  });

  const items = register?.items ?? [];
  const overdueItems = overdueData?.items ?? [];

  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const overdueCount = overdueData?.overdue_count ?? 0;

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-8">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-slate-400" aria-hidden />
          <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {PROJECT_NAME} · {PROJECT_ID} · Report as of {today}
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {registerLoading ? (
          <>
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-lg border border-slate-200 bg-white p-5">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="mt-2 h-8 w-12" />
              </div>
            ))}
          </>
        ) : (
          <>
            <StatCard
              label="Total Submittals"
              value={items.length}
              description="All items in register"
            />
            <StatCard
              label="Overdue"
              value={overdueCount}
              variant={overdueCount > 0 ? "danger" : "default"}
              description="Past required date"
            />
            <StatCard
              label="Reviewed"
              value={items.filter((i) => i.register_status === "REVIEWED").length}
              variant="success"
              description="Completed review"
            />
          </>
        )}
      </div>

      {/* Overdue Table */}
      <section aria-labelledby="overdue-heading">
        <h2 id="overdue-heading" className="mb-3 text-sm font-semibold text-slate-700">
          Overdue Submittals
        </h2>
        <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          {overdueLoading ? (
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
          ) : overdueError ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <AlertTriangle className="h-8 w-8 text-amber-500" aria-hidden />
              <p className="text-sm text-slate-500">Failed to load overdue data</p>
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                <RefreshCcw className="h-3.5 w-3.5" aria-hidden /> Retry
              </Button>
            </div>
          ) : overdueItems.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <CheckCircle2 className="mx-auto h-10 w-10 text-green-400" aria-hidden />
              <p className="mt-3 text-sm font-medium text-green-700">
                No overdue submittals
              </p>
              <p className="mt-1 text-xs text-slate-500">
                All submittals are within their due dates.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-slate-100" role="list">
              {overdueItems.map((item) => {
                const days = daysUntil(item.due_date);
                const daysOverdue = days !== null ? Math.abs(days) : null;
                return (
                  <li key={item.id}>
                    <Link
                      href={`/projects/${PROJECT_ID}/submittals/${item.number}`}
                      className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50 group"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700">
                        <Clock className="h-4 w-4" aria-hidden />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-800">
                          {item.number} — {item.title}
                        </p>
                        <p className="text-xs text-slate-400 font-mono">
                          {item.specification_section} · Required by{" "}
                          {item.required_by ?? "—"}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-xs font-medium text-red-600">
                          {formatDate(item.due_date)}
                        </p>
                        {daysOverdue !== null && (
                          <p className="text-[10px] text-red-500">
                            {daysOverdue} day{daysOverdue !== 1 ? "s" : ""} overdue
                          </p>
                        )}
                      </div>
                      <ArrowRight
                        className="h-3.5 w-3.5 shrink-0 text-slate-300 group-hover:text-slate-500"
                        aria-hidden
                      />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      {overdueItems.length > 0 && (
        <p className="text-xs text-slate-400">
          Click any item to open its detail page and update the status.
        </p>
      )}
    </div>
  );
}
