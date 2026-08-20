"use client";

import { useQuery } from "@tanstack/react-query";
import { getHealth } from "@/lib/api/submittals";
import { CheckCircle2, AlertCircle } from "lucide-react";

export default function SettingsPage() {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
  const reviewer = process.env.NEXT_PUBLIC_DEV_REVIEWER ?? "Aryan";

  const { data: health, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    retry: 1,
  });

  return (
    <div className="mx-auto max-w-2xl px-6 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Application configuration and backend connection status.
        </p>
      </div>

      {/* Backend connection */}
      <section aria-labelledby="backend-heading">
        <h2 id="backend-heading" className="mb-3 text-sm font-semibold text-slate-700">
          Backend Connection
        </h2>
        <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <p className="text-sm font-medium text-slate-800">API URL</p>
              <p className="mt-0.5 font-mono text-xs text-slate-500">{apiUrl}</p>
            </div>
            <div className="flex items-center gap-2">
              {isLoading ? (
                <span className="text-xs text-slate-400">Checking…</span>
              ) : isError ? (
                <>
                  <AlertCircle className="h-4 w-4 text-red-500" aria-hidden />
                  <span className="text-xs text-red-600 font-medium">Unreachable</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4 text-green-500" aria-hidden />
                  <span className="text-xs text-green-700 font-medium">Connected</span>
                </>
              )}
            </div>
          </div>
          <div className="px-5 py-4">
            <p className="text-sm font-medium text-slate-800">Backend Status</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {isLoading ? "Checking…" : isError ? "Backend unavailable" : health?.status ?? "—"}
            </p>
          </div>
        </div>
      </section>

      {/* Development config */}
      <section aria-labelledby="dev-config-heading">
        <h2 id="dev-config-heading" className="mb-3 text-sm font-semibold text-slate-700">
          Development Configuration
        </h2>
        <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
          <div className="px-5 py-4">
            <p className="text-sm font-medium text-slate-800">Reviewer Name</p>
            <p className="mt-0.5 font-mono text-xs text-slate-500">{reviewer}</p>
            <p className="mt-1 text-xs text-slate-400">
              Set via <code className="rounded bg-slate-100 px-1 py-0.5">NEXT_PUBLIC_DEV_REVIEWER</code> in{" "}
              <code className="rounded bg-slate-100 px-1 py-0.5">.env.local</code>
            </p>
          </div>
          <div className="px-5 py-4">
            <p className="text-sm font-medium text-slate-800">Environment Variables</p>
            <div className="mt-2 space-y-1">
              {[
                { key: "NEXT_PUBLIC_API_URL", value: apiUrl },
                { key: "NEXT_PUBLIC_DEV_REVIEWER", value: reviewer },
              ].map(({ key, value }) => (
                <div key={key} className="flex items-center gap-2 text-xs">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{key}</code>
                  <span className="text-slate-400">=</span>
                  <span className="text-slate-600">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Note on auth */}
      <div className="rounded-lg border border-slate-100 bg-slate-50 px-5 py-4">
        <p className="text-xs text-slate-500">
          <strong className="text-slate-700">Authentication:</strong> Not implemented in this version.
          The reviewer name is taken from the environment variable above and used as the reviewer
          identifier in all review decisions.
        </p>
      </div>
    </div>
  );
}
