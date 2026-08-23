import React from 'react';
import {
  Database,
  Cpu,
  FileText,
  Upload,
  MessageSquare,
  CheckSquare,
  Printer,
  ShieldCheck,
  GitBranch,
  Workflow
} from 'lucide-react';

export const ArchitectureDiagram: React.FC = () => {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6 text-white">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-2">
          <Workflow className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-bold tracking-tight">SuperDocs Batch Engine Architecture & API Flow</h2>
        </div>
        <span className="px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          SuperDocs REST V1 Specification Compliant
        </span>
      </div>

      {/* 4-Step REST API Flow Diagram */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Official 4-Step SuperDocs REST API Contract
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-950 border border-blue-500/30 space-y-2 relative">
            <div className="flex items-center space-x-2 text-blue-400 font-bold text-xs">
              <Upload className="w-4 h-4" />
              <span>1. POST /api/documents/upload</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Ingests prior 2024 returns (PDF/TXT), extracts schedules & line citations with Gemini.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-950 border border-indigo-500/30 space-y-2 relative">
            <div className="flex items-center space-x-2 text-indigo-400 font-bold text-xs">
              <MessageSquare className="w-4 h-4" />
              <span>2. POST /api/documents/:id/chat</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Processes CPA natural language edit instructions to generate itemized, targeted proposed diffs.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-950 border border-amber-500/30 space-y-2 relative">
            <div className="flex items-center space-x-2 text-amber-400 font-bold text-xs">
              <CheckSquare className="w-4 h-4" />
              <span>3. POST /api/documents/:id/approve</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Human-in-the-loop gate: CPA approves/rejects proposed line edits before document commitment.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-950 border border-emerald-500/30 space-y-2 relative">
            <div className="flex items-center space-x-2 text-emerald-400 font-bold text-xs">
              <Printer className="w-4 h-4" />
              <span>4. POST /api/documents/:id/export</span>
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Exports finished printable PDF / interactive fillable markdown package with audit logs.
            </p>
          </div>
        </div>
      </div>

      {/* Layer Architecture Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2 text-xs">
          <div className="font-bold text-blue-400 flex items-center space-x-1.5">
            <Cpu className="w-4 h-4" />
            <span>AI Reasoning & Grounding Layer</span>
          </div>
          <ul className="space-y-1 text-slate-300 font-mono text-[11px] list-disc list-inside">
            <li>Gemini 3.6 Flash structured schema parsing</li>
            <li>Line citation grounding (e.g. Schedule C, Line 31)</li>
            <li>2025 IRC tax law updates matcher engine</li>
            <li>Targeted diff extraction (Addition/Modification)</li>
          </ul>
        </div>

        <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2 text-xs">
          <div className="font-bold text-indigo-400 flex items-center space-x-1.5">
            <GitBranch className="w-4 h-4" />
            <span>Agentic Batch Pipeline</span>
          </div>
          <ul className="space-y-1 text-slate-300 font-mono text-[11px] list-disc list-inside">
            <li>8-Stage sequential & parallel execution</li>
            <li>Checkpoint state persistence & recovery</li>
            <li>Missing items document reconciliation</li>
            <li>Tailored client follow-up draft generator</li>
          </ul>
        </div>

        <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2 text-xs">
          <div className="font-bold text-emerald-400 flex items-center space-x-1.5">
            <Database className="w-4 h-4" />
            <span>Persistence & Audit Trail</span>
          </div>
          <ul className="space-y-1 text-slate-300 font-mono text-[11px] list-disc list-inside">
            <li>Durable JSON / PostgreSQL schema store</li>
            <li>Timestamped CPA audit log history</li>
            <li>Versioned document diff tracking</li>
            <li>Zero-data-loss checkpoint recovery</li>
          </ul>
        </div>
      </div>
    </div>
  );
};
