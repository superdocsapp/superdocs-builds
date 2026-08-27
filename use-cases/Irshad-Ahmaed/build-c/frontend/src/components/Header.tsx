import React from 'react';

interface HeaderProps {
  onQuickReviewerTest: () => void;
  isGenerating: boolean;
}

export const Header: React.FC<HeaderProps> = ({ onQuickReviewerTest, isGenerating }) => {
  return (
    <header className="header">
      <div className="header-inner">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '38px',
            height: '38px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #10b981, #0d9488)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '18px',
            boxShadow: '0 4px 12px rgba(16, 185, 129, 0.25)'
          }}>
            📐
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '15px', fontWeight: '700', color: '#fff', letterSpacing: '-0.3px' }}>
                SuperDocs Study-Guide Synthesizer
              </h1>
              <span className="badge-s2">Build C · Band S2</span>
            </div>
            <p style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
              EdTech Notes & Equation-Bearing Revision Synthesis Engine
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <button
            onClick={onQuickReviewerTest}
            disabled={isGenerating}
            className="btn-cyan"
            title="Pre-loads Maxwell's Equations and generates a structured study guide with rendered math in 1 click"
          >
            <span>⚡ Reviewer Quick Test</span>
          </button>

          <a
            href="http://localhost:5173"
            target="_blank"
            rel="noreferrer"
            className="btn-secondary"
            style={{ textDecoration: 'none', fontSize: '11.5px' }}
          >
            ✈️ Build A (FCOM)
          </a>

          <a
            href="http://localhost:5174"
            target="_blank"
            rel="noreferrer"
            className="btn-secondary"
            style={{ textDecoration: 'none', fontSize: '11.5px' }}
          >
            📊 Build B (FinOps)
          </a>
        </div>
      </div>
    </header>
  );
};
