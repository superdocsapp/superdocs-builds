import { useState, useEffect, useMemo } from 'react';
import { ProposedChangeBatch, ProposedChange } from '../types/superdocs';

const OPERATION_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  replace: { bg: 'bg-primary-50', text: 'text-primary-700', border: 'border-primary-400', label: 'Replace' },
  insert: { bg: 'bg-green-50', text: 'text-green-700', border: 'border-green-200', label: 'Insert' },
  delete: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200', label: 'Delete' },
  move: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', label: 'Move' },
};

function formatHtmlSnippet(html: string): string {
  return html.replace(/</g, '<').replace(/>/g, '>').slice(0, 400);
}

interface ChangeItemProps {
  change: ProposedChange;
  isSelected: boolean;
  onToggle: (changeId: string) => void;
  disabled?: boolean;
}

function ChangeItem({ change, isSelected, onToggle, disabled }: ChangeItemProps) {
  const opStyle = OPERATION_STYLES[change.operation] || {
    bg: 'bg-gray-50',
    text: 'text-gray-700',
    border: 'border-gray-200',
    label: change.operation,
  };

  return (
    <div
      className={`border rounded-xl p-4 transition-all card-hover ${
        isSelected
          ? `${opStyle.border} bg-white shadow-sm ring-1 ring-primary-500`
          : 'border-gray-200 bg-gray-50 opacity-80'
      }`}
      aria-label={`Change ${change.change_id}: ${opStyle.label}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id={`change-${change.change_id}`}
            checked={isSelected}
            disabled={disabled}
            onChange={() => onToggle(change.change_id)}
            className="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500 cursor-pointer"
          />
          <label htmlFor={`change-${change.change_id}`} className="cursor-pointer flex items-center gap-2">
            <span className={`px-2 py-0.5 text-xs font-semibold rounded-md border ${opStyle.bg} ${opStyle.text} ${opStyle.border}`}>
              {opStyle.label}
            </span>
            <span className="text-xs text-gray-400 font-mono">{change.change_id}</span>
          </label>
        </div>
        <span className={`text-[11px] px-2.5 py-0.5 rounded-full font-semibold ${isSelected ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-600'}`}>
          {isSelected ? 'Included in approval' : 'Excluded'}
        </span>
      </div>

      {change.ai_explanation && (
        <p className="text-sm text-gray-700 mb-3 font-normal">{change.ai_explanation}</p>
      )}

      {(change.old_html || change.new_html) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          {change.old_html && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1.5">
                <svg className="w-4 h-4 text-red-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
                <span className="font-semibold text-red-700">Removed</span>
              </div>
              <pre className="whitespace-pre-wrap text-red-800 max-h-40 overflow-auto font-mono text-xs">
                {formatHtmlSnippet(change.old_html)}{change.old_html.length > 400 ? '...' : ''}
              </pre>
            </div>
          )}
          {change.new_html && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1.5">
                <svg className="w-4 h-4 text-green-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                <span className="font-semibold text-green-700">Added</span>
              </div>
              <pre className="whitespace-pre-wrap text-green-800 max-h-40 overflow-auto font-mono text-xs">
                {formatHtmlSnippet(change.new_html)}{change.new_html.length > 400 ? '...' : ''}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ReviewTabProps {
  proposedChanges: ProposedChangeBatch | undefined;
  onApprove: (approved: boolean, changes: ProposedChange[]) => void;
  onContinue: (continueJob: boolean) => void;
  disabled: boolean;
  step: string;
}

export function ReviewTab({ 
  proposedChanges, 
  onApprove, 
  onContinue, 
  disabled, 
  step,
}: ReviewTabProps) {
  const allChanges = useMemo(() => proposedChanges?.changes || [], [proposedChanges]);

  // Default to selecting all changes initially
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(allChanges.map(c => c.change_id))
  );

  const [viewMode, setViewMode] = useState<'diffs' | 'preview'>('diffs');

  // Sync selectedIds when proposedChanges batch changes
  useEffect(() => {
    setSelectedIds(new Set(allChanges.map(c => c.change_id)));
  }, [allChanges]);

  const handleToggle = (changeId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(changeId)) {
        next.delete(changeId);
      } else {
        next.add(changeId);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedIds(new Set(allChanges.map(c => c.change_id)));
  };

  const handleDeselectAll = () => {
    setSelectedIds(new Set());
  };

  const selectedChanges = useMemo(
    () => allChanges.filter(c => selectedIds.has(c.change_id)),
    [allChanges, selectedIds]
  );

  // Synthesize live document HTML preview based on selected changes
  const synthesizedPreviewHtml = useMemo(() => {
    return selectedChanges
      .map(c => c.new_html || (c.operation === 'delete' ? '' : c.old_html || ''))
      .filter(Boolean)
      .join('\n\n');
  }, [selectedChanges]);

  if (!proposedChanges || proposedChanges.changes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-gray-500">
        <div className="w-16 h-16 bg-gray-100 rounded-2xl flex items-center justify-center mb-4 shadow-sm">
          <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <p className="text-gray-800 font-semibold text-base">No proposed changes</p>
        <p className="text-sm text-gray-500 mt-1 max-w-xs text-center">
          {step === 'polling' && 'Waiting for SuperDocs to process...'}
          {step === 'generating' && 'Generating initial document...'}
          {step === 'awaiting_approval' && 'Changes will appear here when ready for review'}
          {step === 'completed' && 'Document generation completed'}
        </p>
      </div>
    );
  }

  const isProcessing = ['polling', 'generating', 'approving'].includes(step);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900 text-sm">
              {allChanges.length} Proposed Change{allChanges.length !== 1 ? 's' : ''}
            </span>
            <span className="text-xs bg-primary-100 text-primary-800 font-semibold px-2.5 py-0.5 rounded-full">
              {selectedChanges.length} of {allChanges.length} Selected
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {proposedChanges.awaiting_kind === 'continue'
              ? 'SuperDocs is asking to continue generation'
              : 'Select changes to cherry-pick approval'}
          </p>
        </div>

        {/* View Mode & Selection Controls */}
        <div className="flex items-center gap-2">
          <div className="bg-gray-100 p-0.5 rounded-lg flex items-center border border-gray-200">
            <button
              type="button"
              onClick={() => setViewMode('diffs')}
              className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-all ${viewMode === 'diffs' ? 'bg-white text-primary-700 shadow-xs' : 'text-gray-600 hover:text-gray-900'}`}
            >
              Diffs ({allChanges.length})
            </button>
            <button
              type="button"
              onClick={() => setViewMode('preview')}
              className={`px-2.5 py-1 text-xs font-semibold rounded-md transition-all ${viewMode === 'preview' ? 'bg-white text-primary-700 shadow-xs' : 'text-gray-600 hover:text-gray-900'}`}
            >
              Live Preview
            </button>
          </div>

          {step === 'awaiting_approval' && (
            <div className="flex items-center gap-1.5 text-xs">
              <button
                type="button"
                onClick={handleSelectAll}
                disabled={disabled || selectedChanges.length === allChanges.length}
                className="px-2.5 py-1 text-xs font-semibold text-gray-700 bg-gray-50 border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                Select All
              </button>
              <button
                type="button"
                onClick={handleDeselectAll}
                disabled={disabled || selectedChanges.length === 0}
                className="px-2.5 py-1 text-xs font-semibold text-gray-700 bg-gray-50 border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                Deselect All
              </button>
            </div>
          )}
        </div>

        {proposedChanges.continue_prompt && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-900 w-full sm:w-auto">
            <div className="flex items-start gap-2">
              <svg className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-amber-900">{String(proposedChanges.continue_prompt)}</span>
            </div>
          </div>
        )}
      </div>

      {/* Main Content: Diffs List or Live Preview */}
      {viewMode === 'diffs' ? (
        <div className="space-y-3 max-h-[500px] overflow-auto pr-1" role="list" aria-label="Proposed changes">
          {allChanges.map((change) => (
            <ChangeItem
              key={change.change_id}
              change={change}
              isSelected={selectedIds.has(change.change_id)}
              onToggle={handleToggle}
              disabled={disabled || step !== 'awaiting_approval'}
            />
          ))}
        </div>
      ) : (
        <div className="border border-gray-200 rounded-xl p-5 bg-white shadow-xs max-h-[500px] overflow-auto">
          <div className="flex items-center justify-between mb-3 border-b border-gray-200 pb-2">
            <span className="text-xs font-bold text-gray-800 uppercase tracking-wider">Live Document Preview ({selectedChanges.length} Selected Chunks)</span>
            <span className="text-[11px] text-gray-400 font-mono">Dynamically updated</span>
          </div>
          {synthesizedPreviewHtml ? (
            <pre className="whitespace-pre-wrap text-xs font-mono text-gray-800 bg-gray-50 p-4 rounded-lg border border-gray-200 max-h-[400px] overflow-auto">
              {synthesizedPreviewHtml}
            </pre>
          ) : (
            <div className="py-12 text-center text-gray-400 text-xs">
              No change chunks selected. Select change chunks in the diff list to preview the document.
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-col sm:flex-row gap-3 pt-3 border-t border-gray-200">
        {step === 'awaiting_approval' && (
          <div className="flex flex-col sm:flex-row gap-2 w-full sm:flex-1">
            <button
              onClick={() => onApprove(true, selectedChanges)}
              disabled={disabled || selectedChanges.length === 0}
              className="flex-1 px-4 py-2.5 bg-green-600 text-white rounded-xl font-semibold hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-green-500 focus:ring-offset-2 flex items-center justify-center gap-2 shadow-xs"
              aria-label={`Approve ${selectedChanges.length} selected changes`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Approve Selected ({selectedChanges.length})</span>
            </button>
            <button
              onClick={() => onApprove(false, allChanges)}
              disabled={disabled}
              className="px-4 py-2.5 bg-red-600 text-white rounded-xl font-semibold hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-red-500 focus:ring-offset-2 flex items-center justify-center gap-2 shadow-xs"
              aria-label="Reject all changes"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
              <span>Reject All</span>
            </button>
          </div>
        )}
        
        {proposedChanges.awaiting_kind === 'continue' && (
          <div className="flex flex-col sm:flex-row gap-2 w-full sm:flex-1">
            <button
              onClick={() => onContinue(true)}
              disabled={disabled}
              className="flex-1 px-4 py-2.5 bg-primary-600 text-white rounded-xl font-semibold hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 flex items-center justify-center gap-2 shadow-xs"
              aria-label="Continue"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
              </svg>
              <span>Continue</span>
            </button>
            <button
              onClick={() => onContinue(false)}
              disabled={disabled}
              className="px-4 py-2.5 bg-gray-600 text-white rounded-xl font-semibold hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
              aria-label="Stop"
            >
              Stop
            </button>
          </div>
        )}
        
        {step === 'completed' && (
          <div className="flex-1 text-center text-green-600 font-semibold flex items-center justify-center py-2 bg-green-50 rounded-xl border border-green-200">
            <svg className="w-5 h-5 inline mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Document generation complete
          </div>
        )}
        
        {isProcessing && (
          <div className="flex-1 text-center text-gray-500 font-medium flex items-center justify-center py-2">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600 mr-2" />
            Processing...
          </div>
        )}
      </div>
    </div>
  );
}