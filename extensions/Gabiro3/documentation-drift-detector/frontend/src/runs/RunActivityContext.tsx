import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { listRuns, type RunSummary } from "../api";
import { useNotifications } from "../notifications/NotificationContext";

const ACTIVE_STATUSES = new Set(["pending", "in_progress"]);
const POLL_MS = 3000;

export function isRunActive(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

interface RunActivityState {
  activeRuns: RunSummary[];
  panelCollapsed: boolean;
  togglePanel: () => void;
  /** Start watching a run so its completion raises a toast. */
  trackRun: (runId: string, label: string) => void;
}

const RunActivityContext = createContext<RunActivityState | null>(null);

export function RunActivityProvider({ children }: { children: ReactNode }) {
  const { notify } = useNotifications();
  const [activeRuns, setActiveRuns] = useState<RunSummary[]>([]);
  const [panelCollapsed, setPanelCollapsed] = useState(false);

  // Last status we saw per run, so we only toast on an actual transition.
  const lastStatus = useRef<Map<string, string>>(new Map());
  const labels = useRef<Map<string, string>>(new Map());
  const primed = useRef(false);

  const trackRun = useCallback((runId: string, label: string) => {
    labels.current.set(runId, label);
    if (!lastStatus.current.has(runId)) {
      lastStatus.current.set(runId, "pending");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      let runs: RunSummary[];
      try {
        runs = (await listRuns()).runs;
      } catch {
        return; // ingestor may not be up yet; next tick retries
      }
      if (cancelled) return;

      setActiveRuns(runs.filter((r) => isRunActive(r.status)));

      for (const run of runs) {
        const prev = lastStatus.current.get(run.id);
        lastStatus.current.set(run.id, run.status);

        // Skip the first sweep: pre-existing finished runs are history,
        // not events worth announcing.
        if (!primed.current || prev === undefined || prev === run.status) continue;

        if (isRunActive(prev) && !isRunActive(run.status)) {
          const label = labels.current.get(run.id) ?? run.corpus_ref ?? run.trigger;
          if (run.status === "completed") {
            notify("Analysis complete", `${label} · run ${run.id.slice(0, 8)}`, "success");
          } else if (run.status === "failed") {
            // Point at the logs: a failure the user can't inspect is useless.
            notify(
              "Analysis failed",
              `${label} · open run ${run.id.slice(0, 8)} in the runs list to see why`,
              "error"
            );
          }
          labels.current.delete(run.id);
        }
      }
      primed.current = true;
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [notify]);

  return (
    <RunActivityContext.Provider
      value={{
        activeRuns,
        panelCollapsed,
        togglePanel: () => setPanelCollapsed((v) => !v),
        trackRun,
      }}
    >
      {children}
    </RunActivityContext.Provider>
  );
}

export function useRunActivity(): RunActivityState {
  const ctx = useContext(RunActivityContext);
  if (!ctx) throw new Error("useRunActivity must be used within a RunActivityProvider");
  return ctx;
}
