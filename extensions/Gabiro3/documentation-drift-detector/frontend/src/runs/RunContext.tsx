import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { listRuns, type RunSummary } from "../api";

interface RunContextValue {
  runs: RunSummary[];
  selectedRunId: string | null;
  setSelectedRunId: (id: string | null) => void;
  refresh: () => void;
  loading: boolean;
}

const RunContext = createContext<RunContextValue | null>(null);

export function RunProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    listRuns()
      .then((data) => {
        setRuns(data.runs);
        setSelectedRunId((current) => {
          if (current && data.runs.some((r) => r.id === current)) return current;
          return data.runs.length > 0 ? data.runs[0].id : null;
        });
      })
      .catch(() => {
        /* ingestor API may not be running yet — leave state as-is */
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 8000);
    return () => clearInterval(interval);
  }, [refresh]);

  return (
    <RunContext.Provider value={{ runs, selectedRunId, setSelectedRunId, refresh, loading }}>
      {children}
    </RunContext.Provider>
  );
}

export function useRuns() {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRuns must be used within a RunProvider");
  return ctx;
}