import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { NodeStatus } from '@/types/pipeline';
import { STATUS_CONFIG } from '@/utils/pipelineColors';

interface MergeNodeData {
  label: string;
  status: NodeStatus;
  [key: string]: unknown;
}

export const MergeNode = memo(function MergeNode({ data }: { data: MergeNodeData }) {
  const { status } = data;
  const config = STATUS_CONFIG[status];

  return (
    <div className="relative flex flex-col items-center">
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-white/20 !border-white/30 !top-[-4px]" />

      <div
        className={`
          w-[60px] h-[60px] rotate-45 rounded-md border-2 bg-[#141927]/90 backdrop-blur-sm
          flex items-center justify-center
          ${config.border} ${config.glow}
          ${status === 'processing' ? 'animate-pulse' : ''}
        `}
      >
        {/* Icon inside, counter-rotated */}
        <div className={`-rotate-45 ${config.text}`}>
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
            <path d="M6 3v6l6 6 6-6V3" />
            <path d="M12 15v6" />
          </svg>
        </div>
      </div>

      <span className={`mt-2 text-xs font-medium ${config.text}`}>Merge</span>
      <div className="flex items-center gap-1 mt-0.5">
        <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
        <span className={`text-[10px] ${config.text}`}>{config.label}</span>
      </div>

      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-white/20 !border-white/30 !bottom-[-4px]" />
    </div>
  );
});

export default MergeNode;
