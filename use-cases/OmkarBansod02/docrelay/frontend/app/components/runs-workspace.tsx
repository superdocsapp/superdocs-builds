"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { listRuns, listWatchRules, listWatches, type RunSummary } from "../lib/api";
import { isDocRelayBackupName } from "../lib/import-state";
import { ICON_STROKE, icons } from "@/lib/icons";
import { GoogleDocsMark } from "./brand";
import { RunStatus } from "./run-status";
import { Button, InlineNotice, Skeleton } from "./ui";

export function RunsWorkspace() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [ruleNames, setRuleNames] = useState<Map<string, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [runResponse, watchResponse] = await Promise.all([listRuns(signal), listWatches(signal)]);
      const rulesByWatch = await Promise.all(
        watchResponse.watches.map((watch) => listWatchRules(watch.watch_id, signal)),
      );
      const names = new Map<string, string>();
      for (const response of rulesByWatch) {
        for (const rule of response.rules) names.set(rule.rule_id, `${rule.folder_name}/`);
      }
      setRuleNames(names);
      setRuns(runResponse.runs);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Runs could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => void load(controller.signal));
    return () => controller.abort();
  }, [load]);

  return (
    <section className="page-shell">
      <div className="page-measure">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
          <div className="min-w-0">
            <span className="pill pill-neutral mb-3 flex w-fit">
              <icons.activity className="size-3" strokeWidth={ICON_STROKE} aria-hidden="true" />
              Full history
            </span>
            <h1 className="type-page-title">Activity</h1>
            <p className="type-body-muted mt-2 max-w-[42rem]">
              Every manual and watched document operation, each independently actionable.
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh runs"
          >
            <icons.refresh className="size-4" strokeWidth={ICON_STROKE} aria-hidden="true" />
            Refresh
          </Button>
        </div>

        {error ? (
          <div className="mt-7">
            <InlineNotice tone="warning">{error}</InlineNotice>
          </div>
        ) : null}

        {loading ? (
          <RunsSkeleton />
        ) : runs.length === 0 ? (
          <EmptyRuns />
        ) : (
          <div className="surface-section mt-8 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-left">
                <thead>
                  <tr className="type-section-heading border-b border-border bg-surface-sunken">
                    <th className="px-5 py-3 font-medium">Document</th>
                    <th className="px-3 py-3 font-medium">Origin</th>
                    <th className="px-3 py-3 font-medium">Matched rule</th>
                    <th className="px-3 py-3 font-medium">State</th>
                    <th className="px-3 py-3 font-medium">Updated</th>
                    <th className="px-5 py-3 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.run_id}
                      className="border-b border-border-hair transition-colors duration-[var(--motion-duration)] last:border-b-0 hover:bg-surface-sunken"
                    >
                      <td className="px-5 py-4">
                        <span className="flex items-center gap-2.5 text-[13.5px] font-medium tracking-[-0.014em] text-ink">
                          <GoogleDocsMark className="size-[15px]" />
                          <span className="min-w-0 truncate">{run.document_name}</span>
                          {/* The run really did target this Google file, so the
                              row stays — it is only labelled for what the file
                              is: a versioned copy DocRelay created, not the
                              authoritative source document. */}
                          {isDocRelayBackupName(run.document_name) ? (
                            <span className="pill pill-neutral shrink-0">Backup copy</span>
                          ) : null}
                        </span>
                      </td>
                      <td className="px-3 py-4 text-[13.25px] text-muted">
                        {run.watch_id ? "Watch" : "Manual"}
                      </td>
                      <td className="px-3 py-4 text-[13.25px] text-muted">
                        {run.matched_rule_id
                          ? ruleNames.get(run.matched_rule_id) ?? `Rule v${run.matched_rule_version ?? "—"}`
                          : "—"}
                      </td>
                      <td className="px-3 py-4">
                        <RunStatus run={run} />
                      </td>
                      <td className="px-3 py-4 text-[13.25px] tabular-nums text-muted">
                        {formatDateTime(run.updated_at)}
                      </td>
                      <td className="px-5 py-4 text-right">
                        <Button variant="secondary" className="h-[30px] px-2.5" asChild>
                          <Link href={`/runs/${run.run_id}`}>
                            Open
                            <icons.chevronRight
                              className="size-3.5"
                              strokeWidth={ICON_STROKE}
                              aria-hidden="true"
                            />
                          </Link>
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function RunsSkeleton() {
  return (
    <div className="mt-8 space-y-3">
      <Skeleton className="h-10 w-full rounded-[var(--radius-pane)]" />
      {[1, 2, 3, 4].map((item) => (
        <Skeleton key={item} className="h-14 w-full rounded-[var(--radius-pane)]" />
      ))}
    </div>
  );
}

function EmptyRuns() {
  return (
    <div className="surface-section mt-8 flex flex-col items-center px-6 py-16 text-center">
      <span
        className="grid size-11 place-items-center rounded-[12px] border border-border-light bg-surface-sunken shadow-[var(--shadow-subtle)]"
        aria-hidden="true"
      >
        <GoogleDocsMark className="size-[19px]" />
      </span>
      <h2 className="mt-4 text-[15.5px] font-semibold tracking-[-0.022em] text-ink">No activity yet</h2>
      <p className="mt-2 max-w-[24rem] text-[13.5px] leading-[1.62] text-muted">
        Choose a document in Workspace or configure Watch to begin.
      </p>
    </div>
  );
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}
