import React, { useState } from 'react';
import { X, Upload, FileText, Loader2, CheckCircle2 } from 'lucide-react';

interface UploadClientModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUpload: (file: File | null, rawText: string) => Promise<void>;
}

export const UploadClientModal: React.FC<UploadClientModalProps> = ({
  isOpen,
  onClose,
  onUpload
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pastedText, setPastedText] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile && !pastedText.trim()) return;

    setErrorMsg(null);
    setIsUploading(true);
    try {
      await onUpload(selectedFile, pastedText);
      setSelectedFile(null);
      setPastedText('');
      onClose();
    } catch (err: any) {
      console.error('Upload failed:', err);
      setErrorMsg(err.message || 'Failed to parse uploaded tax document. Please verify file format.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleSampleInsert = () => {
    setPastedText(
      `FORM 1040 - U.S. INDIVIDUAL INCOME TAX RETURN (2024)\nName: Stellar Tech Solutions LLC (Alex Rivera)\nSSN/EIN: xx-xxx4910\nFiling Status: Single / S-Corp Owner\nSchedule C Net Profit: $310,000 (Line 31)\nSection 179 Expense Deduction: $55,000 (Form 4562, Line 12)\nQBI Deduction: $62,000 (Form 1040, Line 13)\nEntities Involved: Stellar Tech Solutions LLC\nPrior Schedules: Schedule C, Schedule SE, Form 4562, Form 8995`
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-6 text-white">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center space-x-2">
            <Upload className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-bold">Upload Prior Year Tax Return / Document</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {errorMsg && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs font-medium">
              {errorMsg}
            </div>
          )}
          {/* File Upload Box */}
          <div className="border-2 border-dashed border-slate-800 hover:border-blue-500/50 rounded-xl p-6 text-center space-y-2 bg-slate-950 transition-colors cursor-pointer relative">
            <input
              type="file"
              accept=".pdf,.txt,.doc,.docx"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              className="absolute inset-0 opacity-0 cursor-pointer"
            />
            <FileText className="w-8 h-8 text-blue-400 mx-auto" />
            <div className="text-xs font-medium text-slate-300">
              {selectedFile ? (
                <span className="text-emerald-400 font-bold">{selectedFile.name}</span>
              ) : (
                'Drop tax return PDF / TXT here or click to select file'
              )}
            </div>
            <p className="text-[10px] text-slate-500">Supports PDF, TXT, or scanned tax return text</p>
          </div>

          <div className="text-center text-xs text-slate-500 uppercase font-bold">- OR Paste Raw Text -</div>

          {/* Raw Text Input */}
          <div className="space-y-1">
            <div className="flex justify-between items-center">
              <label className="text-xs text-slate-400">Tax Return Text / Excerpt:</label>
              <button
                type="button"
                onClick={handleSampleInsert}
                className="text-[11px] text-blue-400 hover:underline"
              >
                Insert Sample S-Corp Return
              </button>
            </div>
            <textarea
              value={pastedText}
              onChange={(e) => setPastedText(e.target.value)}
              placeholder="Paste Form 1040, Schedule C, Schedule E, or W-2 text..."
              rows={5}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
            />
          </div>

          <div className="flex items-center justify-end space-x-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={(!selectedFile && !pastedText.trim()) || isUploading}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold shadow-md transition-colors"
            >
              {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              <span>Extract & Pre-fill Client</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
