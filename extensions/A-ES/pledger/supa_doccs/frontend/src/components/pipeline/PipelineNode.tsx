import { memo, useRef, useEffect, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeStatus } from '@/types/pipeline';
import { STATUS_CONFIG } from '@/utils/pipelineColors';

interface PipelineNodeData {
  label: string;
  status: NodeStatus;
  icon: string;
  overlayMode?: 'none' | 'history' | 'cost';
  historyCount?: number;
  costData?: { time: string; cost: string } | null;
  justTransitioned?: boolean;
  [key: string]: unknown;
}

function NodeIcon({ icon }: { icon: string }) {
  switch (icon) {
    case 'play':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <circle cx="12" cy="12" r="10" />
          <polygon points="10,8 16,12 10,16" fill="currentColor" stroke="none" />
        </svg>
      );
    case 'document':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M7 2h8l5 5v13a2 2 0 01-2 2H7a2 2 0 01-2-2V4a2 2 0 012-2z" />
          <path d="M15 2v5h5" />
          <path d="M9 13h6M9 17h4" />
        </svg>
      );
    case 'download':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M12 3v12m0 0l-4-4m4 4l4-4" />
          <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
        </svg>
      );
    case 'brain':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M12 2a7 7 0 017 7c0 2.5-1.3 4.7-3.2 6l-.8.6V18a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2.4l-.8-.6A7 7 0 0112 2z" />
          <path d="M10 22h4" />
          <path d="M9 9h2m2 0h2" />
        </svg>
      );
    case 'search':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <circle cx="11" cy="11" r="7" />
          <path d="M16 16l4.5 4.5" />
        </svg>
      );
    case 'shield':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M12 3l8 4v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V7l8-4z" />
          <path d="M12 8v4m0 3h.01" />
        </svg>
      );
    case 'check':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
          <path d="M5 12l5 5L20 7" />
        </svg>
      );
    case 'alert':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path d="M12 9v4m0 3h.01M12 3l9.5 16.5H2.5L12 3z" />
        </svg>
      );
    default:
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <circle cx="12" cy="12" r="8" />
        </svg>
      );
  }
}

export const PipelineNode = memo(function PipelineNode({ data }: { data: PipelineNodeData }) {
  const { label, status, icon, overlayMode, historyCount, costData } = data;
  const config = STATUS_CONFIG[status];
  const prevStatusRef = useRef<NodeStatus>(status);
  const [transitioning, setTransitioning] = useState(false);

  // Detect actual status change (from prop diff, not poll tick)
  useEffect(() => {
    if (prevStatusRef.current !== status) {
      setTransitioning(true);
      prevStatusRef.current = status;
      const timer = setTimeout(() => setTransitioning(false), 400);
      return () => clearTimeout(timer);
    }
  }, [status]);

  const displayIcon = transitioning && status === 'complete' ? 'check'
    : transitioning && (status === 'failed' || status === 'escalated') ? 'alert'
    : icon;

  return (
    <div
      className={`
        relative w-[180px] rounded-lg border-t-2 bg-[#141927]/90 backdrop-blur-sm
        px-3 py-3 flex flex-col items-center gap-1.5 cursor-pointer
        hover:bg-[#1a2035]/90
        transition-all duration-300 ease-out
        ${config.border} ${config.glow}
        ${status === 'processing' || status === 'retrying' ? 'node-processing' : ''}
        ${transitioning ? 'scale-[1.03]' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-white/20 !border-white/30" />

      {/* History mode badge */}
      {overlayMode === 'history' && historyCount !== undefined && historyCount > 0 && (
        <div className="absolute -top-2 -right-2 flex items-center justify-center w-5 h-5 rounded-full bg-indigo-500 text-white text-[9px] font-bold shadow-sm shadow-indigo-500/30 z-10">
          {historyCount}
        </div>
      )}

      <div className={`transition-colors duration-300 ${config.text}`}>
        <NodeIcon icon={displayIcon} />
      </div>

      <span className="text-sm font-medium text-white/90">{label}</span>

      {/* Default: status line */}
      {overlayMode !== 'cost' && (
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full transition-colors duration-300 ${config.dot}`} />
          <span className={`text-xs transition-colors duration-300 ${config.text}`}>{config.label}</span>
        </div>
      )}

      {/* Cost mode: time/cost inline */}
      {overlayMode === 'cost' && costData && (
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] font-mono text-violet-300/80">{costData.time}</span>
          <span className="text-white/15">·</span>
          <span className="text-[10px] font-mono text-emerald-300/80">{costData.cost}</span>
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-white/20 !border-white/30" />
    </div>
  );
});

export default PipelineNode;
