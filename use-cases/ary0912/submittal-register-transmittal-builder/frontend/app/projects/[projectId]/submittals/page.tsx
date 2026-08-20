"use client";

import { useQuery } from "@tanstack/react-query";
import { getProjectSubmittals } from "@/lib/api/submittals";
import { RegisterStatusBadge, TechnicalStatusBadge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import {
  AlertTriangle,
  ArrowUpDown,
  RefreshCcw,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useMemo } from "react";
import { formatDate, daysUntil } from "@/lib/utils";
import type { RegisterItem, RegisterStatus } from "@/lib/api/types";

const REGISTER_STATUSES: RegisterStatus[] = [
  "NOT_RECEIVED",
  "RECEIVED",
  "UNDER_REVIEW",
  "REVIEWED",
  "OVERDUE",
];

const REGISTER_STATUS_LABELS: Record<RegisterStatus, string> = {
  NOT_RECEIVED: "Not Received",
  RECEIVED: "Received",
  UNDER_REVIEW: "Under Review",
  REVIEWED: "Reviewed",
  OVERDUE: "Overdue",
};

type SortField = "number" | "title" | "specification_section" | "due_date" | "register_status";
type SortDir = "asc" | "desc";

function sortItems(items: RegisterItem[], field: SortField, dir: SortDir): RegisterItem[] {
  return [...items].sort((a, b) => {
    const va: string = String(a[field] ?? "");
    const vb: string = String(b[field] ?? "");
    const cmp = va.localeCompare(vb, undefined, { numeric: true });
    return dir === "asc" ? cmp : -cmp;
  });
}

export default function SubmittalRegisterPage({
  params,
}: {
  params: { projectId: string };
}) {
  const { projectId } = params;
  const router = useRouter();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RegisterStatus | "ALL">("ALL");
  const [specFilter, setSpecFilter] = useState<string>("ALL");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: "number",
    dir: "asc",
  });

  const { data: register, isLoading, isError, refetch } = useQuery({
    queryKey: ["register", projectId],
    queryFn: () => getProjectSubmittals(projectId),
  });

  const specSections = useMemo(() => {
    if (!register) return [];
    return Array.from(new Set(register.items.map((i) => i.specification_section))).sort();
  }, [register]);

  const filtered = useMemo(() => {
    if (!register) return [];
    let items = register.items;

    if (search) {
      const q = search.toLowerCase();
      items = items.filter(
        (i) =>
          i.number.toLowerCase().includes(q) ||
          i.title.toLowerCase().includes(q) ||
          i.specification_section.toLowerCase().includes(q) ||
          (i.required_by ?? "").toLowerCase().includes(q),
      );
    }
    if (statusFilter !== "ALL") {
      items = items.filter((i) => i.register_status === statusFilter);
    }
    if (specFilter !== "ALL") {
      items = items.filter((i) => i.specification_section === specFilter);
    }
    if (overdueOnly) {
      items = items.filter((i) => i.register_status === "OVERDUE");
    }

    return sortItems(items, sort.field, sort.dir);
  }, [register, search, statusFilter, specFilter, overdueOnly, sort]);

  function toggleSort(field: SortField) {
    setSort((prev) =>
      prev.field === field
        ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { field, dir: "asc" },
    );
  }

  const hasFilters = search || statusFilter !== "ALL" || specFilter !== "ALL" || overdueOnly;

  function clearFilters() {
    setSearch("");
    setStatusFilter("ALL");
    setSpecFilter("ALL");
    setOverdueOnly(false);
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-16 text-center">
        <AlertTriangle className="h-10 w-10 text-amber-500" aria-hidden />
        <h2 className="text-lg font-semibold">Failed to load register</h2>
        <p className="text-sm text-slate-500">The server returned an error.</p>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {projectId}
            </p>
            <h1 className="mt-0.5 text-xl font-semibold text-slate-900">
              Submittal Register
            </h1>
          </div>
          {!isLoading && register && (
            <p className="text-sm text-slate-500">
              {filtered.length} of {register.items.length} item
              {register.items.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>

        {/* Filters */}
        <div className="mt-4 flex flex-wrap gap-3 items-center">
          {/* Search */}
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

          {/* Register status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as RegisterStatus | "ALL")}
            className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Filter by register status"
          >
            <option value="ALL">All statuses</option>
            {REGISTER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {REGISTER_STATUS_LABELS[s]}
              </option>
            ))}
          </select>

          {/* Spec section filter */}
          {specSections.length > 1 && (
            <select
              value={specFilter}
              onChange={(e) => setSpecFilter(e.target.value)}
              className="h-8 rounded-md border border-slate-300 bg-white px-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              aria-label="Filter by specification section"
            >
              <option value="ALL">All spec sections</option>
              {specSections.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}

          {/* Overdue toggle */}
          <button
            onClick={() => setOverdueOnly((v) => !v)}
            className={`h-8 rounded-md border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              overdueOnly
                ? "border-red-300 bg-red-50 text-red-700"
                : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
            }`}
            aria-pressed={overdueOnly}
          >
            Overdue only
          </button>

          {/* Clear filters */}
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="flex items-center gap-1 h-8 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <X className="h-3 w-3" aria-hidden /> Clear
            </button>
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
                  { field: "number" as SortField, label: "SUB #", width: "w-20" },
                  { field: "title" as SortField, label: "Title", width: "w-auto" },
                  { field: "specification_section" as SortField, label: "Spec", width: "w-28" },
                  { field: null, label: "Required By", width: "w-36" },
                  { field: "due_date" as SortField, label: "Due Date", width: "w-28" },
                  { field: "register_status" as SortField, label: "Register Status", width: "w-36" },
                  { field: null, label: "Tech Status", width: "w-32" },
                ] as const
              ).map(({ field, label, width }) => (
                <th
                  key={label}
                  className={`px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 ${width}`}
                >
                  {field ? (
                    <button
                      onClick={() => toggleSort(field)}
                      className="flex items-center gap-1 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                      aria-label={`Sort by ${label}`}
                    >
                      {label}
                      <ArrowUpDown
                        className={`h-3 w-3 ${sort.field === field ? "text-blue-600" : "text-slate-400"}`}
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
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-16 text-center text-sm text-slate-500">
                  {hasFilters
                    ? "No submittals match the current filters."
                    : "No submittals in the register yet."}
                </td>
              </tr>
            ) : (
              filtered.map((item) => {
                const days = daysUntil(item.due_date);
                const isOverdue = item.register_status === "OVERDUE";
                return (
                  <tr
                    key={item.id}
                    className="hover:bg-slate-50 transition-colors cursor-pointer group"
                    onClick={() =>
                      router.push(
                        `/projects/${projectId}/submittals/${item.number}`,
                      )
                    }
                  >
                    <td className="px-4 py-3 font-mono text-xs font-medium text-slate-600">
                      {item.number}
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-900 max-w-xs">
                      <Link
                        href={`/projects/${projectId}/submittals/${item.number}`}
                        className="hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {item.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-500">
                      {item.specification_section}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {item.required_by ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.due_date ? (
                        <span className={isOverdue ? "font-medium text-red-600" : "text-slate-500"}>
                          {formatDate(item.due_date)}
                          {isOverdue && days !== null && (
                            <span className="block text-[10px]">
                              {Math.abs(days)}d ago
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <RegisterStatusBadge status={item.register_status} />
                    </td>
                    <td className="px-4 py-3">
                      <TechnicalStatusBadge status={item.status} />
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
