import { useState, useEffect, useCallback } from 'react';
import { DocumentVersion } from '../types/superdocs';

interface HistoryTabProps {
  documentId?: string;
  versions?: DocumentVersion[];
  versionsLoading?: boolean;
  selectedVersion?: DocumentVersion;
  onLoadVersions: () => void;
  onLoadVersion: (versionId: string) => Promise<DocumentVersion | undefined>;
  onRevert: (versionId: string) => Promise<void>;
  disabled?: boolean;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function VersionPreview({ version }: { version: DocumentVersion }) {
  const [expanded, setExpanded] = useState(false);
  const snippet = expanded ? version.html : version.html.slice(0, 600);

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 shadow-xs">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold text-gray-700">HTML Preview</span>
        {version.html.length > 600 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-xs text-primary-600 font-semibold hover:underline focus:outline-none"
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
      <pre className="whitespace-pre-wrap text-xs font-mono text-gray-800 max-h-80 overflow-auto bg-white p-3 rounded-lg border border-gray-200">
        {snippet}{!expanded && version.html.length > 600 ? '...' : ''}
      </pre>
    </div>
  );
}

export function HistoryTab({
  documentId,
  versions,
  versionsLoading,
  selectedVersion,
  onLoadVersions,
  onLoadVersion,
  onRevert,
  disabled,
}: HistoryTabProps) {
  const [revertingId, setRevertingId] = useState<string | null>(null);

  useEffect(() => {
    if (documentId && !versions && !versionsLoading) {
      onLoadVersions();
    }
  }, [documentId, versions, versionsLoading, onLoadVersions]);

  const handlePreview = useCallback(async (versionId: string) => {
    await onLoadVersion(versionId);
  }, [onLoadVersion]);

  const handleRevert = useCallback(async (versionId: string) => {
    setRevertingId(versionId);
    try {
      await onRevert(versionId);
    } finally {
      setRevertingId(null);
    }
  }, [onRevert]);

  if (!documentId) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-gray-500">
        <div className="w-16 h-16 bg-gray-100 rounded-2xl flex items-center justify-center mb-4 shadow-sm">
          <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="text-gray-900 font-bold text-base">No document yet</p>
        <p className="text-xs text-gray-500 mt-1">Generate a document to track its version history.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
        <div>
          <p className="font-bold text-gray-900 text-sm">Document Version History</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {versions ? `${versions.length} version(s) saved` : 'Loading versions...'}
          </p>
        </div>
        <button
          onClick={onLoadVersions}
          disabled={versionsLoading || disabled}
          className="px-3 py-1.5 text-xs font-semibold bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 shadow-xs"
        >
          {versionsLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {versionsLoading && (!versions || versions.length === 0) && (
        <div className="flex items-center gap-2 text-sm text-gray-600 py-8 justify-center">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600" />
          <span>Loading version history...</span>
        </div>
      )}

      {!versionsLoading && versions && versions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-gray-500">
          <p className="text-gray-600 font-medium">No versions found</p>
          <p className="text-sm text-gray-500 mt-1">This document has no saved versions yet.</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Version list */}
        <div className="space-y-2.5 max-h-[600px] overflow-auto pr-1" role="list" aria-label="Document versions">
          {(versions || []).map((version) => (
            <div
              key={version.version_id}
              className={`border rounded-xl p-4 transition-all card-hover ${selectedVersion?.version_id === version.version_id ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500 shadow-sm' : 'border-gray-200 bg-white shadow-xs'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-900 truncate">{version.change_summary || 'Untitled version'}</span>
                    {version.is_current && (
                      <span className="px-2 py-0.5 text-[10px] font-bold bg-green-100 text-green-700 rounded-full border border-green-200">Current</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">{formatDate(version.created_at)}</p>
                  <p className="text-xs text-gray-400 font-mono mt-0.5 truncate">{version.version_id}</p>
                </div>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => handlePreview(version.version_id)}
                  disabled={disabled}
                  className="flex-1 px-3 py-1.5 text-xs font-semibold bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
                >
                  Preview
                </button>
                {!version.is_current && (
                  <button
                    onClick={() => handleRevert(version.version_id)}
                    disabled={disabled || revertingId === version.version_id}
                    className="flex-1 px-3 py-1.5 text-xs font-semibold bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 shadow-xs"
                  >
                    {revertingId === version.version_id ? 'Reverting...' : 'Revert'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Preview pane */}
        <div className="lg:sticky lg:top-0">
          {selectedVersion ? (
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-gray-900">Preview: {selectedVersion.change_summary || selectedVersion.version_id}</span>
              </div>
              <VersionPreview version={selectedVersion} />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full py-16 text-gray-400 border border-dashed border-gray-300 rounded-xl bg-white/50">
              <svg className="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <p className="text-xs font-medium">Select a version to preview</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
