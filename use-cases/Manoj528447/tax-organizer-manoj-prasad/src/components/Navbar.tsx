import React from 'react';
import {
  FileCheck2,
  Cpu,
  Layers,
  Sparkles,
  RotateCcw,
  BookOpen,
  DollarSign,
  Clock,
  ShieldCheck,
  Upload
} from 'lucide-react';
import { BatchRunCheckpoint } from '../types';

interface NavbarProps {
  checkpoint: BatchRunCheckpoint;
  activeTab: 'batch' | 'editor' | 'pipeline' | 'followup';
  setActiveTab: (tab: 'batch' | 'editor' | 'pipeline' | 'followup') => void;
  onReset: () => void;
  onOpenLawDb: () => void;
  onOpenUpload: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  checkpoint,
  activeTab,
  setActiveTab,
  onReset,
  onOpenLawDb,
  onOpenUpload
}) => {
  const isGateActive = checkpoint.currentStage === 'SUPERDOCS_DIFF_GATE';

  return (
    <header className="bg-slate-900/95 backdrop-blur-md border-b border-slate-800/80 text-white sticky top-0 z-40 shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2.5 2xl:py-2">
        <div className="flex flex-col 2xl:flex-row 2xl:items-center 2xl:justify-between gap-3">
          
          {/* Top Row on <xl / Left Section on xl: Logo & Branding */}
          <div className="flex items-center justify-between 2xl:justify-start w-full 2xl:w-auto">
            <div className="flex items-center space-x-3 shrink-0">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 via-blue-500 to-indigo-500 flex items-center justify-center shadow-md shadow-blue-500/25 ring-1 ring-white/20">
                <FileCheck2 className="w-5 h-5 text-white" />
              </div>
              <div className="flex flex-col justify-center">
                <div className="flex items-center space-x-2">
                  <span className="font-bold text-base tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-300 bg-clip-text text-transparent">
                    SuperDocs <span className="text-blue-400 font-semibold">TaxOrganizer</span>
                  </span>
                  <span className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 shrink-0">
                    AI Batch
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 font-normal leading-tight hidden sm:block">
                  Client Tax Organizer & Year-End Letter Batch
                </p>
              </div>
            </div>

            {/* Mobile/Tablet Controls displayed inline with logo */}
            <div className="flex 2xl:hidden items-center space-x-1.5 shrink-0">
              <div className="flex items-center space-x-1 text-xs px-2 py-1 rounded-lg bg-slate-950/80 border border-slate-800 text-slate-300">
                <DollarSign className="w-3 h-3 text-emerald-400" />
                <span className="font-mono text-emerald-400 font-semibold text-[11px]">
                  ${checkpoint.totalCostEstimate.toFixed(4)}
                </span>
              </div>
              <button
                onClick={onOpenUpload}
                className="flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700/80 transition-all"
                title="Upload Tax Return PDF/Text"
              >
                <Upload className="w-3.5 h-3.5 text-blue-400" />
                <span className="hidden sm:inline">Upload</span>
              </button>
              <button
                onClick={onOpenLawDb}
                className="flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700/80 transition-all"
                title="2025/2026 Tax Law Database"
              >
                <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
                <span className="hidden sm:inline">Rules</span>
              </button>
              <button
                onClick={onReset}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                title="Reset Engine Checkpoint"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Center Section: Navigation Tabs */}
          <nav 
            aria-label="Main Navigation"
            className="flex items-center bg-slate-950/80 p-1.5 rounded-xl border border-slate-800/80 space-x-1 overflow-x-auto scrollbar-none justify-start sm:justify-center w-full 2xl:w-auto"
          >
            <button
              onClick={() => setActiveTab('batch')}
              className={`flex items-center space-x-2 px-3 py-1.5 sm:px-3.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 whitespace-nowrap focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${
                activeTab === 'batch'
                  ? 'bg-blue-600 text-white shadow-sm font-semibold'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
              }`}
            >
              <Layers className="w-4 h-4 shrink-0" />
              <span>Client Batch</span>
              <span className={`ml-1 text-[11px] px-1.5 py-0.2 rounded-full ${
                activeTab === 'batch' ? 'bg-blue-700 text-blue-100' : 'bg-slate-800 text-slate-400'
              }`}>
                {checkpoint.clientRecords.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTab('editor')}
              className={`relative flex items-center space-x-2 px-3 py-1.5 sm:px-3.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 whitespace-nowrap focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${
                activeTab === 'editor'
                  ? 'bg-blue-600 text-white shadow-sm font-semibold'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
              }`}
            >
              <Sparkles className="w-4 h-4 text-amber-300 shrink-0" />
              <span>SuperDocs Diff Gate</span>
              {isGateActive && (
                <span className="relative flex h-2 w-2 ml-0.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('pipeline')}
              className={`flex items-center space-x-2 px-3 py-1.5 sm:px-3.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 whitespace-nowrap focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${
                activeTab === 'pipeline'
                  ? 'bg-blue-600 text-white shadow-sm font-semibold'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
              }`}
            >
              <Cpu className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Agent Pipeline</span>
            </button>

            <button
              onClick={() => setActiveTab('followup')}
              className={`flex items-center space-x-2 px-3 py-1.5 sm:px-3.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 whitespace-nowrap focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${
                activeTab === 'followup'
                  ? 'bg-blue-600 text-white shadow-sm font-semibold'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
              }`}
            >
              <ShieldCheck className="w-4 h-4 text-indigo-400 shrink-0" />
              <span>Missing Items</span>
            </button>
          </nav>

          {/* Right Section on xl: Desktop Utility Tools & Compact Status */}
          <div className="hidden 2xl:flex items-center space-x-2.5 shrink-0">
            
            {/* Compact Status Indicator Area */}
            <div className="flex items-center space-x-2 text-xs px-2.5 py-1.5 rounded-lg bg-slate-950/80 border border-slate-800 text-slate-300 shadow-inner">
              <div className="flex items-center space-x-1" title="Engine Status">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span className="text-[11px] font-medium text-slate-300">Ready</span>
              </div>

              <span className="text-slate-800">|</span>

              <div className="flex items-center space-x-1" title="Estimated AI Cost">
                <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                <span className="font-mono text-emerald-400 font-semibold text-xs">
                  ${checkpoint.totalCostEstimate.toFixed(4)}
                </span>
              </div>

              <span className="text-slate-800">|</span>

              <div className="flex items-center space-x-1" title="Execution Time">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                <span className="font-mono text-slate-200 text-xs">
                  {(checkpoint.totalDurationMs / 1000).toFixed(1)}s
                </span>
              </div>
            </div>

            {/* Utility Action Buttons */}
            <div className="flex items-center space-x-1.5">
              <button
                onClick={onOpenUpload}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700/80 hover:border-slate-600 transition-all focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
                title="Upload Tax Return PDF/Text"
              >
                <Upload className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                <span>Upload Return</span>
              </button>

              <button
                onClick={onOpenLawDb}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700/80 hover:border-slate-600 transition-all focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
                title="2025/2026 Tax Law Database"
              >
                <BookOpen className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                <span>Tax Law Rules</span>
              </button>

              <button
                onClick={onReset}
                className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/80 border border-transparent hover:border-slate-700 transition-all focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
                title="Reset Engine Checkpoint"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>

          </div>

        </div>
      </div>
    </header>
  );
};

