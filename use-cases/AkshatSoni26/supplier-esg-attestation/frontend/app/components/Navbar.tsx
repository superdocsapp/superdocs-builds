"use client";

import React from "react";
import {
  FileText,
  RefreshCw,
  FileSpreadsheet,
  Building2,
  BarChart3,
  FileCheck2,
} from "lucide-react";
import { config } from "../config";

export type DashboardTab = "operations" | "analytics" | "audit";

interface NavbarProps {
  onRefresh: () => void;
  onOpenReport: () => void;
  loading: boolean;
  activeTab: DashboardTab;
  setActiveTab: (tab: DashboardTab) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  onRefresh,
  onOpenReport,
  loading,
  activeTab,
  setActiveTab,
}) => {
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 glass-panel backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Left: SuperDocs Brand & Task Title */}
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-rose-500 to-pink-500 p-0.5 shadow-lg shadow-rose-500/20 flex items-center justify-center">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <FileText className="w-5 h-5 text-rose-400" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-lg tracking-tight text-white flex items-center gap-1.5">
                {config.app.brandName} <span className="text-rose-400 font-medium">ESG Attestation Engine</span>
              </h1>
              <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-rose-500/15 text-rose-300 border border-rose-500/30">
                Cycle · {config.app.defaultCycleYear}
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              {config.app.tagline}
            </p>
          </div>
        </div>

        {/* Center: 3-Tab Navigation Switcher */}
        <div className="flex items-center gap-1.5 p-1 bg-slate-900/90 rounded-2xl border border-white/10 text-xs">
          <button
            onClick={() => setActiveTab("operations")}
            className={`px-3.5 py-1.5 rounded-xl font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "operations"
                ? "bg-rose-500 text-white font-semibold shadow-md shadow-rose-500/20"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Building2 className="w-3.5 h-3.5" />
            <span>Supplier Operations</span>
          </button>

          <button
            onClick={() => setActiveTab("analytics")}
            className={`px-3.5 py-1.5 rounded-xl font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "analytics"
                ? "bg-rose-500 text-white font-semibold shadow-md shadow-rose-500/20"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Executive Analytics</span>
          </button>

          <button
            onClick={() => setActiveTab("audit")}
            className={`px-3.5 py-1.5 rounded-xl font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "audit"
                ? "bg-rose-500 text-white font-semibold shadow-md shadow-rose-500/20"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <FileCheck2 className="w-3.5 h-3.5" />
            <span>Compliance & Audit Hub</span>
          </button>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenReport}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-rose-500 to-pink-500 hover:from-rose-600 hover:to-pink-600 text-white font-semibold text-xs transition-all shadow-lg shadow-rose-500/25 flex items-center gap-2 cursor-pointer active:scale-98"
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Executive Report</span>
          </button>

          <button
            onClick={onRefresh}
            disabled={loading}
            className="p-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-white transition-all flex items-center gap-1.5 text-xs cursor-pointer disabled:opacity-50"
            title="Refresh Data"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-rose-400" : ""}`} />
            <span className="hidden lg:inline font-medium">Refresh</span>
          </button>
        </div>
      </div>
    </header>
  );
};
