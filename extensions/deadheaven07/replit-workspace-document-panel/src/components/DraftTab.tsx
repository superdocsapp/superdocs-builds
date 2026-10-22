import { useState, useCallback } from 'react';
import { DEFAULT_INSTRUCTIONS } from '../services/context';

interface DraftTabProps {
  onGenerate: (documentType: 'readme' | 'spec' | 'user-guide', instruction: string) => void;
  disabled: boolean;
  fileCount: number;
}

const DOCUMENT_TYPES: Array<{ id: 'readme' | 'spec' | 'user-guide'; label: string; description: string }> = [
  { id: 'readme', label: 'README', description: 'Project overview, installation, usage, and configuration' },
  { id: 'spec', label: 'Specification', description: 'Architecture, components, APIs, data models, and deployment' },
  { id: 'user-guide', label: 'User Guide', description: 'Tutorials, workflows, examples, and troubleshooting' },
];

export function DraftTab({ onGenerate, disabled, fileCount }: DraftTabProps) {
  const [documentType, setDocumentType] = useState<'readme' | 'spec' | 'user-guide'>('readme');
  const [instruction, setInstruction] = useState('');

  const handleGenerate = useCallback(() => {
    onGenerate(documentType, instruction.trim());
  }, [documentType, instruction, onGenerate]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
        <h3 className="text-sm font-bold text-gray-900 mb-1">Create Documentation</h3>
        <p className="text-xs text-gray-500">Generate documentation from selected project files using SuperDocs AI.</p>
      </div>

      {/* Document Type Selection */}
      <div className="mb-4">
        <label className="block text-xs font-semibold text-gray-700 mb-2">Document Type</label>
        <div className="grid grid-cols-3 gap-2.5" role="radiogroup" aria-label="Document type">
          {DOCUMENT_TYPES.map((type) => (
            <button
              key={type.id}
              type="button"
              role="radio"
              aria-checked={documentType === type.id}
              onClick={() => setDocumentType(type.id)}
              className={`relative flex-1 rounded-xl border-2 p-3 text-center transition-all card-hover cursor-pointer ${
                documentType === type.id
                  ? 'border-primary-500 bg-primary-50 text-primary-700 shadow-sm ring-1 ring-primary-500'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 shadow-xs'
              }`}
              disabled={disabled}
            >
              <div className="font-bold text-xs">{type.label}</div>
              <div className="text-[10px] text-gray-500 mt-1 line-clamp-2">{type.description}</div>
              {documentType === type.id && (
                <div className="absolute -bottom-1 left-1/2 transform -translate-x-1/2 w-2 h-2 bg-primary-500 rounded-full" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Instructions */}
      <div>
        <label className="block text-xs font-semibold text-gray-700 mb-2">
          Instruction for SuperDocs
        </label>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={4}
          placeholder={DEFAULT_INSTRUCTIONS[documentType]}
          className="w-full px-3.5 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-xs transition-all resize-none disabled:opacity-50 disabled:cursor-not-allowed bg-white"
          disabled={disabled}
          aria-describedby="instruction-hint"
        />
        <p id="instruction-hint" className="text-[11px] text-gray-500 mt-1.5">
          Leave empty to use the default instruction for the selected document type.
        </p>
      </div>

      {/* Context Summary */}
      <div className="px-4 py-3 bg-white rounded-xl border border-gray-200 shadow-xs">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary-500" />
            <span className="text-gray-700 font-medium">
              {fileCount} file{fileCount !== 1 ? 's' : ''} selected for context
            </span>
          </div>
          <span className="text-[10px] text-gray-400 font-mono">Max 500KB cap</span>
        </div>
      </div>

      {/* Primary CTA */}
      <div className="pt-2">
        <button
          onClick={handleGenerate}
          disabled={disabled || fileCount === 0}
          className="w-full px-4 py-3 bg-primary-600 text-white rounded-xl font-semibold hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 shadow-sm flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span>Generate Document</span>
        </button>
        {fileCount === 0 && !disabled && (
          <p className="text-xs text-gray-500 text-center mt-2">Select at least one file to generate a document</p>
        )}
      </div>
    </div>
  );
}