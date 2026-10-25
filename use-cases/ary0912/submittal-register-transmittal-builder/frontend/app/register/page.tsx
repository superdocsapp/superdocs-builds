"use client";

import { useQuery } from "@tanstack/react-query";
import { getProjectSubmittals, getOverdueSubmittals } from "@/lib/api/submittals";
import { RegisterStatusBadge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpDown,
  RefreshCcw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useMemo } from "react";
import { formatDate, daysUntil } from "@/lib/utils";
import { PROJECT_ID } from "@/lib/constants";
import type { RegisterItem, RegisterStatus } from "@/lib/api/types";

type SortField = "number" | "title" | "specification_section" | "due_date" | "register_status";
type SortDir = "asc" | "desc";

function sortItems(items: RegisterItem[], field: SortField, dir: SortDir) {
  return [...items].sort((a, b) => {
    const va = String(a[field] ?? "");
    const vb = String(b[field] ?? "");
    const cmp = va.localeCompare(vb, undefined, { numeric: true });
    return dir === "asc" ? cmp : -cmp;
  });
}

function StatPill({
  label,
  value,
  active,
  onClick,
  color,
}: {
  label: string;
  value: number | string;
  active?: boolean;
  onClick?: () => void;
  color?: "default" | "amber" | "green" | "red";
}) {
  const colorClass = {
    default: active ? "bg-slate-800 text-white" : "bg-white text-slate-700 border-slate-200",
    amber: active ? "bg-amber-600 text-white" : "bg-amber-50 text-amber-700 border-amber-200",
    green: active ? "bg-green-600 text-white" : "bg-green-50 text-green-700 border-green-200",
    red: active ? "bg-red-600 text-white" : "bg-red-50 text-red-700 border-red-200",
  }[color ?? "default"];

  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${colorClass}`}
      aria-pressed={active}
    >
      <span className="tabular-nums font-semibold text-sm">{value}</span>
      <span className="opacity-75">{label}</span>
    </button>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RegisterStatus | "ALL">("ALL");
  const [specFilter, setSpecFilter] = useState<string>("ALL");
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: "number",
    dir: "asc",
  });

  const { data: register, isLoading, isError, refetch } = useQuery({
    queryKey: ["register", PROJECT_ID],
    queryFn: () => getProjectSubmittals(PROJECT_ID),
  });

  const { data: overdueData } = useQuery({
    queryKey: ["overdue", PROJECT_ID],
    queryFn: () => getOverdueSubmittals(PROJECT_ID),
    enabled: !!register,
  });

  const items = useMemo(() => register?.items ?? [], [register]);

  const stats = useMemo(() => ({
    total: items.length,
    notReceived: items.filter((i) => i.register_status === "NOT_RECEIVED").length,
    received: items.filter((i) => i.register_status === "RECEIVED").length,
    underReview: items.filter((i) => i.register_status === "UNDER_REVIEW").length,
    reviewed: items.filter((i) => i.register_status === "REVIEWED").length,
    overdue: overdueData?.overdue_count ?? items.filter((i) => i.register_status === "OVERDUE").length,
  }), [items, overdueData]);

  const specSections = useMemo(
    () => Array.from(new Set(items.map((i) => i.specification_section))).sort(),
    [items],
  );

  const filtered = useMemo(() => {
    let list = items;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (i) =>
          i.number.toLowerCase().includes(q) ||
          i.title.toLowerCase().includes(q) ||
          i.specification_section.toLowerCase().includes(q) ||
          (i.required_by ?? "").toLowerCase().includes(q) ||
          (i.required_form ?? "").toLowerCase().includes(q),
      );
    }
    if (statusFilter !== "ALL") list = list.filter((i) => i.register_status === statusFilter);
    if (specFilter !== "ALL") list = list.filter((i) => i.specification_section === specFilter);
    return sortItems(list, sort.field, sort.dir);
  }, [items, search, statusFilter, specFilter, sort]);

  function toggleSort(field: SortField) {
    setSort((prev) =>
      prev.field === field
        ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { field, dir: "asc" },
    );
  }

  const hasFilters = search || statusFilter !== "ALL" || specFilter !== "ALL";

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold text-slate-900">
          Couldn&apos;t load the submittal register
        </h2>
        <p className="text-sm text-slate-500">
          Check that the backend is running and try again.
        </p>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="border-b border-slate-200 bg-white px-6 pt-5 pb-0">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
              Bristol Office Development · BROD-2026
            </p>
            <h1 className="mt-0.5 text-xl font-semibold text-slate-900">
              Submittal Register
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">
              Track required submissions, review incoming documents, and prepare transmittal packets.
            </p>
          </div>
          {stats.overdue > 0 && (
            <Link
              href="/reports"
              className="flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              {stats.overdue} overdue
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          )}
        </div>

        {/* Stat pills — act as status filters */}
        <div className="flex flex-wrap gap-2 pb-3">
          {isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-8 w-24 animate-pulse rounded-md bg-slate-100" />
            ))
          ) : (
            <>
              <StatPill
                label="Total"
                value={stats.total}
                active={statusFilter === "ALL"}
                onClick={() => setStatusFilter("ALL")}
              />
              <StatPill
                label="Not received"
                value={stats.notReceived}
                active={statusFilter === "NOT_RECEIVED"}
                onClick={() => setStatusFilter(statusFilter === "NOT_RECEIVED" ? "ALL" : "NOT_RECEIVED")}
              />
              <StatPill
                label="Received"
                value={stats.received}
                active={statusFilter === "RECEIVED"}
                onClick={() => setStatusFilter(statusFilter === "RECEIVED" ? "ALL" : "RECEIVED")}
                color="default"
              />
              <StatPill
                label="Under review"
                value={stats.underReview}
                active={statusFilter === "UNDER_REVIEW"}
                onClick={() => setStatusFilter(statusFilter === "UNDER_REVIEW" ? "ALL" : "UNDER_REVIEW")}
                color="amber"
              />
              <StatPill
                label="Reviewed"
                value={stats.reviewed}
                active={statusFilter === "REVIEWED"}
                onClick={() => setStatusFilter(statusFilter === "REVIEWED" ? "ALL" : "REVIEWED")}
                color="green"
              />
              <StatPill
                label="Overdue"
                value={stats.overdue}
                active={statusFilter === "OVERDUE"}
                onClick={() => setStatusFilter(statusFilter === "OVERDUE" ? "ALL" : "OVERDUE")}
                color="red"
              />
            </>
          )}
        </div>

        {/* Search + filters row */}
        <div className="flex flex-wrap gap-2 items-center border-t border-slate-100 py-2.5">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
            <input
              type="search"
              placeholder="Search number, title, spec, contractor…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 rounded-md border border-slate-300 bg-white pl-8 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 w-72"
              aria-label="Search submittals"
            />
          </div>

          {specSections.length > 1 && (
            <select
              value={specFilter}
              onChange={(e) => setSpecFilter(e.target.value)}
              className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              aria-label="Filter by specification section"
            >
              <option value="ALL">All spec sections</option>
              {specSections.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}

          {hasFilters && (
            <button
              onClick={() => { setSearch(""); setStatusFilter("ALL"); setSpecFilter("ALL"); }}
              className="flex items-center gap-1 h-8 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <X className="h-3 w-3" aria-hidden /> Clear filters
            </button>
          )}

          {!isLoading && (
            <p className="ml-auto text-xs text-slate-400">
              {filtered.length} of {items.length} items
            </p>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm" aria-label="Submittal register">
          <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-200">
            <tr>
              {(
                [
                  { field: "number" as SortField, label: "Number", width: "w-24" },
                  { field: "title" as SortField, label: "Title", width: "min-w-[180px]" },
                  { field: "specification_section" as SortField, label: "Spec", width: "w-24" },
                  { field: null, label: "Revision", width: "w-20" },
                  { field: null, label: "Required By", width: "w-44" },
                  { field: null, label: "Required Form", width: "w-44" },
                  { field: "due_date" as SortField, label: "Due Date", width: "w-28" },
                  { field: "register_status" as SortField, label: "Status", width: "w-32" },
                  { field: null, label: "", width: "w-12" },
                ] as const
              ).map(({ field, label, width }) => (
                <th
                  key={label || "action"}
                  className={`px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 ${width}`}
                >
                  {field ? (
                    <button
                      onClick={() => toggleSort(field)}
                      className="flex items-center gap-1 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                    >
                      {label}
                      <ArrowUpDown
                        className={`h-3 w-3 ${sort.field === field ? "text-blue-600" : "text-slate-300"}`}
                        aria-hidden
                      />
                    </button>
                  ) : (
                    label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 9 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-16 text-center text-sm text-slate-500">
                  {hasFilters
                    ? "No submittals match the current filters."
                    : "No submittals have been added to this register yet."}
                </td>
              </tr>
            ) : (
              filtered.map((item) => {
                const days = daysUntil(item.due_date);
                const isOverdue = item.register_status === "OVERDUE";
                return (
                  <tr
                    key={item.id}
                    className="hover:bg-slate-50 transition-colors cursor-pointer"
                    onClick={() =>
                      router.push(`/projects/${PROJECT_ID}/submittals/${item.number}`)
                    }
                  >
                    <td className="px-4 py-3 font-mono text-xs font-semibold text-slate-600">
                      {item.number}
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      <Link
                        href={`/projects/BROD-2026/submittals/${item.number}`}
                        className="hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {item.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {item.specification_section}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {item.specification_revision ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {item.required_by ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 max-w-[160px] truncate">
                      {item.required_form ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.due_date ? (
                        <span className={isOverdue ? "font-medium text-red-600" : "text-slate-500"}>
                          {formatDate(item.due_date)}
                          {isOverdue && days !== null && (
                            <span className="block text-[10px] text-red-500">
                              {Math.abs(days)}d overdue
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <RegisterStatusBadge status={item.register_status} />
                    </td>
                    <td className="px-4 py-3">
                      <ArrowRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-slate-500" aria-hidden />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
