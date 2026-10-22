import { useState, useCallback } from 'react';

interface ExportTabProps {
  onExport: (format: 'pdf' | 'docx', destination: string) => Promise<void>;
  checkFileExists: (path: string) => Promise<boolean>;
  disabled: boolean;
  step: string;
  defaultDestination: string;
}

export function ExportTab({ onExport, checkFileExists, disabled, step, defaultDestination }: ExportTabProps) {
  const [format, setFormat] = useState<'pdf' | 'docx'>('pdf');
  const [destination, setDestination] = useState(defaultDestination);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingExport, setPendingExport] = useState<{ format: 'pdf' | 'docx'; destination: string } | null>(null);

  const checkAndExport = useCallback(async () => {
    if (disabled || exporting) return;

    const exists = await checkFileExists(destination);

    if (exists) {
      setPendingExport({ format, destination });
      setShowConfirm(true);
      return;
    }

    await doExport(format, destination);
  }, [disabled, exporting, destination, format, checkFileExists]);

  const confirmExport = useCallback(async () => {
    if (!pendingExport) return;

    await doExport(pendingExport.format, pendingExport.destination);
    setShowConfirm(false);
    setPendingExport(null);
  }, [pendingExport]);

  const cancelExport = useCallback(() => {
    setShowConfirm(false);
    setPendingExport(null);
  }, []);

  const doExport = async (fmt: 'pdf' | 'docx', dest: string) => {
    setExporting(true);
    setError(null);
    setSuccess(null);

    try {
      await onExport(fmt, dest);
      setSuccess(`Successfully exported ${fmt.toUpperCase()} to ${dest}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
        <h3 className="text-sm font-bold text-gray-900 mb-1">Export Document</h3>
        <p className="text-xs text-gray-500">Export the finished document and save it to your workspace filesystem.</p>
      </div>

      {/* Format Selection */}
      <div className="mb-4">
        <label className="block text-xs font-semibold text-gray-700 mb-2">Export Format</label>
        <div className="grid grid-cols-2 gap-3" role="radiogroup" aria-label="Export format">
          {['pdf', 'docx'].map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={format === f}
              onClick={() => setFormat(f as 'pdf' | 'docx')}
              className={`relative flex-1 rounded-xl border-2 p-4 text-center transition-all card-hover cursor-pointer ${
                format === f
                  ? 'border-primary-500 bg-primary-50 text-primary-700 shadow-sm ring-1 ring-primary-500'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 shadow-xs'
              }`}
            >
              <div className="font-bold text-sm">{f.toUpperCase()}</div>
              <div className="text-xs text-gray-500 mt-1">
                {f === 'pdf' ? 'Portable Document Format' : 'Microsoft Word Document'}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Destination */}
      <div className="mb-4">
        <label className="block text-xs font-semibold text-gray-700 mb-2">Destination Path</label>
        <input
          type="text"
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          placeholder="e.g., docs/README.pdf"
          className="w-full px-3.5 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-xs font-mono transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-white"
          disabled={disabled || exporting}
        />
        <p className="text-[11px] text-gray-500 mt-1.5">
          Path relative to project root. Parent directories will be created automatically in your Repl.
        </p>
      </div>

      {/* Error/Success */}
      {error && (
        <div className="p-3.5 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-start gap-2 animate-fade-in" role="alert">
          <svg className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.36 0L3.36 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span className="text-red-700 font-medium">Error: {error}</span>
        </div>
      )}

      {success && (
        <div className="p-3.5 bg-green-50 border border-green-200 rounded-xl text-xs text-green-700 flex items-start gap-2 animate-fade-in" role="status">
          <svg className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <span className="text-green-700 font-semibold">{success}</span>
        </div>
      )}

      {/* Overwrite Confirmation */}
      {showConfirm && pendingExport && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="flex items-start gap-3">
            <svg className="w-6 h-6 text-amber-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.36 0L3.36 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <h4 id="confirm-title" className="font-bold text-amber-900 text-sm">File already exists</h4>
              <p className="text-xs text-amber-800 mt-1">
                <strong className="font-mono">{pendingExport.destination}</strong> already exists. Overwrite it?
              </p>
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={confirmExport}
              disabled={exporting}
              className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg text-xs font-semibold hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-red-500 focus:ring-offset-2 shadow-xs"
            >
              Overwrite
            </button>
            <button
              onClick={cancelExport}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg text-xs font-semibold hover:bg-gray-700 focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Export Button */}
      <button
        onClick={checkAndExport}
        disabled={disabled || exporting || step !== 'completed' || showConfirm}
        className="w-full px-4 py-3 bg-primary-600 text-white rounded-xl font-semibold hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 shadow-sm flex items-center justify-center gap-2"
      >
        {exporting ? (
          <>
            <svg className="animate-spin -ml-1 mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Exporting...
          </>
        ) : step === 'completed' ? (
          `Export & Save ${format.toUpperCase()}`
        ) : (
          'Complete generation first'
        )}
      </button>

      {step !== 'completed' && !showConfirm && (
        <p className="text-center text-xs text-gray-500">
          Complete the document generation and approval process first.
        </p>
      )}
    </div>
  );
}