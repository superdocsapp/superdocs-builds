import React from 'react';
import { X, Printer, Download, Copy, Check } from 'lucide-react';
import { ClientBatchRecord } from '../types';
import { buildExportContent } from '../services/exportContent';

interface PrintExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  client: ClientBatchRecord | null;
  exportType: 'organizer' | 'letter';
  onExported?: (checkpoint: any) => void;
}

export const PrintExportModal: React.FC<PrintExportModalProps> = ({
  isOpen,
  onClose,
  client,
  exportType,
  onExported
}) => {
  const [copied, setCopied] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);
  const [exportMsg, setExportMsg] = React.useState<string | null>(null);

  if (!isOpen || !client) return null;

  // Use the SAME builder the server export uses, so Copy Raw Text, Download .MD,
  // and Print Page all reflect approved edits -- consistent with "Export via
  // SuperDocs". Previously this rebuilt the base letter inline and omitted the
  // approved diffs, so those three actions silently dropped the CPA's edits.
  const contentText = buildExportContent(client, exportType);

  const handlePrint = () => {
    // The browser stamps document.title into the print header and uses it as
    // the default PDF filename. Temporarily set it to a client-specific,
    // professional title so a printed CPA letter doesn't show the app's own
    // name in the header, then restore it afterward.
    const originalTitle = document.title;
    const docLabel = exportType === 'letter' ? 'Year-End Tax Law Letter' : 'Tax Organizer';
    document.title = `${client.clientName} - ${docLabel} (2025 Planning)`;

    // Isolate what gets printed. Rather than trying to hide the whole app around
    // a deeply-nested modal (which previously left layout space that paginated
    // into a duplicated second sheet), copy the document text into #print-portal
    // -- a direct child of <body>, sibling of #root -- and let print CSS show
    // ONLY that. Guarantees the document prints exactly once, with no chrome.
    const portal = document.getElementById('print-portal');
    if (portal) portal.textContent = contentText;
    document.documentElement.classList.add('printing');

    const restore = () => {
      document.title = originalTitle;
      document.documentElement.classList.remove('printing');
      if (portal) portal.textContent = '';
      window.removeEventListener('afterprint', restore);
    };
    window.addEventListener('afterprint', restore);
    window.print();
    // Fallback restore in case afterprint doesn't fire (some browsers).
    setTimeout(restore, 1000);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(contentText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Export via the SERVER route, which (when a live SuperDocs session exists
  // for this client) calls the real POST /v1/documents/export and returns the
  // rendered file as `remoteFile`. This is the only path that exercises the
  // real SuperDocs export API -- the Download .MD button is a purely local
  // browser download and never touches SuperDocs.
  const handleServerExport = async () => {
    if (!client) return;
    setExporting(true);
    setExportMsg(null);
    try {
      const res = await fetch(`/api/documents/${client.id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exportType, exportedBy: 'CPA_Reviewer' })
      });
      const data = await res.json();
      // Download the FINISHED, EDITED document (approved diffs applied) -- this
      // is what "export the finished file" means. The real SuperDocs export
      // call still runs server-side (contract exercised + logged); we report
      // whether it was confirmed, but the file the user gets is the edited
      // letter/organizer, not the raw uploaded source SuperDocs holds.
      const finished = data.content || contentText;
      const blob = new Blob([finished], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${client.clientName.replace(/\s+/g, '_')}_${exportType}_finished.md`;
      a.click();
      URL.revokeObjectURL(url);
      // Refresh the parent's checkpoint so the export event shows immediately
      // in the on-screen decision log (it's already persisted server-side).
      if (data.checkpoint && onExported) onExported(data.checkpoint);
      if (data.remoteExportConfirmed) {
        setExportMsg('Finished document downloaded (approved edits applied). Real SuperDocs export API call confirmed ✓.');
      } else {
        setExportMsg('Finished document downloaded (approved edits applied). No live SuperDocs session for this client, so the remote export call was skipped — upload this client from a real file to exercise it.');
      }
    } catch (err) {
      setExportMsg('Export request failed; see console.');
      console.error('Server export error:', err);
    } finally {
      setExporting(false);
    }
  };

  const handleDownloadMarkdown = () => {
    const blob = new Blob([contentText], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${client.clientName.replace(/\s+/g, '_')}_${exportType}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-6 text-white max-h-[90vh] flex flex-col">
        <div className="no-print flex items-center justify-between border-b border-slate-800 pb-4">
          <h2 className="text-lg font-bold">
            Export & Print: {client.clientName} ({exportType === 'letter' ? 'Year-End Letter' : 'Tax Organizer'})
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto bg-slate-950 p-4 rounded-xl border border-slate-800 font-mono text-xs whitespace-pre-wrap leading-relaxed text-slate-200">
          {contentText}
        </div>

        <div className="no-print flex items-center justify-between border-t border-slate-800 pt-4">
          <button
            onClick={handleCopy}
            className="flex items-center space-x-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors"
          >
            {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            <span>{copied ? 'Copied!' : 'Copy Raw Text'}</span>
          </button>

          <div className="flex items-center space-x-3">
            <button
              onClick={handleServerExport}
              disabled={exporting}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-xs font-semibold shadow-md transition-colors"
            >
              <Download className="w-4 h-4" />
              <span>{exporting ? 'Exporting…' : 'Export via SuperDocs'}</span>
            </button>

            <button
              onClick={handleDownloadMarkdown}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-colors"
            >
              <Download className="w-4 h-4" />
              <span>Download .MD (local)</span>
            </button>

            <button
              onClick={handlePrint}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-md transition-colors"
            >
              <Printer className="w-4 h-4" />
              <span>Print Page</span>
            </button>
          </div>
        </div>

        {exportMsg && (
          <p className="no-print text-xs text-slate-400 pt-2 border-t border-slate-800/60">{exportMsg}</p>
        )}
      </div>
    </div>
  );
};
