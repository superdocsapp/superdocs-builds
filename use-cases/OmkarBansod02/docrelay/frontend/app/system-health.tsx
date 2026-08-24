"use client";

import { useEffect, useState } from "react";

type CheckState =
  | { kind: "checking" }
  | { kind: "ready"; requestId: string | null }
  | { kind: "unavailable"; detail: string };

type ReadyResponse = {
  status: "ready" | "unavailable";
  dependencies: Record<string, { status: "ready" | "unavailable"; detail?: string | null }>;
};

const apiOrigin = process.env.NEXT_PUBLIC_DOCRELAY_API_URL ?? "http://localhost:8000";

export function SystemHealth() {
  const [state, setState] = useState<CheckState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    async function check() {
      try {
        const response = await fetch(`${apiOrigin}/health/ready`, {
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = (await response.json()) as ReadyResponse;
        if (response.ok && payload.status === "ready") {
          setState({ kind: "ready", requestId: response.headers.get("x-request-id") });
          return;
        }
        setState({ kind: "unavailable", detail: "The API or PostgreSQL is not ready." });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ kind: "unavailable", detail: "The DocRelay API could not be reached." });
      }
    }

    void check();
    return () => controller.abort();
  }, []);

  return (
    <section className="health" aria-live="polite" aria-busy={state.kind === "checking"}>
      <div>
        <p className="eyebrow">System readiness</p>
        <p className="health-detail">
          {state.kind === "checking" && "Checking the API and required database…"}
          {state.kind === "ready" && "The API and PostgreSQL are ready."}
          {state.kind === "unavailable" && state.detail}
        </p>
      </div>
      <span className={`status status-${state.kind}`}>
        {state.kind === "checking" ? "Checking" : state.kind === "ready" ? "Ready" : "Unavailable"}
      </span>
    </section>
  );
}
