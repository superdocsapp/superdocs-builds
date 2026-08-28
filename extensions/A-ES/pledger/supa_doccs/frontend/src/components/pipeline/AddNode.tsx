import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

export const AddNode = memo(function AddNode() {
  return (
    <div className="relative flex items-center justify-center">
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-transparent !border-transparent" />

      <div
        className="
          w-8 h-8 rounded-full border border-dashed border-white/20
          flex items-center justify-center
          text-white/30 text-lg leading-none
          hover:border-solid hover:border-white/40 hover:text-white/50
          transition-all cursor-pointer
        "
      >
        +
      </div>

      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-transparent !border-transparent" />
    </div>
  );
});

export default AddNode;
