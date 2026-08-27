import React, { useState } from 'react';

interface ChatRefineBarProps {
  onRefine: (instruction: string) => void;
  isRefining: boolean;
  disabled: boolean;
}

export const ChatRefineBar: React.FC<ChatRefineBarProps> = ({ onRefine, isRefining, disabled }) => {
  const [instruction, setInstruction] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!instruction.trim() || disabled || isRefining) return;
    onRefine(instruction.trim());
    setInstruction('');
  };

  const chips = [
    'Add step-by-step mathematical derivation',
    'Add 2 more exam-style practice questions',
    'Expand the Feynman intuitive breakdown',
    'Include dimensional analysis for all units',
  ];

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={{ fontSize: '12.5px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>💬</span> Multi-Turn AI Refinement Chat
        </label>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Modifies the active guide without losing LaTeX formulas
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {chips.map((chip, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => setInstruction(chip)}
            disabled={disabled || isRefining}
            className="btn-secondary"
            style={{ padding: '3px 8px', fontSize: '11px' }}
          >
            + {chip}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          className="form-input"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="e.g. Add step-by-step mathematical proof for formula 3..."
          disabled={disabled || isRefining}
          style={{ flex: 1 }}
        />
        <button
          type="submit"
          disabled={disabled || isRefining || !instruction.trim()}
          className="btn-primary"
          style={{ padding: '8px 18px', fontSize: '12px' }}
        >
          {isRefining ? <span className="spinner" /> : <span>Apply Refinement</span>}
        </button>
      </form>
    </div>
  );
};
