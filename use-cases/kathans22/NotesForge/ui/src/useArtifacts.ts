import { useCallback, useEffect, useState } from "react";
import type {
  AmendmentBatch,
  Client,
  ConsentMatrix,
  CoverageSnapshot,
  LedgerSnapshot,
  PacksSnapshot,
  Requirement,
  VersionStore,
} from "./types";

export interface Artifacts {
  clients: Client[];
  requirements: Requirement[];
  coverage: CoverageSnapshot;
  packs: PacksSnapshot;
  versions: VersionStore;
  consentMatrix: ConsentMatrix;
  requirementsSnapshot: Requirement[] | null;
  ledger: LedgerSnapshot | null;
  amendments: AmendmentBatch[];
  corpusNotes: Record<string, string>;
}

type ArtifactsState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: Artifacts };

async function fetchJson<T>(path: string): Promise<T> {
  // no-store: after a run triggers a re-sync, the browser must not serve a
  // stale cached copy of a file at the same URL.
  const res = await fetch(`/data/${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`failed to load /data/${path}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

/**
 * Loads every synced artifact, and exposes `reload` so a UI action (running
 * a compliance command via RunPanel) can refresh the screen with whatever
 * that run just wrote — still just reading state/*.json back, never
 * recomputing anything itself.
 */
export function useArtifacts(): { state: ArtifactsState; reload: () => void } {
  const [state, setState] = useState<ArtifactsState>({ status: "loading" });
  const [generation, setGeneration] = useState(0);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [
          clients,
          requirements,
          coverage,
          packs,
          versions,
          consentMatrix,
          requirementsSnapshot,
          ledger,
          amendments,
          corpusNotes,
        ] = await Promise.all([
          fetchJson<Client[]>("clients.json"),
          fetchJson<Requirement[]>("requirements.json"),
          fetchJson<CoverageSnapshot>("coverage.json"),
          fetchJson<PacksSnapshot>("packs.json"),
          fetchJson<VersionStore>("versions.json"),
          fetchJson<ConsentMatrix>("consent-matrix.json"),
          fetchJson<Requirement[] | null>("requirements-snapshot.json"),
          fetchJson<LedgerSnapshot | null>("ledger.json"),
          fetchJson<AmendmentBatch[]>("amendments.json"),
          fetchJson<Record<string, string>>("corpus-notes.json"),
        ]);

        if (!cancelled) {
          setState({
            status: "ready",
            data: {
              clients,
              requirements,
              coverage,
              packs,
              versions,
              consentMatrix,
              requirementsSnapshot,
              ledger,
              amendments,
              corpusNotes,
            },
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [generation]);

  return { state, reload };
}
