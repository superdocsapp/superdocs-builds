import React from 'react';
import { Upload, FileText, RefreshCw, X } from 'lucide-react';

export default function AuditorSidebar({
  specFile, setSpecFile,
  cutsheetFile, setCutsheetFile,
  scheduleFile, setScheduleFile,
  isUploading,
  handleStartAnalysis,
  runs,
  activeRunId, setActiveRunId,
  setDownloadUrls
}) {
  return (
    <aside className="w-80 bg-secondary border-r border-borderDark p-6 flex flex-col gap-6 h-full overflow-hidden">
      {/* Upload Form */}
      <div className="bg-cardbg border border-borderDark rounded-xl p-6 shadow-md">
        <h3 className="font-display text-sm font-semibold mb-4 text-white flex items-center gap-2">
          <Upload size={16} className="text-accentGold" /> Ingest Documents
        </h3>
        
        <div className="flex flex-col gap-4">
          {/* Specification Upload */}
          <div>
            <label className="block text-[10px] uppercase font-bold tracking-wider text-gray-500 mb-1.5">1. Specification Section</label>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-secondary border border-borderDark rounded-lg text-xs font-medium text-gray-400 hover:text-white cursor-pointer hover:border-border-hover transition">
                <FileText size={14} />
                <span className="truncate max-w-[120px]">{specFile ? specFile.name : 'Select File'}</span>
                <input type="file" onChange={(e) => setSpecFile(e.target.files[0])} className="hidden" />
              </label>
              {specFile && <button onClick={() => setSpecFile(null)} className="text-gray-500 hover:text-white"><X size={14} /></button>}
            </div>
          </div>

          {/* Proposed Cutsheet Upload */}
          <div>
            <label className="block text-[10px] uppercase font-bold tracking-wider text-gray-500 mb-1.5">2. Proposed Cutsheet</label>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-secondary border border-borderDark rounded-lg text-xs font-medium text-gray-400 hover:text-white cursor-pointer hover:border-border-hover transition">
                <FileText size={14} />
                <span className="truncate max-w-[120px]">{cutsheetFile ? cutsheetFile.name : 'Select File'}</span>
                <input type="file" onChange={(e) => setCutsheetFile(e.target.files[0])} className="hidden" />
              </label>
              {cutsheetFile && <button onClick={() => setCutsheetFile(null)} className="text-gray-500 hover:text-white"><X size={14} /></button>}
            </div>
          </div>

          {/* Finish Schedule Upload */}
          <div>
            <label className="block text-[10px] uppercase font-bold tracking-wider text-gray-500 mb-1.5">3. Finish Schedule</label>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-secondary border border-borderDark rounded-lg text-xs font-medium text-gray-400 hover:text-white cursor-pointer hover:border-border-hover transition">
                <FileText size={14} />
                <span className="truncate max-w-[120px]">{scheduleFile ? scheduleFile.name : 'Select File'}</span>
                <input type="file" onChange={(e) => setScheduleFile(e.target.files[0])} className="hidden" />
              </label>
              {scheduleFile && <button onClick={() => setScheduleFile(null)} className="text-gray-500 hover:text-white"><X size={14} /></button>}
            </div>
          </div>

          <button
            onClick={handleStartAnalysis}
            disabled={isUploading || !specFile || !cutsheetFile || !scheduleFile || activeRunId}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg text-xs font-semibold cursor-pointer transition bg-accentGold text-secondary hover:brightness-110 disabled:opacity-30 disabled:cursor-not-allowed mt-2"
          >
            {isUploading ? <RefreshCw size={14} className="animate-spin" /> : 'Analyze Substitution'}
          </button>
        </div>
      </div>

      {/* Prior Audits History */}
      <div className="flex-1 flex flex-col min-h-0 bg-cardbg border border-borderDark rounded-xl p-6 shadow-md overflow-hidden">
        <h3 className="font-display text-sm font-semibold mb-4 text-white">Audits History</h3>
        <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
          {runs.length === 0 ? (
            <div className="text-center text-xs text-gray-500 py-8">No audits recorded yet.</div>
          ) : (
            runs.map((r) => (
              <div key={r.id} className="p-3 bg-secondary border border-borderDark rounded-lg flex flex-col gap-2 transition hover:border-border-hover">
                <div className="flex justify-between items-start gap-1">
                  <span className="text-[10px] font-mono text-gray-400 truncate max-w-[100px]">ID: {r.id.substring(0, 8)}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-bold border border-borderDark bg-cardbg text-gray-400 uppercase">{r.status}</span>
                </div>
                <div className="text-[10px] text-gray-400 truncate"><b>Spec:</b> {r.spec_filename}</div>
                <div className="text-[10px] text-gray-400 truncate"><b>Sheet:</b> {r.cutsheet_filename}</div>
                <button
                  onClick={() => {
                    setActiveRunId(r.id);
                    setDownloadUrls(null);
                  }}
                  className="w-full text-center py-1.5 bg-cardbg hover:bg-borderDark border border-borderDark rounded text-[10px] text-gray-300 transition"
                >
                  Open Details
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  );
}
