import { memo } from 'react';
import { getSmoothStepPath } from '@xyflow/react';
import type { EdgeProps } from '@xyflow/react';
import type { NodeStatus, EdgeDecision } from '@/types/pipeline';

interface SmoothEdgeData {
  sourceStatus?: NodeStatus;
  decision?: EdgeDecision;
  [key: string]: unknown;
}

export const SmoothEdge = memo(function SmoothEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const edgeData = data as SmoothEdgeData | undefined;
  const sourceStatus = edgeData?.sourceStatus ?? 'ready';
  const decision = edgeData?.decision;

  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 20,
  });

  let strokeColor = 'rgba(255,255,255,0.12)';
  let strokeDasharray = '';
  let glowFilter = '';
  let strokeWidth = 2;
  let useFlowAnimation = false;

  // Decision-based styling takes priority
  if (decision === 'retry') {
    strokeColor = 'rgba(129,140,248,0.7)';
    strokeDasharray = '6 4';
    glowFilter = 'drop-shadow(0 0 3px rgba(129,140,248,0.4))';
  } else if (decision === 'skip') {
    strokeColor = 'rgba(251,191,36,0.5)';
    strokeDasharray = '4 6';
  } else if (decision === 'escalate') {
    strokeColor = 'rgba(251,113,133,0.8)';
    glowFilter = 'drop-shadow(0 0 4px rgba(251,113,133,0.4))';
    strokeWidth = 2.5;
  } else {
    // Status-based styling
    if (sourceStatus === 'complete') {
      strokeColor = 'rgba(16,185,129,0.45)';
      glowFilter = 'drop-shadow(0 0 2px rgba(16,185,129,0.2))';
    } else if (sourceStatus === 'processing' || sourceStatus === 'retrying') {
      // Flowing dash animation — communicates active data flow
      strokeColor = 'rgba(99,102,241,0.6)';
      strokeDasharray = '8 6';
      glowFilter = 'drop-shadow(0 0 3px rgba(99,102,241,0.3))';
      useFlowAnimation = true;
    } else if (sourceStatus === 'failed' || sourceStatus === 'escalated') {
      strokeColor = 'rgba(251,113,133,0.4)';
    }
  }

  return (
    <g>
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={strokeDasharray}
        className={useFlowAnimation ? 'edge-flow' : ''}
        style={{ filter: glowFilter, transition: 'stroke 300ms ease, filter 300ms ease' }}
      />
      {decision && decision !== 'next' && (
        <text
          x={(sourceX + targetX) / 2}
          y={(sourceY + targetY) / 2 - 8}
          textAnchor="middle"
          className="text-[9px] fill-white/40 font-mono uppercase"
        >
          {decision === 'retry' ? '↺ retry' : decision === 'skip' ? '⤳ skip' : '⚠ escalate'}
        </text>
      )}
    </g>
  );
});

export default SmoothEdge;
