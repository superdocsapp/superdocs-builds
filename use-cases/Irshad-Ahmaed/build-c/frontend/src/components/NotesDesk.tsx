import React from 'react';
import { PRESETS, StudyPreset } from '../data/presets';

interface NotesDeskProps {
  subject: string;
  setSubject: (v: string) => void;
  topic: string;
  setTopic: (v: string) => void;
  targetExam: string;
  setTargetExam: (v: string) => void;
  rawNotes: string;
  setRawNotes: (v: string) => void;
  depth: string;
  setDepth: (v: string) => void;
  onGenerate: () => void;
  isGenerating: boolean;
  onSelectPreset: (preset: StudyPreset) => void;
}

export const NotesDesk: React.FC<NotesDeskProps> = ({
  subject,
  setSubject,
  topic,
  setTopic,
  targetExam,
  setTargetExam,
  rawNotes,
  setRawNotes,
  depth,
  setDepth,
  onGenerate,
  isGenerating,
  onSelectPreset,
}) => {
  const charCount = rawNotes.length;
  const maxChars = 15000;

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
        <h2 style={{ fontSize: '13.5px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>📝</span> Raw Lecture Notes & Formula Input
        </h2>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Max {maxChars.toLocaleString()} chars
        </span>
      </div>

      {/* Preset Chips */}
      <div>
        <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '6px', display: 'block' }}>
          One-Click Academic Presets:
        </label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {PRESETS.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelectPreset(p)}
              disabled={isGenerating}
              className="btn-secondary"
              style={{ padding: '4px 10px', fontSize: '11.5px' }}
            >
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Grid Inputs */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
        <div>
          <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
            Subject / Domain
          </label>
          <input
            type="text"
            className="form-input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="e.g. Classical Electrodynamics"
          />
        </div>
        <div>
          <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
            Topic / Unit
          </label>
          <input
            type="text"
            className="form-input"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Maxwell's Equations & Waves"
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
        <div>
          <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
            Target Exam / Standard
          </label>
          <input
            type="text"
            className="form-input"
            value={targetExam}
            onChange={(e) => setTargetExam(e.target.value)}
            placeholder="e.g. University STEM / UPSC Mains"
          />
        </div>
        <div>
          <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
            Synthesis Depth
          </label>
          <select
            className="form-select"
            value={depth}
            onChange={(e) => setDepth(e.target.value)}
          >
            <option value="summary">High-Yield Summary (Cheat-Sheet)</option>
            <option value="detailed">Comprehensive Cornell Notes (Default)</option>
            <option value="mastery">Mastery Mode (Proofs & Derivations)</option>
          </select>
        </div>
      </div>

      {/* Raw Notes Area */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <label style={{ fontSize: '11.5px', fontWeight: '500', color: 'var(--text-secondary)' }}>
            Paste Messy Lecture Highlights or Formulas:
          </label>
          <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: charCount > maxChars ? 'var(--rose-text)' : 'var(--text-muted)' }}>
            {charCount.toLocaleString()} / {maxChars.toLocaleString()} chars
          </span>
        </div>
        <textarea
          className="form-textarea"
          rows={11}
          value={rawNotes}
          onChange={(e) => setRawNotes(e.target.value)}
          placeholder="Paste lecture transcript, shorthand formulas (e.g. del x E = -dB/dt), or bullet points here..."
        />
      </div>

      {/* Submit Button */}
      <button
        onClick={onGenerate}
        disabled={isGenerating || !rawNotes.trim() || charCount > maxChars}
        className="btn-primary"
        style={{ width: '100%', padding: '12px 18px', fontSize: '13px' }}
      >
        {isGenerating ? (
          <>
            <span className="spinner" />
            <span>Synthesizing Cornell Study Guide with Rendered Math...</span>
          </>
        ) : (
          <>
            <span>✨</span>
            <span>Synthesize Pedagogical Study Guide</span>
          </>
        )}
      </button>
    </div>
  );
};
