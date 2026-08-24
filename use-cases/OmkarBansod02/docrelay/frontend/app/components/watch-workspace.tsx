"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ICON_STROKE, icons } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { browserPickerTokenManager } from "../google-drive/picker-token";
import {
  configureWatch,
  configureWatchRule,
  getAuthorizeUrl,
  getConnections,
  listWatchRules,
  listWatchRuns,
  listWatchScanItems,
  listWatchScans,
  listWatches,
  triggerWatchScan,
  updateWatchSchedule,
  verifyWriteAuthorization,
  type GoogleConnection,
  type RunSummary,
  type WatchRoot,
  type WatchRule,
  type WatchScan,
  type WatchScanItem,
} from "../lib/api";
import { requestOpenRecentDocument } from "../lib/conversation";
import { extractSelectedFile, formatRelativeTime, type SelectedDriveFile } from "../lib/import-state";
import {
  actionableWatchRuns,
  exactFilePickMatches,
  isGoogleFolder,
  proposalCountLabel,
  scanProgressLabel,
  scheduleLabel,
  watchActivityLabel,
  watchDocumentAction,
  watchDocumentSelection,
  watchErrorCopy,
} from "../lib/watch-state";
import { GoogleDocsMark, GoogleDriveMark } from "./brand";
import { Button, InlineNotice, Skeleton } from "./ui";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
const PICKER_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";
const CLOUD_PROJECT_NUMBER = process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER ?? "";
const DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file";
const DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly";
const FOLDER_MIME = "application/vnd.google-apps.folder";

const INTERVALS = [
  { value: 3600, label: "Every hour" },
  { value: 21600, label: "Every 6 hours" },
  { value: 86400, label: "Every 24 hours" },
  { value: 900, label: "Every 15 min" },
  { value: 300, label: "Every 5 min" },
] as const;

type WatchData = {
  watch: WatchRoot;
  rules: WatchRule[];
  scans: WatchScan[];
  latestItems: WatchScanItem[];
  runs: RunSummary[];
};

