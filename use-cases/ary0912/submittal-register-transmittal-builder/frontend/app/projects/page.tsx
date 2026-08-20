"use client";

import { useQuery } from "@tanstack/react-query";
import { getProjectSubmittals, getOverdueSubmittals } from "@/lib/api/submittals";
import { StatCard } from "@/components/dashboard/StatCard";
import { SkeletonStatCard } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { AlertTriangle, ArrowRight, FolderKanban } from "lucide-react";
import Link from "next/link";
import { PROJECT_ID, PROJECT_NAME } from "@/lib/constants";

// The backend currently supports one project. The UI is structured
// to support multiple projects in the future.
const PROJECTS = [{ id: PROJECT_ID, name: PROJECT_NAME }];

function ProjectCard({ id, name }: { id: string; name: string }) {
  const { data: register, isLoading, isError, refetch } = useQuery({
    queryKey: ["register", id],
    queryFn: () => getProjectSubmittals(id),
  });
  const { data: overdue } = useQuery({
    queryKey: ["overdue", id],
    queryFn: () => getOverdueSubmittals(id),
  });

  const total = register?.items.length ?? 0;
  const underReview = register?.items.filter((i) => i.register_status === "UNDER_REVIEW").length ?? 0;
  const reviewed = register?.items.filter((i) => i.register_status === "REVIEWED").length ?? 0;
  const overdueCount = overdue?.overdue_count ?? 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <FolderKanban className="h-4 w-4 text-blue-600" aria-hidden />
            <h2 className="text-base font-semibold text-slate-900">{name}</h2>
          </div>
          <p className="mt-0.5 text-sm text-slate-500 font-mono">{id}</p>
        </div>
        <Link href={`/projects/${id}/submittals`}>
          <Button variant="secondary" size="sm">
            Open Register <ArrowRight className="h-3 w-3" aria-hidden />
          </Button>
        </Link>
      </div>

      {isError ? (
        <div className="flex items-center gap-2 text-sm text-red-600">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <span>Failed to load register data.</span>
          <button
            onClick={() => refetch()}
            className="ml-1 underline hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
          >
            Retry
          </button>
        </div>
      ) : isLoading ? (
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonStatCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total" value={total} />
          <StatCard label="Under Review" value={underReview} variant="warning" />
          <StatCard label="Reviewed" value={reviewed} variant="success" />
          <StatCard label="Overdue" value={overdueCount} variant={overdueCount > 0 ? "danger" : "default"} />
        </div>
      )}

      <div className="flex gap-3 pt-1 border-t border-slate-100">
        <Link
          href={`/projects/${id}/submittals`}
          className="text-sm text-blue-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          View Submittal Register
        </Link>
        <span className="text-slate-300">·</span>
        <Link
          href={`/transmittals`}
          className="text-sm text-blue-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          View Transmittals
        </Link>
      </div>
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
        <p className="mt-1 text-sm text-slate-500">
          Overview of active construction projects and their submittal registers.
        </p>
      </div>

      <div className="space-y-4">
        {PROJECTS.map((p) => (
          <ProjectCard key={p.id} id={p.id} name={p.name} />
        ))}
      </div>
    </div>
  );
}
