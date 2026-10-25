"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  getProjectSubmittals,
} from "@/lib/api/submittals";
import { StatCard } from "@/components/dashboard/StatCard";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  AlertTriangle,
  RefreshCcw,
  Clock,
  FileStack,
  SendHorizonal,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";

export default function OverviewPage() {
  const {
    data: register,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["register", PROJECT_ID],
    queryFn: () => getProjectSubmittals(PROJECT_ID),
  });

  const items = register?.items ?? [];

  const totalItems = items.length;
  const awaitingReview = items.filter(
    (i) => i.register_status === "NOT_RECEIVED" || i.register_status === "RECEIVED",
  ).length;
  const deviations = items.filter(
    (i) => i.status === "REVIEWED_DEVIATION",
  ).length;
  const overdue = items.filter((i) => i.register_status === "OVERDUE").length;

  // Items needing attention
  const needsAttention = [
    ...items
      .filter((i) => i.register_status === "OVERDUE")
      .map((i) => ({
        id: i.id,
        number: i.number,
        title: i.title,
        reason: "Overdue — action required",
        href: `/projects/${PROJECT_ID}/submittals/${i.number}`,
        variant: "danger" as const,
      })),
    ...items
      .filter((i) => i.status === "REVIEWED_DEVIATION")
      .map((i) => ({
        id: i.id,
        number: i.number,
        title: i.title,
        reason: "Specification deviation detected",
        href: `/projects/${PROJECT_ID}/submittals/${i.number}`,
        variant: "warning" as const,
      })),
  ].slice(0, 6);

  // Recent activity (last 5 items by created_at)
  const recentActivity = [...items]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5);

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load register</h2>
        <p className="text-sm text-slate-500">
          Ensure the backend is running and the demo dataset is seeded.
        </p>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Overview</h1>
          <p className="mt-1 text-sm text-slate-500">
            {PROJECT_NAME} · {PROJECT_ID}
          </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading ? (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
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
              value={totalItems}
              description="All items in register"
            />
            <StatCard
              label="Awaiting Review"
              value={awaitingReview}
              description="Not yet started"
            />
            <StatCard
              label="Deviations"
              value={deviations}
              variant={deviations > 0 ? "warning" : "default"}
              description="Specification non-compliance"
            />
            <StatCard
              label="Overdue"
              value={overdue}
              variant={overdue > 0 ? "danger" : "default"}
              description="Past required date"
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        {/* Needs Attention */}
        <section aria-labelledby="attention-heading">
          <h2
            id="attention-heading"
            className="mb-3 text-sm font-semibold text-slate-700"
          >
            Needs Attention
          </h2>
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            {isLoading ? (
              <div className="divide-y divide-slate-100 p-4 space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-8 w-8 rounded-full" />
                    <div className="flex-1 space-y-1">
                      <Skeleton className="h-4 w-40" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                  </div>
                ))}
              </div>
            ) : needsAttention.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <CheckCircle2 className="mx-auto h-8 w-8 text-green-500" aria-hidden />
                <p className="mt-2 text-sm font-medium text-slate-600">
                  All clear
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  No items currently need your attention.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100" role="list">
                {needsAttention.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={item.href}
                      className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50"
                    >
                      <div
                        className={cn(
                          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                          item.variant === "danger"
                            ? "bg-red-100 text-red-700"
                            : "bg-amber-100 text-amber-700",
                        )}
                      >
                        {item.variant === "danger" ? (
                          <AlertCircle className="h-4 w-4" aria-hidden />
                        ) : (
                          <AlertTriangle className="h-4 w-4" aria-hidden />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-800 truncate">
                          {item.number} — {item.title}
                        </p>
                        <p
                          className={cn(
                            "mt-0.5 text-xs font-medium",
                            item.variant === "danger"
                              ? "text-red-600"
                              : "text-amber-600",
                          )}
                        >
                          {item.reason}
                        </p>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 mt-2" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Recent Activity */}
        <section aria-labelledby="activity-heading">
          <h2
            id="activity-heading"
            className="mb-3 text-sm font-semibold text-slate-700"
          >
            Recent Activity
          </h2>
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            {isLoading ? (
              <div className="divide-y divide-slate-100 p-4 space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-4 w-20" />
                    <Skeleton className="h-4 flex-1" />
                    <Skeleton className="h-4 w-16" />
                  </div>
                ))}
              </div>
            ) : recentActivity.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <FileStack className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
                <p className="mt-2 text-sm font-medium text-slate-600">
                  No activity yet
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100" role="list">
                {recentActivity.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={`/projects/${PROJECT_ID}/submittals/${item.number}`}
                      className="flex items-center gap-4 px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-800 truncate">
                          {item.number} — {item.title}
                        </p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {item.specification_section}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                          item.register_status === "OVERDUE"
                            ? "bg-red-50 text-red-700"
                            : item.register_status === "REVIEWED"
                              ? "bg-green-50 text-green-700"
                              : "bg-slate-100 text-slate-600",
                        )}
                      >
                        {item.register_status.replace("_", " ").toLowerCase()}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      {/* Quick Links */}
      <section aria-labelledby="quick-links-heading">
        <h2
          id="quick-links-heading"
          className="mb-3 text-sm font-semibold text-slate-700"
        >
          Quick Links
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Link
            href="/register"
            className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <FileStack className="h-5 w-5 text-slate-400" aria-hidden />
            <div>
              <p className="text-sm font-medium text-slate-800">Submittal Register</p>
              <p className="text-xs text-slate-500">View and manage all submittals</p>
            </div>
          </Link>
          <Link
            href="/transmittals"
            className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <SendHorizonal className="h-5 w-5 text-slate-400" aria-hidden />
            <div>
              <p className="text-sm font-medium text-slate-800">Transmittals</p>
              <p className="text-xs text-slate-500">Packet exports and status</p>
            </div>
          </Link>
          <Link
            href="/reports"
            className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <Clock className="h-5 w-5 text-slate-400" aria-hidden />
            <div>
              <p className="text-sm font-medium text-slate-800">Reports</p>
              <p className="text-xs text-slate-500">Overdue and status reports</p>
            </div>
          </Link>
        </div>
      </section>
    </div>
  );
}
