const STEPS = [
  { key: 'uploading', label: 'Upload', icon: 'M4 16l4.586-4.586a2 2 0 012.828 0L16 12l-4.586-4.586a2 2 0 00-2.828 0L10 12l-4.586 4.586a2 2 0 002.828 0L20 12' },
  { key: 'generating', label: 'Generate', icon: 'M10 20l4-16m4 4l4 4-4 4M6 16l4 4 4-4' },
  { key: 'polling', label: 'Process', icon: 'M12 4v16m8-8H4' },
  { key: 'awaiting_approval', label: 'Review', icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.062-.382-3.04z' },
  { key: 'approving', label: 'Apply', icon: 'M5 13l4 4L19 7' },
  { key: 'exporting', label: 'Export', icon: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12' },
  { key: 'saving', label: 'Save', icon: 'M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-1l-4-4H5a2 2 0 00-2 2v9a2 2 0 002 2z' },
  { key: 'completed', label: 'Done', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
];

const STEP_ORDER = ['uploading', 'generating', 'polling', 'awaiting_approval', 'approving', 'exporting', 'saving', 'completed'];

interface StatusBadgeProps {
  step: string;
  progress?: string;
  error?: string;
  canRetry?: boolean;
  sessionId?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function StatusBadge({ step, progress, error, canRetry, sessionId, onRetry, onDismiss }: StatusBadgeProps) {
  const stepInfo = STEPS.find(s => s.key === step);
  const currentIndex = STEP_ORDER.indexOf(step);

  const isActive = step !== 'idle' && step !== 'completed' && step !== 'failed';

  return (
    <div className="p-3.5 rounded-xl border border-gray-200 bg-white shadow-xs">
      {/* Progress workflow */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-gray-100 text-gray-800 border border-gray-200">
              {stepInfo?.label || step}
            </span>
            {sessionId && (
              <span className="text-xs text-gray-400 font-mono hidden sm:inline" title={`SuperDocs Session: ${sessionId}`}>
                Session: {sessionId.slice(0, 8)}...
              </span>
            )}
          </div>
          {progress && <span className="text-xs text-gray-600 truncate max-w-xs">{progress}</span>}
        </div>
        
        {/* Progress indicator */}
        <div className="flex items-center gap-1" role="progressbar" aria-valuenow={currentIndex + 1} aria-valuemin={1} aria-valuemax={STEP_ORDER.length} aria-label="Generation progress">
          {STEP_ORDER.map((stepKey, index) => {
            const isCompleted = index < currentIndex;
            const isCurrent = index === currentIndex && isActive;

            return (
              <div key={stepKey} className="flex items-center">
                <div className="relative flex-shrink-0">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold transition-all ${
                    isCompleted ? 'bg-primary-600 text-white' :
                    isCurrent ? 'bg-primary-600 text-white animate-pulse' :
                    'bg-gray-200 text-gray-400'
                  }`}>
                    {isCompleted && (
                      <svg className="w-3.5 h-3.5 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {!isCompleted && !isCurrent && (
                      <span className="mx-auto">{index + 1}</span>
                    )}
                  </div>
                </div>
                {index < STEP_ORDER.length - 1 && (
                  <div className={`w-8 h-0.5 mx-1 transition-colors ${
                    index < currentIndex ? 'bg-primary-600' : 'bg-gray-200'
                  }`} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Current step label */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className={`px-2.5 py-0.5 rounded-full font-semibold ${
            step === 'failed' ? 'bg-red-100 text-red-700' :
            step === 'completed' ? 'bg-green-100 text-green-700' :
            step === 'idle' ? 'bg-gray-100 text-gray-700' :
            'bg-primary-100 text-primary-700'
          }`}>
            {stepInfo?.label || step}
          </span>
          {progress && <span className="text-gray-600">{progress}</span>}
        </div>
        {isActive && (
          <span className="text-primary-600 animate-pulse font-mono text-[10px] font-bold">● ACTIVE</span>
        )}
      </div>
      
      {error && (
        <div className="mt-2.5 p-3 text-xs text-red-700 bg-red-50 rounded-xl border border-red-200 flex items-start gap-2 animate-fade-in" role="alert">
          <svg className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.36 0L3.36 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span className="text-red-700 font-medium flex-1">Error: {error}</span>
          {canRetry && onRetry && (
            <button
              onClick={onRetry}
              className="px-3 py-1 text-xs font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors focus:ring-2 focus:ring-red-500 focus:ring-offset-2 cursor-pointer shadow-xs"
              aria-label="Retry"
            >
              Retry
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="px-3 py-1 text-xs font-semibold bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 cursor-pointer"
              aria-label="Dismiss"
            >
              Dismiss
            </button>
          )}
        </div>
      )}
    </div>
  );
}