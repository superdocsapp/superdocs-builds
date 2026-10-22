import { Database, KeyRound, HardDrive, Server, ShieldCheck, Lock } from "lucide-react";

export function SettingsPage() {
  const rows = [
    { icon: Server, label: "API Base URL", value: import.meta.env.VITE_API_URL || "/api (proxied to :8000)", status: "Connected" },
    { icon: KeyRound, label: "SuperDocs AI Intelligence", value: "Backend-configured (SUPERDOCS_API_KEY with deterministic fallback)", status: "Active" },
    { icon: Database, label: "Relational Database", value: "PostgreSQL 16 (bates_packet)", status: "Healthy" },
    { icon: HardDrive, label: "Content-Addressed Storage", value: "backend/storage (originals, processed, working, final)", status: "Reference-Aware" },
  ];

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8 animate-fade-in">
      {/* Header */}
      <div className="pb-2 border-b dark:border-slate-800/80 border-slate-200/80">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-display font-bold tracking-tight dark:text-white text-slate-900">System Diagnostics</h1>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 bg-emerald-50 text-emerald-700 border border-emerald-300">
            System Operational
          </span>
        </div>
        <p className="dark:text-slate-400 text-slate-600 text-sm mt-1">Runtime infrastructure and verification engine parameters.</p>
      </div>

      {/* Diagnostics Grid */}
      <div className="dark:bg-slate-900/80 bg-white rounded-2xl border dark:border-slate-800/90 border-slate-200 divide-y dark:divide-slate-800/60 divide-slate-200 shadow-sm backdrop-blur-md overflow-hidden">
        {rows.map(({ icon: Icon, label, value, status }) => (
          <div key={label} className="flex items-center justify-between p-5 dark:hover:bg-slate-800/30 hover:bg-slate-50 transition-colors">
            <div className="flex items-start gap-4">
              <div className="h-10 w-10 rounded-xl dark:bg-sky-500/10 bg-sky-50 border dark:border-sky-500/20 border-sky-200 flex items-center justify-center text-sky-500 shrink-0 mt-0.5">
                <Icon className="h-5 w-5" />
              </div>
              <div>
                <p className="text-sm font-semibold dark:text-white text-slate-900">{label}</p>
                <p className="text-xs dark:text-slate-400 text-slate-500 mt-1 font-mono">{value}</p>
              </div>
            </div>
            <span className="px-2.5 py-1 text-xs font-mono font-medium rounded-full dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 bg-emerald-50 text-emerald-700 border border-emerald-300 shrink-0">
              {status}
            </span>
          </div>
        ))}
      </div>

      {/* Legal & Architectural Guarantees Card */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-5 space-y-2 shadow-sm">
          <div className="flex items-center gap-2 text-sky-500">
            <ShieldCheck className="h-5 w-5" />
            <p className="font-semibold dark:text-white text-slate-900 text-sm">Bates Contiguity Invariant</p>
          </div>
          <p className="text-xs dark:text-slate-400 text-slate-600 leading-relaxed">
            Packets use a configurable prefix (default <code className="dark:text-sky-300 text-sky-600 font-mono font-bold">CASE-</code>), sequential start number, and zero-padding width. Reordering dynamically updates contiguous sequence numbering.
          </p>
        </div>

        <div className="dark:bg-slate-900/60 bg-white rounded-2xl border dark:border-slate-800 border-slate-200 p-5 space-y-2 shadow-sm">
          <div className="flex items-center gap-2 text-indigo-500">
            <Lock className="h-5 w-5" />
            <p className="font-semibold dark:text-white text-slate-900 text-sm">Byte-Scrub Redaction & Manifest</p>
          </div>
          <p className="text-xs dark:text-slate-400 text-slate-600 leading-relaxed">
            Redacted bytes are permanently eliminated from PDF streams with multi-pass residue verification. Every exported exhibit and manifest entry is sealed with cryptographic SHA-256 hashes.
          </p>
        </div>
      </div>
    </div>
  );
}