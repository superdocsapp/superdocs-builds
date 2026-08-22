import React from "react";
import { Sparkles, FileSpreadsheet } from "lucide-react";
import { config } from "../config";

interface HeroBannerProps {
  onOpenReport: () => void;
}

export function HeroBanner({ onOpenReport }: HeroBannerProps) {
  return (
    <div className="glass-panel p-6 sm:p-8 rounded-3xl relative overflow-hidden flex flex-col md:flex-row items-start md:items-center justify-between gap-6 border border-white/10 shadow-2xl">
      <div className="space-y-2.5 max-w-2xl">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs font-mono font-medium">
          <Sparkles className="w-3.5 h-3.5 text-rose-400" />
          Annual Attestation Cycle Active · {config.app.defaultCycleYear}
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight leading-tight">
          Supplier Code-of-Conduct & ESG Compliance
        </h2>
        <p className="text-xs sm:text-sm text-slate-300 leading-relaxed font-normal">
          Issue localized tier-specific questionnaires, normalize multi-format supplier responses, verify via human review gates, and automatically draft deficiency notices quoting supplier evidence.
        </p>
      </div>

      <button
        onClick={onOpenReport}
        className="px-5 py-3.5 rounded-2xl bg-gradient-to-r from-rose-500 to-pink-500 hover:from-rose-600 hover:to-pink-600 text-white font-semibold text-xs sm:text-sm transition-all shadow-xl shadow-rose-500/25 flex items-center gap-2.5 shrink-0 cursor-pointer active:scale-98"
      >
        <FileSpreadsheet className="w-4 h-4" />
        Executive Programme Report
      </button>
    </div>
  );
}
