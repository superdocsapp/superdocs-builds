"use client";

import { useQuery } from "@tanstack/react-query";
import { getProjectSubmittals } from "@/lib/api/submittals";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertTriangle, RefreshCcw, SendHorizonal } from "lucide-react";
import { Button } from "@/components/ui/Button";
import Link from "next/link";
import { formatDate } from "@/lib/utils";
import { PROJECT_ID } from "@/lib/constants";

export default function TransmittalsPage() {
  const { data: register, isLoading, isError, refetch } = useQuery({
    queryKey: ["register", PROJECT_ID],
    queryFn: () => getProjectSubmittals(PROJECT_ID),
  });

  // Collect all submittals that have a transmittal
  const transmittals = register?.items
    .filter((item) => item.finding_count > 0) ?? [];

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load transmittals</h2>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Transmittals</h1>
        <p className="mt-1 text-sm text-slate-500">
          Transmittal packets generated from reviewed submittal findings.
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        {isLoading ? (
          <div className="divide-y divide-slate-100">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-5 w-28 rounded-full" />
              </div>
            ))}
          </div>
        ) : transmittals.length === 0 ? (
          <div className="px-5 py-16 text-center">
            <SendHorizonal className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
            <p className="mt-3 text-sm font-medium text-slate-600">No transmittals yet</p>
            <p className="mt-1 text-xs text-slate-400">
              Complete all findings review on a submittal to create a transmittal.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100" role="list">
            {transmittals.map((item) => (
              <li key={item.id}>
                <Link
                  href={`/projects/${PROJECT_ID}/submittals/${item.number}`}
                  className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:bg-slate-50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">
                      TR-{item.number}
                    </p>
                    <p className="text-xs text-slate-500 truncate">{item.title}</p>
                  </div>
                  <span className="text-xs text-slate-400">{formatDate(item.created_at)}</span>
                  <span className="text-xs text-slate-400">{item.specification_section}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-xs text-slate-400">
        To view the full transmittal workflow, open a submittal and navigate to its transmittal.
      </p>
    </div>
  );
}
