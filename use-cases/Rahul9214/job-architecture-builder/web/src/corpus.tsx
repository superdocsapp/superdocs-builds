import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { CorpusSummary } from "./types";

type CorpusContextValue = {
  corpora: CorpusSummary[];
  corpusId: string;
  setCorpusId: (id: string) => void;
  analyzed: boolean;
  loading: boolean;
  error: string | null;
  analyze: () => Promise<void>;
  refresh: () => Promise<void>;
};

const CorpusContext = createContext<CorpusContextValue | null>(null);

export function CorpusProvider({ children }: { children: ReactNode }) {
  const [corpora, setCorpora] = useState<CorpusSummary[]>([]);
  const [corpusId, setCorpusId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const current = corpora.find((item) => item.corpus_id === corpusId);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.corpora();
      setCorpora(payload.corpora);
      setCorpusId((existing) => {
        if (existing && payload.corpora.some((item) => item.corpus_id === existing)) {
          return existing;
        }
        return payload.corpora[0]?.corpus_id ?? "";
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load corpora.");
    } finally {
      setLoading(false);
    }
  }, []);

  const analyze = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await api.analyze(corpusId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Analyze failed.");
      setLoading(false);
    }
  }, [corpusId, refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({
      corpora,
      corpusId,
      setCorpusId,
      analyzed: Boolean(current?.analyzed),
      loading,
      error,
      analyze,
      refresh,
    }),
    [analyze, corpora, corpusId, current?.analyzed, error, loading, refresh],
  );

  return <CorpusContext.Provider value={value}>{children}</CorpusContext.Provider>;
}

// The provider and hook are the public corpus API for the reviewer shell.
// eslint-disable-next-line react-refresh/only-export-components
export function useCorpus() {
  const value = useContext(CorpusContext);
  if (!value) {
    throw new Error("useCorpus must be used within CorpusProvider");
  }
  return value;
}
