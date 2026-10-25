"use client";

import { useQuery } from "@tanstack/react-query";
import { getProjectSubmittals, getOverdueSubmittals } from "@/lib/api/submittals";
import { StatCard } from "@/components/dashboard/StatCard";
import { RegisterStatusBadge, TechnicalStatusBadge } from "@/components/ui/Badge";
import { SkeletonStatCard, Skeleton } from "@/components/ui/Skeleton";
import { AlertTriangle, ArrowRight, RefreshCcw } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";

const PROJECT_NAMES: Record<string, string> = {
  "BROD-2026": "Bristol Office Development",
};

export default function ProjectPage({ params }: { params: { projectId: string } }) {
  const { projectId } = params;
  const name = PROJECT_NAMES[projectId] ?? projectId;

  const { data: register, isLoading, isError, refetch } = useQuery({
    queryKey: ["register", projectId],
    queryFn: () => getProjectSubmittals(projectId),
  });
  const { data: overdue } = useQuery({
    queryKey: ["overdue", projectId],
    queryFn: () => getOverdueSubmittals(projectId),
  });

  const items = register?.items ?? [];
  const total = items.length;
  const underReview = items.filter((i) => i.register_status === "UNDER_REVIEW").length;
  const reviewed = items.filter((i) => i.register_status === "REVIEWED").length;
  const notReceived = items.filter((i) => i.register_status === "NOT_RECEIVED").length;
  const overdueCount = overdue?.overdue_count ?? 0;

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load project</h2>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Project</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">{name}</h1>
          <p className="text-sm font-mono text-slate-500">{projectId}</p>
        </div>
        <Link href={`/projects/${projectId}/submittals`}>
          <Button size="sm">
            View Register <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </Link>
      </div>

      {/* Stats */}
      <section aria-label="Project statistics">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          {isLoading ? (
            Array.from({ length: 5 }).map((_, i) => <SkeletonStatCard key={i} />)
          ) : (
            <>
              <StatCard label="Total" value={total} />
              <StatCard label="Not Received" value={notReceived} />
              <StatCard label="Under Review" value={underReview} variant="warning" />
              <StatCard label="Reviewed" value={reviewed} variant="success" />
              <StatCard label="Overdue" value={overdueCount} variant={overdueCount > 0 ? "danger" : "default"} />
            </>
          )}
        </div>
      </section>

      {/* Register preview */}
      <section aria-labelledby="register-preview-heading">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="register-preview-heading" className="text-sm font-semibold text-slate-700">
            Submittal Register
          </h2>
          <Link
            href={`/projects/${projectId}/submittals`}
            className="flex items-center gap-1 text-xs text-blue-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
          >
            View all <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          {isLoading ? (
            <div className="divide-y divide-slate-100">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 px-4 py-3">
                  <Skeleton className="h-4 w-14" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-5 w-24 rounded-full" />
                  <Skeleton className="h-5 w-20 rounded-full" />
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-slate-500">
              No submittals in the register yet.
            </div>
          ) : (
            <ul className="divide-y divide-slate-100" role="list">
              {items.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/projects/${projectId}/submittals/${item.number}`}
                    className="flex items-center gap-4 px-4 py-3 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50"
                  >
                    <span className="w-14 shrink-0 font-mono text-xs font-medium text-slate-500">
                      {item.number}
                    </span>
                    <span className="flex-1 min-w-0 text-sm text-slate-800 truncate">
                      {item.title}
                    </span>
                    <span className="hidden text-xs text-slate-400 sm:block">{item.specification_section}</span>
                    <RegisterStatusBadge status={item.register_status} />
                    <TechnicalStatusBadge status={item.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
