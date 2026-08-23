import React from 'react';
import { X, BookOpen, Tag } from 'lucide-react';
import { CURRENT_TAX_LAW_UPDATES } from '../data/taxLawUpdates';

interface TaxLawDatabaseModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const TaxLawDatabaseModal: React.FC<TaxLawDatabaseModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-3xl w-full p-6 shadow-2xl space-y-6 text-white max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center space-x-2">
            <BookOpen className="w-5 h-5 text-indigo-400" />
            <h2 className="text-lg font-bold">2025/2026 Federal & State Tax Law Changes Database</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {CURRENT_TAX_LAW_UPDATES.map((law) => (
            <div
              key={law.id}
              className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-blue-400">{law.title}</span>
                <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-mono text-[10px] border border-indigo-500/20">
                  {law.codeSection}
                </span>
              </div>

              <p className="text-slate-300 leading-relaxed">{law.summary}</p>

              <div className="flex items-center space-x-2 pt-2 border-t border-slate-900">
                <span className="text-slate-400 font-semibold flex items-center space-x-1">
                  <Tag className="w-3 h-3 text-slate-500" />
                  <span>Target Segments:</span>
                </span>
                <div className="flex flex-wrap gap-1">
                  {law.targetSegments.map((seg) => (
                    <span
                      key={seg}
                      className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 uppercase text-[10px] font-mono border border-slate-700"
                    >
                      {seg}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
