import React from "react";
import { AlertTriangle } from "lucide-react";

interface BackendOfflineAlertProps {
  error: string;
  onRetry: () => void;
}

export function BackendOfflineAlert({ error, onRetry }: BackendOfflineAlertProps) {
  return (
    <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-rose-300 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
        <div>
          <p className="text-xs font-semibold text-white">Backend Connection Required</p>
          <p className="text-xs text-rose-300/80">{error}</p>
        </div>
      </div>
      <button
        onClick={onRetry}
        className="px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-xs font-semibold text-white border border-rose-500/30 transition-colors cursor-pointer"
      >
        Retry
      </button>
    </div>
  );
}