export function WatchWorkspace() {
  const router = useRouter();
  const [connection, setConnection] = useState<GoogleConnection | null>(null);
  const [data, setData] = useState<WatchData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pickerBusy, setPickerBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [editingRule, setEditingRule] = useState<WatchRule | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [connections, watches] = await Promise.all([getConnections(signal), listWatches(signal)]);
      const active = connections.connections.find((item) => item.status === "CONNECTED") ?? null;
      setConnection(active);
      const watch = watches.watches.at(-1);
      if (!watch) {
        setData(null);
        return;
      }
      const [rulesResponse, scansResponse, runsResponse] = await Promise.all([
        listWatchRules(watch.watch_id, signal),
        listWatchScans(watch.watch_id, signal),
        listWatchRuns(watch.watch_id, signal),
      ]);
      const scans = [...scansResponse.scans].sort((left, right) => Date.parse(right.started_at) - Date.parse(left.started_at));
      const latest = scans[0];
      const itemsResponse = latest
        ? await listWatchScanItems(watch.watch_id, latest.scan_id, signal)
        : { items: [] };
      setData({
        watch,
        rules: rulesResponse.rules,
        scans,
        latestItems: itemsResponse.items,
        runs: runsResponse.runs,
      });
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Watch could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => void load(controller.signal));
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (data?.scans[0]?.status !== "RUNNING") return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [data?.scans, load]);

  const openConversation = useCallback((run: RunSummary) => {
    requestOpenRecentDocument(watchDocumentSelection(run));
    router.push("/");
  }, [router]);

  async function scanNow() {
    if (!data || busy) return;
    setBusy(true);
    setError(null);
    try {
      await triggerWatchScan(data.watch.watch_id);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The scan could not be started.");
    } finally {
      setBusy(false);
    }
  }

  async function chooseFolder() {
    if (!connection || pickerBusy) return;
    setPickerBusy(true);
    setError(null);
    try {
      const folder = await pickDriveFolder("Choose a Drive folder to watch");
      if (!folder) return;
      await configureWatch({
        connection_id: connection.connection_id,
        root_folder_id: folder.fileId,
        interval_seconds: data?.watch.interval_seconds ?? 3600,
        enabled: data?.watch.enabled ?? true,
      });
      setEditing(false);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be selected.");
    } finally {
      setPickerBusy(false);
    }
  }

  if (loading && !data) return <WatchSkeleton />;

  if (!data) {
    return (
      <WatchEmpty
        connection={connection}
        error={error}
        pickerBusy={pickerBusy}
        onEnableWatch={() => window.location.assign(getAuthorizeUrl("watch"))}
        onChooseFolder={() => void chooseFolder()}
      />
    );
  }

  const { watch, rules, scans, latestItems, runs } = data;
  const latest = scans[0] ?? null;
  const scanning = busy || latest?.status === "RUNNING";
  const pending = actionableWatchRuns(runs);
  const runsById = new Map(runs.map((run) => [run.run_id, run]));
  const watchError = watchErrorCopy(watch.last_error_code ?? latest?.failure_code ?? null);
  const progress = scanProgressLabel(latest, busy);

  const lastScan = watch.last_scan_at ? formatRelativeTime(watch.last_scan_at) : null;

  return (
    <div className="page-shell">
      <div className="page-measure">
        <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
          <div className="min-w-0">
            <span className="pill pill-neutral mb-3 flex w-fit">
              <icons.watch className="size-3" strokeWidth={ICON_STROKE} aria-hidden="true" />
              Automatic discovery
            </span>
            <h1 className="type-page-title">Watch</h1>
            <p className="type-body-muted mt-2 max-w-[42rem]">
              Keep selected Drive folders in sync with reviewed DocRelay changes.
            </p>
          </div>
          <WatchAccessStatus
            connection={connection}
            onEnable={() => window.location.assign(getAuthorizeUrl("watch"))}
          />
        </header>

        {error ? (
          <div className="mt-6">
            <InlineNotice tone="warning">{error}</InlineNotice>
          </div>
        ) : null}

        {watchError ? (
          <div className="mt-6">
            <Alert variant="warning" className="rounded-[var(--radius-pane)]">
              <icons.warning strokeWidth={ICON_STROKE} />
              <AlertTitle>{watchError.title}</AlertTitle>
              <AlertDescription>{watchError.detail}</AlertDescription>
              {watch.last_error_code === "GOOGLE_WATCH_AUTHORIZATION_REQUIRED" ? (
                <AlertAction>
                  <Button variant="secondary" onClick={() => window.location.assign(getAuthorizeUrl("watch"))}>
                    Enable watch access
                  </Button>
                </AlertAction>
              ) : null}
            </Alert>
          </div>
        ) : null}

        <section className="mt-10" aria-labelledby="watching-heading">
          <h2 id="watching-heading" className="type-section-title">Watching</h2>
          <div className="surface-section mt-3.5 px-5 py-5 sm:px-6 sm:py-6">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
              <span
                className="grid size-10 shrink-0 place-items-center rounded-[11px] border border-border-light bg-surface-sunken text-muted shadow-[var(--shadow-subtle)]"
                aria-hidden="true"
              >
                <icons.folderOpen className="size-[19px]" strokeWidth={ICON_STROKE} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15.5px] font-semibold tracking-[-0.02em] text-ink">{watch.root_name}</p>
                <p className="type-caption mt-0.5 flex items-center gap-1.5">
                  <GoogleDriveMark className="size-3" />
                  Google Drive
                </p>
              </div>
              <WatchStatePill enabled={watch.enabled} />
            </div>

            <dl className="mt-5 grid gap-x-8 gap-y-5 border-t border-border-hair pt-5 sm:grid-cols-[minmax(0,1fr)_auto]">
              <div className="min-w-0">
                <dt className="type-section-heading">Rule</dt>
                {rules.length === 0 ? (
                  <dd className="mt-1.5 text-[13.5px] leading-[1.6] text-muted">
                    Add a rule so discovered documents know what to do.
                  </dd>
                ) : (
                  <dd className="mt-1.5 space-y-3">
                    {rules.map((rule) => (
                      <div key={rule.rule_id} className="min-w-0">
                        <p className="border-l-2 border-primary-line pl-3 text-[13.5px] leading-[1.6] text-ink italic">
                          “{rule.instruction}”
                        </p>
                        <p className="type-caption mt-0.5">{rule.folder_name}</p>
                        {editing ? (
                          <button
                            type="button"
                            onClick={() => { setEditingRule(rule); setShowRuleForm(true); }}
                            className="type-caption mt-1 text-accent hover:underline"
                          >
                            Edit rule
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </dd>
                )}
              </div>
              <div className="sm:text-right">
                <dt className="type-section-heading">Schedule</dt>
                <dd className="mt-1.5 text-[13.5px] text-ink">
                  {scheduleLabel(watch.enabled, watch.interval_seconds)}
                </dd>
                {lastScan ? <dd className="type-caption mt-1">Last scan {lastScan}</dd> : null}
                {progress ? <dd className="mt-1 text-[13px] text-accent">{progress}</dd> : null}
              </div>
            </dl>

            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border-hair pt-5">
              <Button busy={scanning} disabled={scanning} onClick={() => void scanNow()}>
                {latest?.status === "RUNNING" ? "Scanning…" : "Scan now"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setEditing((value) => !value);
                  if (editing) {
                    setShowRuleForm(false);
                    setEditingRule(null);
                  }
                }}
              >
                {editing ? "Done" : "Edit setup"}
              </Button>
              <Button variant="ghost" disabled={pickerBusy} onClick={() => void chooseFolder()}>
                {pickerBusy ? "Opening Drive…" : "Change folder"}
              </Button>
            </div>

            {editing ? (
              <div className="mt-5 border-t border-border-hair pt-5 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-[var(--motion-duration)]">
                <ScheduleEditor
                  watch={watch}
                  onSaved={() => { void load(); }}
                />
                <Button
                  variant="ghost"
                  className="mt-4"
                  onClick={() => { setEditingRule(null); setShowRuleForm(true); }}
                >
                  <icons.plus className="size-4" strokeWidth={ICON_STROKE} />
                  Add rule
                </Button>
                {showRuleForm ? (
                  <RuleEditor
                    watchId={watch.watch_id}
                    rule={editingRule}
                    onClose={() => { setShowRuleForm(false); setEditingRule(null); }}
                    onSaved={() => { setShowRuleForm(false); setEditingRule(null); void load(); }}
                  />
                ) : null}
              </div>
            ) : null}
          </div>
        </section>

        <section className="mt-10" aria-labelledby="needs-review-heading">
          <div className="flex items-center justify-between gap-4">
            <h2 id="needs-review-heading" className="type-section-title">Needs review</h2>
            {pending.length > 0 ? (
              <span className="pill pill-warning tabular-nums">
                {pending.length} waiting
              </span>
            ) : null}
          </div>
          {/* Documents waiting on a person are the loudest thing on the page:
              a raised surface, a warm edge, and the action in reach. */}
          <div
            className={cn(
              "mt-3.5 overflow-hidden rounded-[var(--radius-pane)] border bg-surface",
              pending.length > 0
                ? "border-warning/30 shadow-[var(--shadow-raised)]"
                : "border-border-light shadow-[var(--shadow-subtle)]",
            )}
          >
            {pending.length === 0 ? (
              <EmptySurfaceRow
                tone={latest ? "positive" : "neutral"}
                label={latest ? "Nothing needs review" : "Scan to discover documents"}
              />
            ) : pending.map((run) => {
              const action = watchDocumentAction(run);
              return (
                <article
                  key={run.run_id}
                  className="relative flex flex-wrap items-start gap-x-4 gap-y-3 border-b border-border-hair px-5 py-4 transition-colors duration-[var(--motion-duration)] last:border-b-0 hover:bg-surface-sunken"
                >
                  <span
                    className="absolute inset-y-0 left-0 w-[2.5px] bg-warning/50"
                    aria-hidden="true"
                  />
                  <GoogleDocsMark className="mt-0.5 size-[17px]" />
                  <div className="min-w-[12rem] flex-1">
                    <p className="truncate text-[14.5px] font-medium tracking-[-0.014em] text-ink">{run.document_name}</p>
                    <p className="mt-0.5 text-[12.75px] text-muted">
                      {action.kind === "review" ? proposalCountLabel(run.proposal_count) : action.statusLabel}
                    </p>
                    {action.kind === "authorize" && action.detail ? (
                      <p className="mt-2 max-w-[36rem] text-[12.75px] leading-[1.6] text-muted">{action.detail}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {action.kind === "authorize" ? (
                      <AuthorizeExactFileButton
                        run={run}
                        onAuthorized={() => void load()}
                        onError={setError}
                      />
                    ) : null}
                    <Button
                      variant={action.kind === "authorize" ? "secondary" : "primary"}
                      onClick={() => openConversation(run)}
                    >
                      Open conversation
                      <icons.chevronRight className="size-3.5" strokeWidth={ICON_STROKE} aria-hidden="true" />
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="mt-10" aria-labelledby="activity-heading">
          <h2 id="activity-heading" className="type-section-title">Recent activity</h2>
          <div className="surface-section mt-3.5 overflow-hidden">
            {latestItems.length === 0 ? (
              <EmptySurfaceRow
                tone="neutral"
                label={latest?.status === "RUNNING" ? "Scan in progress" : "No recent Watch activity"}
              />
            ) : latestItems.map((item) => {
              const run = item.run_id ? runsById.get(item.run_id) : undefined;
              const label = watchActivityLabel(item, run);
              return (
                <div
                  key={`${item.provider_file_id}-${item.outcome}`}
                  className="flex items-center gap-3 border-b border-border-hair px-5 py-3 transition-colors duration-[var(--motion-duration)] last:border-b-0 hover:bg-surface-sunken"
                >
                  <GoogleDocsMark className="size-[15px] opacity-80" />
                  <p className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{item.name}</p>
                  <ActivityMark label={label} />
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function WatchStatePill({ enabled }: { enabled: boolean }) {
  return (
    <span className={cn("pill shrink-0", enabled ? "pill-accent" : "pill-neutral")}>
      <span
        className={cn("size-[6px] rounded-full", enabled ? "bg-primary" : "bg-muted-soft")}
        aria-hidden="true"
      />
      {enabled ? "Watch enabled" : "Manual only"}
    </span>
  );
}

/** Truthful status labels only — the tone is derived, never the wording. */
function ActivityMark({ label }: { label: string }) {
  const attention = label === "Attention required" || label === "Conflict"
    || label === "Write access required" || label === "Needs review";
  const verified = label === "Verified" || label === "Reviewed";
  return (
    <span
      className={cn(
        "pill shrink-0",
        attention ? "pill-warning" : verified ? "pill-accent" : "pill-neutral",
      )}
    >
      <span
        className={cn(
          "size-[6px] rounded-full",
          attention ? "bg-warning" : verified ? "bg-primary" : "bg-muted-soft",
        )}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function EmptySurfaceRow({ label, tone }: { label: string; tone: "positive" | "neutral" }) {
  return (
    <p className="flex items-center gap-2 px-5 py-6 text-[13.5px] text-muted">
      {tone === "positive" ? (
        <icons.check className="size-4 shrink-0 text-success" strokeWidth={2.25} aria-hidden="true" />
      ) : null}
      {label}
    </p>
  );
}

function WatchAccessStatus({
  connection,
  onEnable,
}: {
  connection: GoogleConnection | null;
  onEnable: () => void;
}) {
  if (connection?.watch_authorized) {
    return (
      <p className="pill pill-accent h-7 shrink-0 px-2.5">
        <span className="grid size-3.5 place-items-center rounded-full bg-primary text-primary-foreground" aria-hidden="true">
          <icons.check className="size-2.5" strokeWidth={2.75} />
        </span>
        Drive access · Watch enabled
      </p>
    );
  }

  return (
    <div className="surface-section shrink-0 px-4 py-3.5">
      <p className="text-[13.5px] font-medium text-ink">Watch access required</p>
      <p className="mt-1 max-w-[22rem] text-[12.75px] leading-[1.6] text-muted">
        DocRelay needs read access to discover files in the selected folder.
      </p>
      <Button className="mt-3" onClick={onEnable}>Enable watch access</Button>
    </div>
  );
}

function WatchEmpty({
  connection,
  error,
  pickerBusy,
  onEnableWatch,
  onChooseFolder,
}: {
  connection: GoogleConnection | null;
  error: string | null;
  pickerBusy: boolean;
  onEnableWatch: () => void;
  onChooseFolder: () => void;
}) {
  const watchReady = Boolean(connection?.watch_authorized);
  const ready = Boolean(connection) && watchReady;
  return (
    <section className="page-shell">
      {/* The same starting composition as the Workspace hero — one left-aligned
          column carrying a single selection row — so the two entry points into
          the product read as the same product. */}
      <div className="mx-auto w-full max-w-[568px] pt-4 lg:pt-14">
        <h1 className="type-hero-title text-balance">Watch a Drive folder</h1>
        <p className="type-hero-body mt-3.5 max-w-[29rem] text-pretty">
          Keep a Drive folder in sync with human-reviewed DocRelay changes.
        </p>

        <div className="mt-8 flex w-full flex-col gap-3 lg:mt-9">
          {error ? <InlineNotice tone="warning">{error}</InlineNotice> : null}

          <div
            className={cn(
              "flex w-full flex-col items-stretch gap-3.5 rounded-[14px] border p-4 text-left",
              "border-border bg-surface shadow-[var(--shadow-raised)]",
              "sm:flex-row sm:items-center sm:gap-4 sm:py-3.5 sm:pr-3.5 sm:pl-[18px]",
            )}
          >
            <span className="flex min-w-0 flex-1 items-center gap-3.5">
              <icons.folderOpen
                className="size-[25px] shrink-0 text-muted"
                strokeWidth={ICON_STROKE}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[16px] leading-[1.3] font-semibold tracking-[-0.024em] text-ink">
                  {ready ? "Choose a folder" : "Watch access required"}
                </span>
                <span className="mt-[3px] block text-[12.75px] leading-[1.45] text-muted">
                  {ready
                    ? "Select the folder to watch, then add a rule and a schedule."
                    : "DocRelay needs read access to discover files in the folder."}
                </span>
              </span>
            </span>
            {ready ? (
              <Button className="h-[36px] shrink-0 px-4" busy={pickerBusy} onClick={onChooseFolder}>
                {pickerBusy ? "Opening…" : "Choose folder"}
              </Button>
            ) : (
              <Button className="h-[36px] shrink-0 px-4" onClick={onEnableWatch}>
                Enable access
              </Button>
            )}
          </div>
        </div>

        <p className="mt-5 text-[12.5px] leading-5 text-muted-soft">
          Every discovered change is reviewed before write-back.
        </p>
      </div>
    </section>
  );
}

function ScheduleEditor({ watch, onSaved }: { watch: WatchRoot; onSaved: () => void }) {
  const [interval, setIntervalValue] = useState(watch.interval_seconds);
  const [enabled, setEnabled] = useState(watch.enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="type-section-heading grid gap-1.5">
        Schedule
        <select
          value={enabled ? interval : 0}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (next === 0) {
              setEnabled(false);
              return;
            }
            setEnabled(true);
            setIntervalValue(next);
          }}
          className="h-[34px] rounded-[9px] border border-border bg-surface px-3 text-[13px] font-normal tracking-normal text-ink normal-case outline-none transition-colors duration-[var(--motion-duration)] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20"
        >
          <option value={0}>Manual</option>
          {INTERVALS.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
      </label>
      <Button
        busy={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await updateWatchSchedule(watch.watch_id, { enabled, interval_seconds: enabled ? interval : watch.interval_seconds });
            onSaved();
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "Schedule could not be saved.");
          } finally {
            setBusy(false);
          }
        }}
      >
        Save schedule
      </Button>
      {error ? <p className="w-full text-[13px] text-warning">{error}</p> : null}
    </div>
  );
}

function RuleEditor({
  watchId,
  rule,
  onClose,
  onSaved,
}: {
  watchId: string;
  rule: WatchRule | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [folder, setFolder] = useState<SelectedDriveFile | null>(
    rule ? { fileId: rule.folder_id, name: rule.folder_name, mimeType: FOLDER_MIME } : null,
  );
  const [instruction, setInstruction] = useState(rule?.instruction ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pickFolder() {
    if (rule || picking) return;
    setPicking(true);
    setError(null);
    try {
      const selected = await pickDriveFolder("Choose a folder for this rule");
      if (selected) setFolder(selected);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be selected.");
    } finally {
      setPicking(false);
    }
  }

  return (
    <div className="mt-5 rounded-[var(--radius-card)] border border-border-light bg-surface-sunken px-4 py-4">
      <h3 className="text-[13.5px] font-semibold tracking-[-0.015em] text-ink">
        {rule ? `Edit ${rule.folder_name}` : "Add rule"}
      </h3>
      <div className="mt-4 grid gap-4">
        <div>
          <p className="type-section-heading">Folder</p>
          {folder ? (
            <p className="mt-1.5 text-[13.5px] text-ink">{folder.name}</p>
          ) : (
            <Button variant="secondary" className="mt-1.5" busy={picking} onClick={() => void pickFolder()}>
              {picking ? "Opening Drive…" : "Choose folder"}
            </Button>
          )}
        </div>
        <label className="type-section-heading grid gap-1.5">
          Instruction
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={4}
            className="resize-y rounded-[10px] border border-border bg-surface px-3.5 py-2.5 text-[13.5px] leading-[1.6] font-normal tracking-normal text-ink normal-case outline-none transition-colors duration-[var(--motion-duration)] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20"
          />
        </label>
        <label className="flex items-center gap-2 text-[13px] text-ink">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="size-4 accent-accent" />
          Enabled
        </label>
        {error ? <InlineNotice tone="warning">{error}</InlineNotice> : null}
        <div className="flex gap-2">
          <Button
            busy={busy}
            disabled={!folder || !instruction.trim()}
            onClick={async () => {
              if (!folder) return;
              setBusy(true);
              setError(null);
              try {
                await configureWatchRule(watchId, {
                  folder_id: folder.fileId,
                  instruction: instruction.trim(),
                  enabled,
                });
                onSaved();
              } catch (reason) {
                setError(reason instanceof Error ? reason.message : "Rule could not be saved.");
              } finally {
                setBusy(false);
              }
            }}
          >
            Save rule
          </Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  );
}

function AuthorizeExactFileButton({
  run,
  onAuthorized,
  onError,
}: {
  run: RunSummary;
  onAuthorized: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  return (
    <Button
      busy={busy}
      onClick={() => {
        void (async () => {
          if (busy) return;
          setBusy(true);
          try {
            const pickedId = await pickExactDocument(run.document_name);
            if (!pickedId) return;
            if (!exactFilePickMatches(pickedId, run.provider_file_id)) {
              onError(`Choose ${run.document_name}. DocRelay will not transfer permission from another file.`);
              return;
            }
            await verifyWriteAuthorization(run.run_id, pickedId);
            onAuthorized();
          } catch (reason) {
            onError(reason instanceof Error ? reason.message : "Exact-file authorization failed.");
          } finally {
            setBusy(false);
          }
        })();
      }}
    >
      {busy ? "Opening Google Drive…" : "Authorize document"}
    </Button>
  );
}

function WatchSkeleton() {
  return (
    <div className="page-shell">
      <div className="page-measure space-y-4">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-80" />
        <Skeleton className="h-44 w-full rounded-[var(--radius-pane)]" />
        <Skeleton className="h-32 w-full rounded-[var(--radius-pane)]" />
      </div>
    </div>
  );
}

async function pickDriveFolder(title: string): Promise<SelectedDriveFile | null> {
  await ensurePicker();
  const token = await requestPickerToken(DRIVE_READONLY_SCOPE);
  return new Promise((resolve, reject) => {
    try {
      const view = new window.google!.picker!.DocsView();
      view.setMimeTypes(FOLDER_MIME);
      view.setIncludeFolders(true);
      view.setSelectFolderEnabled(true);
      const picker = new window.google!.picker!.PickerBuilder()
        .addView(view)
        .setOAuthToken(token)
        .setDeveloperKey(PICKER_API_KEY)
        .setAppId(CLOUD_PROJECT_NUMBER)
        .setOrigin(window.location.origin)
        .setTitle(title)
        .setCallback((data: google.picker.ResponseObject) => {
          if (data.action === "cancel") {
            resolve(null);
            return;
          }
          if (data.action === "error") {
            reject(new Error("Google Picker could not complete folder selection."));
            return;
          }
          if (data.action !== "picked") return;
          const file = extractSelectedFile(data);
          if (!file || (file.mimeType && !isGoogleFolder(file.mimeType))) {
            resolve(null);
            return;
          }
          resolve({ ...file, mimeType: file.mimeType || FOLDER_MIME });
        })
        .build();
      picker.setVisible(true);
    } catch (reason) {
      reject(reason);
    }
  });
}

async function pickExactDocument(documentName: string): Promise<string | null> {
  await ensurePicker();
  const token = await browserPickerTokenManager.getToken(
    (prompt) => requestPickerTokenResponse(DRIVE_FILE_SCOPE, prompt),
  );
  return new Promise((resolve, reject) => {
    try {
      const view = new window.google!.picker!.DocsView();
      view.setMimeTypes("application/vnd.google-apps.document");
      const picker = new window.google!.picker!.PickerBuilder()
        .addView(view)
        .setOAuthToken(token)
        .setDeveloperKey(PICKER_API_KEY)
        .setAppId(CLOUD_PROJECT_NUMBER)
        .setOrigin(window.location.origin)
        .setTitle(`Authorize ${documentName}`)
        .setCallback((data: google.picker.ResponseObject) => {
          if (data.action === "cancel") {
            resolve(null);
            return;
          }
          const file = extractSelectedFile(data);
          resolve(file?.fileId ?? null);
        })
        .build();
      picker.setVisible(true);
    } catch (reason) {
      reject(reason);
    }
  });
}

async function ensurePicker(): Promise<void> {
  if (!GOOGLE_CLIENT_ID || !PICKER_API_KEY || !CLOUD_PROJECT_NUMBER) {
    throw new Error("Google Drive is not fully configured in this environment.");
  }
  await Promise.all([loadGapiScript(), loadGisScript()]);
  await loadPickerLibrary();
}

function requestPickerToken(scope: string): Promise<string> {
  return requestPickerTokenResponse(scope, "").then((response) => response.accessToken);
}

function requestPickerTokenResponse(
  scope: string,
  prompt: "" | "consent",
): Promise<{ accessToken: string; expiresIn: number }> {
  return new Promise((resolve, reject) => {
    const client = window.google!.accounts!.oauth2!.initTokenClient({
      client_id: GOOGLE_CLIENT_ID,
      scope,
      callback: (response) => {
        if (response.error) {
          reject(new Error(response.error_description || response.error));
          return;
        }
        resolve({ accessToken: response.access_token, expiresIn: response.expires_in });
      },
      error_callback: (reason) => reject(new Error(reason.message || "OAuth popup was closed or denied")),
    });
    client.requestAccessToken({ prompt });
  });
}

let gapiLoadPromise: Promise<void> | null = null;
let gisLoadPromise: Promise<void> | null = null;

function loadGapiScript(): Promise<void> {
  if (gapiLoadPromise) return gapiLoadPromise;
  gapiLoadPromise = new Promise((resolve, reject) => {
    if (window.gapi) { resolve(); return; }
    const script = document.createElement("script");
    script.src = "https://apis.google.com/js/api.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google API script"));
    document.head.appendChild(script);
  });
  return gapiLoadPromise;
}

function loadGisScript(): Promise<void> {
  if (gisLoadPromise) return gisLoadPromise;
  gisLoadPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) { resolve(); return; }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(script);
  });
  return gisLoadPromise;
}

function loadPickerLibrary(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.picker) { resolve(); return; }
    if (!window.gapi) { reject(new Error("GAPI not loaded")); return; }
    window.gapi.load("picker", () => window.google?.picker ? resolve() : reject(new Error("Picker library failed to initialize")));
  });
}
