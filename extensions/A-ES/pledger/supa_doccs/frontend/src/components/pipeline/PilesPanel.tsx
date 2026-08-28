import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchPiles, createPile, fetchPileDetail, uploadToPile, uploadIncrementalDocument, deletePile, seedDemo } from '@/services/pipelineApi';
import type { PileListItem, PileDetail, IncrementalUpdateResponse, PileDocumentItem, SeedDemoResponse } from '@/services/pipelineApi';
import { FileDropZone } from './FileDropZone';
import { DocumentDetailPanel } from './DocumentDetailPanel';

interface PilesPanelProps {
  selectedPileId: string | null;
  onPileSelect: (pile: PileListItem) => void;
  onDocumentsUploaded: () => void;
  onDemoSeeded?: (result: SeedDemoResponse) => Promise<void> | void;
}

/**
 * Piles section for the sidebar — list piles, create new pile,
 * show documents in selected pile, and upload files into it.
 */
export function PilesPanel({ selectedPileId, onPileSelect, onDocumentsUploaded, onDemoSeeded }: PilesPanelProps) {
  const [piles, setPiles] = useState<PileListItem[]>([]);
  const [pileDetail, setPileDetail] = useState<PileDetail | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [newPileName, setNewPileName] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isIncremental, setIsIncremental] = useState(false);
  const [incrementalResult, setIncrementalResult] = useState<IncrementalUpdateResponse | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<PileDocumentItem | null>(null);
  const [isSeeding, setIsSeeding] = useState(false);
  const [seedResult, setSeedResult] = useState<SeedDemoResponse | null>(null);
  const [seedError, setSeedError] = useState<string | null>(null);
  const incrementalInputRef = useRef<HTMLInputElement>(null);

  // Load piles list
  const loadPiles = useCallback(async () => {
    const result = await fetchPiles();
    setPiles(result);
  }, []);

  useEffect(() => {
    loadPiles();
  }, [loadPiles]);

  // Load pile detail when selection changes
  useEffect(() => {
    if (selectedPileId) {
      fetchPileDetail(selectedPileId)
        .then(setPileDetail)
        .catch(() => setPileDetail(null));
    } else {
      setPileDetail(null);
    }
  }, [selectedPileId]);

  const handleCreatePile = useCallback(async () => {
    if (!newPileName.trim()) return;
    try {
      const created = await createPile(newPileName.trim());
      setNewPileName('');
      setIsCreating(false);
      await loadPiles();
      // Auto-select the newly created pile
      onPileSelect({ id: created.id, name: created.name, status: 'active', created_at: '', document_count: 0 });
    } catch (err) {
      console.error('Failed to create pile:', err);
    }
  }, [newPileName, loadPiles, onPileSelect]);

  const handleSeedDemo = useCallback(async () => {
    setIsSeeding(true);
    setSeedError(null);
    setSeedResult(null);
    try {
      const result = await seedDemo();
      setSeedResult(result);
      // Refresh the pile list so the seeded demo pile appears.
      await loadPiles();
      await onDemoSeeded?.(result);
    } catch (err) {
      setSeedError(err instanceof Error ? err.message : 'Demo seed failed');
    } finally {
      setIsSeeding(false);
    }
  }, [loadPiles, onDemoSeeded]);

  const handleFilesSelected = useCallback(async (files: File[]) => {
    if (!selectedPileId) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const result = await uploadToPile(selectedPileId, files);
      if (result.errors.length > 0) {
        setUploadError(result.errors.join(', '));
      }
      // Refresh pile detail and list
      await loadPiles();
      const detail = await fetchPileDetail(selectedPileId);
      setPileDetail(detail);
      onDocumentsUploaded();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  }, [selectedPileId, loadPiles, onDocumentsUploaded]);

  const handleIncrementalUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !selectedPileId) return;
    setIsIncremental(true);
    setUploadError(null);
    setIncrementalResult(null);
    try {
      const result = await uploadIncrementalDocument(selectedPileId, Array.from(files));
      setIncrementalResult(result);
      // Refresh pile detail
      await loadPiles();
      const detail = await fetchPileDetail(selectedPileId);
      setPileDetail(detail);
      onDocumentsUploaded();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Incremental update failed');
    } finally {
      setIsIncremental(false);
      // Reset file input
      if (incrementalInputRef.current) incrementalInputRef.current.value = '';
    }
  }, [selectedPileId, loadPiles, onDocumentsUploaded]);

  return (
    <div className="space-y-3">
      {/* Section header + New button */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/45">
          Piles
        </span>
        <button
          onClick={() => setIsCreating(!isCreating)}
          className="text-[10px] font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
        >
          {isCreating ? 'Cancel' : '+ New'}
        </button>
      </div>

      {/* Run demo — seeds the fixed 5-document demo pile */}
      <div>
        <button
          onClick={handleSeedDemo}
          disabled={isSeeding}
          className="w-full rounded-md border border-indigo-500/30 bg-indigo-500/[0.08] px-2.5 py-2 text-[11px] font-medium text-indigo-300 hover:bg-indigo-500/[0.15] hover:border-indigo-500/50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          title="Seed the fixed demo pile (runs scripts/seed_demo.py logic on the backend)"
        >
          {isSeeding ? 'Seeding demo…' : 'Run demo'}
        </button>
        {seedResult && (
          <p className="mt-1 text-[10px] text-white/45">
            {seedResult.status === 'seeded'
              ? `Demo seeded — ${seedResult.document_count} documents, ${seedResult.conflicts?.length ?? 0} conflicts.`
              : 'Demo already present — nothing to seed.'}
          </p>
        )}
        {seedError && (
          <p className="mt-1 text-[10px] text-rose-400">{seedError}</p>
        )}
      </div>

      {/* Create pile inline form */}
      {isCreating && (
        <div className="flex gap-1.5">
          <input
            type="text"
            value={newPileName}
            onChange={(e) => setNewPileName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreatePile(); }}
            placeholder="Pile name..."
            className="flex-1 rounded-md border border-white/[0.1] bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-white/80 placeholder-white/30 focus:border-indigo-500/50 focus:outline-none focus:ring-1 focus:ring-indigo-500/20"
            autoFocus
          />
          <button
            onClick={handleCreatePile}
            disabled={!newPileName.trim()}
            className="rounded-md bg-indigo-600 px-2.5 py-1.5 text-[11px] font-medium text-white disabled:opacity-40 hover:bg-indigo-500 transition-colors"
          >
            Create
          </button>
        </div>
      )}

      {/* Pile list */}
      <div className="space-y-1">
        {piles.length === 0 && (
          <p className="text-[12px] text-white/30 italic">No piles yet</p>
        )}
        {piles.map((pile) => {
          const isActive = pile.id === selectedPileId;
          return (
            <div
              key={pile.id}
              className={`
                group w-full text-left rounded-md px-2.5 py-2 transition-all duration-150 cursor-pointer
                ${isActive
                  ? 'bg-indigo-500/[0.12] border border-indigo-500/30'
                  : 'border border-transparent hover:bg-white/[0.04] hover:border-white/[0.08]'
                }
              `}
              onClick={() => onPileSelect(pile)}
            >
              <div className="flex items-center justify-between">
                <span className={`text-[13px] font-medium truncate ${isActive ? 'text-white/90' : 'text-white/60'}`}>
                  {pile.name}
                </span>
                <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                  <span className="text-[10px] text-white/30 tabular-nums">
                    {pile.document_count} doc{pile.document_count !== 1 ? 's' : ''}
                  </span>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!confirm(`Delete pile "${pile.name}"?`)) return;
                      try {
                        await deletePile(pile.id);
                        await loadPiles();
                        if (selectedPileId === pile.id) {
                          setPileDetail(null);
                        }
                      } catch {}
                    }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-white/25 hover:text-rose-400 transition-all"
                    title="Delete pile"
                  >
                    <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected pile: document list + upload zone */}
      {selectedPileId && pileDetail && (
        <div className="space-y-2 pt-2 border-t border-white/[0.06]">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-white/45 block">
            Documents in "{pileDetail.name}"
          </span>

          {pileDetail.documents.length === 0 ? (
            <p className="text-[11px] text-white/30 italic">No documents yet — drop files below</p>
          ) : (
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {pileDetail.documents.map((doc) => (
                <div
                  key={doc.document_id}
                  className="flex items-center gap-2 rounded px-2 py-1.5 bg-white/[0.02] hover:bg-white/[0.05] cursor-pointer transition-colors"
                  onClick={() => setSelectedDoc(doc)}
                  title={`View extracted facts from ${doc.filename}`}
                  data-testid={`document-${doc.document_id}`}
                >
                  <MimeIcon mime={doc.mime_type} />
                  <span className="text-[12px] text-white/60 truncate flex-1">
                    {doc.filename}
                  </span>
                  <svg className="w-3 h-3 text-white/25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </div>
              ))}
            </div>
          )}

          {/* Drop zone */}
          <FileDropZone
            onFilesSelected={handleFilesSelected}
            isUploading={isUploading}
            disabled={false}
          />

          {/* Incremental update action */}
          <div className="pt-1.5">
            <input
              ref={incrementalInputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={handleIncrementalUpload}
              className="hidden"
              aria-label="Add document for incremental update"
            />
            <button
              onClick={() => incrementalInputRef.current?.click()}
              disabled={isIncremental}
              className="w-full rounded-md border border-emerald-500/30 bg-emerald-500/[0.08] px-2.5 py-2 text-[11px] font-medium text-emerald-400 hover:bg-emerald-500/[0.15] hover:border-emerald-500/50 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isIncremental ? 'Processing...' : 'Add document (incremental)'}
            </button>
            <p className="mt-1 text-[10px] text-white/30">
              Updates only affected sections — no full re-run
            </p>
          </div>

          {/* Incremental result feedback */}
          {incrementalResult && (
            <div className="rounded-md border border-emerald-500/20 bg-emerald-500/[0.05] px-2.5 py-2 space-y-1">
              <p className="text-[11px] text-emerald-400 font-medium">Incremental update complete</p>
              <p className="text-[10px] text-white/50">
                {incrementalResult.sections_updated} section{incrementalResult.sections_updated !== 1 ? 's' : ''} updated,{' '}
                {incrementalResult.unaffected_sections.length} unchanged
              </p>
              {incrementalResult.conflicts_detected > 0 && (
                <p className="text-[10px] text-amber-400">
                  {incrementalResult.conflicts_detected} conflict{incrementalResult.conflicts_detected !== 1 ? 's' : ''} sent to approval queue
                </p>
              )}
            </div>
          )}

          {uploadError && (
            <p className="text-[11px] text-rose-400">{uploadError}</p>
          )}
        </div>
      )}

      {/* Document detail overlay */}
      {selectedDoc && (
        <DocumentDetailPanel
          documentId={selectedDoc.document_id}
          filename={selectedDoc.filename}
          onClose={() => setSelectedDoc(null)}
        />
      )}
    </div>
  );
}

/** Tiny MIME type icon */
function MimeIcon({ mime }: { mime: string }) {
  const color = mime.includes('pdf') ? 'text-rose-400/70' :
    mime.includes('word') ? 'text-blue-400/70' : 'text-white/40';
  return (
    <svg className={`w-3.5 h-3.5 flex-shrink-0 ${color}`} viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 1a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V5.414A2 2 0 0013.414 4L11 1.586A2 2 0 009.586 1H4zm5 1.5v2A1.5 1.5 0 0010.5 6H13v7a.5.5 0 01-.5.5h-9A.5.5 0 013 13V3a.5.5 0 01.5-.5H9z" />
    </svg>
  );
}
