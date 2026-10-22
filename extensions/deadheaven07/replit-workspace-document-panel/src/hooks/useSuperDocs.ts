import { useState, useCallback, useMemo, useRef } from 'react';
import { createSuperDocsClient } from '../services/superdocs';
import { planRegeneration, DocumentType } from '../services/revision';
import { parseProposedChangeBatch } from '../utils/parser';
import { FileHashMap } from '../utils/hash';
import { DocumentUploadResult, ProposedChange, ExportResult, ProposedChangeBatch, SyncHtmlResponse, DocumentVersion, Template, Prompt } from '../types/superdocs';

export type GenerationStep = 
  | 'idle'
  | 'uploading'
  | 'generating'
  | 'polling'
  | 'awaiting_approval'
  | 'approving'
  | 'exporting'
  | 'saving'
  | 'completed'
  | 'failed';

export interface SuperDocsState {
  step: GenerationStep;
  sessionId?: string;
  documentId?: string;
  jobId?: string;
  uploadResult?: DocumentUploadResult;
  proposedChanges?: ProposedChangeBatch;
  exportResult?: ExportResult;
  error?: string;
  progress?: string;
  canRetry?: boolean;
  lastInstruction?: string;
  lastDocumentType?: string;
  // --- v2 platform capability state ---
  versions?: DocumentVersion[];
  versionsLoading?: boolean;
  selectedVersion?: DocumentVersion;
  templates?: Template[];
  prompts?: Prompt[];
  templatesLoading?: boolean;
  lastSyncAt?: string;
  syncError?: string;
  syncSuccess?: boolean;
}

export interface SuperDocsActions {
  generateDocument: (instruction: string, documentType: string, sessionId?: string) => Promise<void>;
  regenerateFromSource: (
    instruction: string,
    documentType: string,
    baselineHashes: FileHashMap,
    currentFiles: Map<string, string>,
    sessionId?: string
  ) => Promise<{ hasChanges: boolean; changes: ProposedChange[] }>;
  approveChanges: (approved: boolean, changes: ProposedChange[]) => Promise<void>;
  continueJob: (continueJob: boolean) => Promise<void>;
  exportDocument: (format: 'pdf' | 'docx') => Promise<Blob>;
  cancel: () => void;
  retry: () => void;
  dismissError: () => void;
  reset: () => void;
  // --- v2 platform capability actions ---
  syncHtml: (html: string, documentId?: string) => Promise<SyncHtmlResponse | undefined>;
  loadVersions: () => Promise<void>;
  loadVersion: (versionId: string) => Promise<DocumentVersion | undefined>;
  revertToVersion: (versionId: string) => Promise<void>;
  loadTemplates: () => Promise<void>;
  loadPrompts: () => Promise<void>;
}

export function useSuperDocs(apiKey: string): [SuperDocsState, SuperDocsActions] {
  const [state, setState] = useState<SuperDocsState>({ step: 'idle' });
  const client = useMemo(() => createSuperDocsClient(apiKey), [apiKey]);
  const abortControllerRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setState({ step: 'idle' });
  }, []);

  const updateStep = useCallback((step: GenerationStep, progress?: string) => {
    setState(prev => ({ ...prev, step, progress, error: undefined, canRetry: false }));
  }, []);

  const setError = useCallback((error: string, canRetry = false) => {
    setState(prev => ({ ...prev, step: 'failed', error, canRetry, lastInstruction: prev.lastInstruction, lastDocumentType: prev.lastDocumentType }));
  }, []);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) abortControllerRef.current.abort();
    setState(prev => ({ ...prev, step: 'idle', error: undefined, progress: undefined }));
  }, []);

  const dismissError = useCallback(() => {
    setState(prev => ({ ...prev, step: 'idle', error: undefined, canRetry: false }));
  }, []);

const generateDocument = useCallback(async (instruction: string, documentType: string, sessionId?: string) => {
    if (!apiKey) { setError('SuperDocs API key is required', true); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    setState(prev => ({ ...prev, lastInstruction: instruction, lastDocumentType: documentType }));

    try {
      updateStep('uploading', 'Uploading document to SuperDocs...');
      const filename = `${documentType.toUpperCase()}.md`;
      const uploadResult = await client.uploadDocument(filename, instruction, sessionId, true, signal);
      if (signal.aborted) return;

      setState(prev => ({ ...prev, sessionId: uploadResult.session_id, documentId: uploadResult.document_id, uploadResult }));
      updateStep('generating', 'Starting document generation...');
      
      const jobId = await client.chatAsync({
        message: instruction,
        session_id: uploadResult.session_id,
        approval_mode: 'ask_every_time',
        model_tier: 'core',
      }, signal);
      if (signal.aborted) return;

      setState(prev => ({ ...prev, jobId }));
      updateStep('polling', 'Waiting for SuperDocs to process...');
      
      const jobStatus = await client.waitForJob(jobId, (status) => {
        if (signal.aborted) return;
        updateStep('polling', `Processing... (${status.status})`);
      }, signal);
      if (signal.aborted) return;

      setState(prev => ({ ...prev, jobId: jobStatus.job_id }));
      
      if (jobStatus.status === 'failed') throw new Error(jobStatus.error || 'Job failed');
      
      if (jobStatus.status === 'awaiting_approval') {
        const metadata = jobStatus.metadata;
        if (metadata && metadata.pending_changes) {
          const proposedChanges = parseProposedChangeBatch(
            typeof metadata.pending_changes === 'string' ? metadata.pending_changes : JSON.stringify(metadata.pending_changes)
          );
          setState(prev => ({ ...prev, proposedChanges }));
          updateStep('awaiting_approval', `${proposedChanges.changes.length} proposed changes awaiting review`);
        } else {
          updateStep('awaiting_approval', 'Awaiting approval (no changes parsed)');
        }
      } else if (jobStatus.status === 'completed') {
        updateStep('completed', 'Document generation completed');
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      setError(error instanceof Error ? error.message : 'Unknown error', true);
    }
  }, [apiKey, client, updateStep, setError]);

  const regenerateFromSource = useCallback(async (
    instruction: string,
    documentType: string,
    baselineHashes: FileHashMap,
    currentFiles: Map<string, string>,
    sessionId?: string
  ): Promise<{ hasChanges: boolean; changes: ProposedChange[] }> => {
    if (!apiKey) { setError('SuperDocs API key is required', true); return { hasChanges: false, changes: [] }; }
    if (!sessionId) { setError('No active SuperDocs session to regenerate against', true); return { hasChanges: false, changes: [] }; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      const plan = await planRegeneration(
        baselineHashes,
        currentFiles,
        documentType as DocumentType,
        instruction
      );
      if (signal.aborted) return { hasChanges: false, changes: [] };

      // Zero-drift short-circuit: identical hashes produce zero proposed
      // changes and NO chat job is created. Approved sections from the
      // previous round are preserved because unchanged source is never sent.
      if (!plan.hasChanges) {
        setState(prev => ({
          ...prev,
          step: 'completed',
          progress: 'No source changes detected - document already reflects current code',
          error: undefined,
          canRetry: false,
        }));
        return { hasChanges: false, changes: [] };
      }

      setState(prev => ({ ...prev, lastInstruction: plan.message, lastDocumentType: documentType }));
      updateStep('generating', `Detected ${plan.diff.changed.length + plan.diff.added.length} changed file(s), requesting granular updates...`);

      const jobId = await client.chatAsync({
        message: plan.message!,
        session_id: sessionId,
        approval_mode: 'ask_every_time',
        model_tier: 'core',
      }, signal);
      if (signal.aborted) return { hasChanges: false, changes: [] };

      setState(prev => ({ ...prev, jobId }));
      updateStep('polling', 'Waiting for SuperDocs to process changes...');

      const jobStatus = await client.waitForJob(jobId, (status) => {
        if (signal.aborted) return;
        updateStep('polling', `Processing... (${status.status})`);
      }, signal);
      if (signal.aborted) return { hasChanges: false, changes: [] };

      if (jobStatus.status === 'failed') throw new Error(jobStatus.error || 'Job failed');

      if (jobStatus.status === 'awaiting_approval') {
        const metadata = jobStatus.metadata;
        if (metadata && metadata.pending_changes) {
          const proposedChanges = parseProposedChangeBatch(
            typeof metadata.pending_changes === 'string' ? metadata.pending_changes : JSON.stringify(metadata.pending_changes)
          );
          setState(prev => ({ ...prev, proposedChanges }));
          updateStep('awaiting_approval', `${proposedChanges.changes.length} proposed changes awaiting review`);
          return { hasChanges: true, changes: proposedChanges.changes };
        }
        updateStep('awaiting_approval', 'Awaiting approval (no changes parsed)');
        return { hasChanges: true, changes: [] };
      }

      updateStep('completed', 'Regeneration completed - no changes proposed');
      return { hasChanges: true, changes: [] };
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return { hasChanges: false, changes: [] };
      setError(error instanceof Error ? error.message : 'Regeneration failed', true);
      return { hasChanges: false, changes: [] };
    }
  }, [apiKey, client, updateStep, setError]);

  const retry = useCallback(() => {
    const { lastInstruction, lastDocumentType } = state;
    if (lastInstruction && lastDocumentType) {
      generateDocument(lastInstruction, lastDocumentType);
    }
  }, [state, generateDocument]);

  const approveChanges = useCallback(async (approved: boolean, changes: ProposedChange[]) => {
    const { sessionId, jobId } = state;
    if (!sessionId || !jobId) { setError('Missing session or job ID'); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      const step = approved ? 'approving' : 'polling';
      const progress = approved ? 'Applying approved changes...' : 'Rejecting changes and continuing...';
      updateStep(step, progress);
      
      const jobStatus = await client.approveChanges({ session_id: sessionId, job_id: jobId, approved, changes }, signal);
      
      if (jobStatus.status === 'awaiting_approval') {
        const metadata = jobStatus.metadata;
        if (metadata && metadata.pending_changes) {
          const proposedChanges = parseProposedChangeBatch(
            typeof metadata.pending_changes === 'string' ? metadata.pending_changes : JSON.stringify(metadata.pending_changes)
          );
          setState(prev => ({ ...prev, proposedChanges }));
          updateStep('awaiting_approval', `${proposedChanges.changes.length} proposed changes awaiting review`);
        }
      } else if (jobStatus.status === 'completed') {
        updateStep('completed', approved ? 'Changes applied successfully' : 'Changes rejected, generation continued');
      } else if (jobStatus.status === 'failed') {
        throw new Error(jobStatus.error || 'Job failed after approval');
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to approve changes', true);
    }
  }, [state, client, updateStep, setError]);

  const continueJob = useCallback(async (continueJob: boolean) => {
    const { sessionId, jobId } = state;
    if (!sessionId || !jobId) { setError('Missing session or job ID'); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      updateStep('polling', continueJob ? 'Continuing generation...' : 'Stopping job...');
      const jobStatus = await client.continueJob({ job_id: jobId, continue: continueJob }, sessionId, signal);
      
      if (jobStatus.status === 'awaiting_approval') {
        const metadata = jobStatus.metadata;
        if (metadata && metadata.pending_changes) {
          const proposedChanges = parseProposedChangeBatch(
            typeof metadata.pending_changes === 'string' ? metadata.pending_changes : JSON.stringify(metadata.pending_changes)
          );
          setState(prev => ({ ...prev, proposedChanges }));
          updateStep('awaiting_approval', `${proposedChanges.changes.length} proposed changes awaiting review`);
        }
      } else if (jobStatus.status === 'completed') {
        updateStep('completed', 'Document generation completed');
      } else if (jobStatus.status === 'failed') {
        throw new Error(jobStatus.error || 'Job failed');
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to continue job', true);
    }
  }, [state, client, updateStep, setError]);

  const exportDocument = useCallback(async (format: 'pdf' | 'docx'): Promise<Blob> => {
    const { sessionId } = state;
    if (!sessionId) throw new Error('No active SuperDocs session');

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      updateStep('exporting', `Exporting ${format.toUpperCase()}...`);
      const exportResult = await client.exportDocument({ session_id: sessionId, format }, signal);
      if (signal.aborted) throw new Error('Aborted');

      setState(prev => ({ ...prev, exportResult }));
      updateStep('saving', 'Downloading exported document...');
      const blob = await client.downloadExport(exportResult.download_url, signal);
      updateStep('completed', 'Export downloaded successfully');
      return blob;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      const message = error instanceof Error ? error.message : 'Export failed';
      setError(message, true);
      throw error;
    }
  }, [state, client, updateStep, setError]);

  const syncHtml = useCallback(async (html: string, documentId?: string): Promise<SyncHtmlResponse | undefined> => {
    const { sessionId, documentId: stateDocId } = state;
    const targetDocId = documentId || stateDocId;
    if (!sessionId || !targetDocId) { setError('No active SuperDocs session or document to sync', true); return undefined; }
    if (!apiKey) { setError('SuperDocs API key is required', true); return undefined; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      setState(prev => ({ ...prev, syncError: undefined, syncSuccess: false }));
      const response = await client.syncHtml({ session_id: sessionId, document_id: targetDocId, html }, signal);
      if (signal.aborted) return undefined;
      setState(prev => ({ ...prev, lastSyncAt: new Date().toISOString(), syncSuccess: true, syncError: undefined }));
      return response;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return undefined;
      const message = error instanceof Error ? error.message : 'Sync failed';
      setState(prev => ({ ...prev, syncError: message, syncSuccess: false }));
      return undefined;
    }
  }, [state, apiKey, client, setError]);

  const loadVersions = useCallback(async () => {
    const { documentId } = state;
    if (!documentId) { setError('No active SuperDocs document to load versions', true); return; }
    if (!apiKey) { setError('SuperDocs API key is required', true); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      setState(prev => ({ ...prev, versionsLoading: true, error: undefined }));
      const response = await client.getVersions(documentId, signal);
      if (signal.aborted) return;
      setState(prev => ({ ...prev, versions: response.versions, versionsLoading: false }));
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      const message = error instanceof Error ? error.message : 'Failed to load versions';
      setState(prev => ({ ...prev, versionsLoading: false, error: message }));
    }
  }, [state.documentId, apiKey, client, setError]);

  const loadVersion = useCallback(async (versionId: string): Promise<DocumentVersion | undefined> => {
    const { documentId } = state;
    if (!documentId || !apiKey) return undefined;

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      const version = await client.getDocumentVersion(documentId, versionId, signal);
      if (signal.aborted) return undefined;
      setState(prev => ({ ...prev, selectedVersion: version }));
      return version;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return undefined;
      const message = error instanceof Error ? error.message : 'Failed to load version';
      setState(prev => ({ ...prev, error: message }));
      return undefined;
    }
  }, [state.documentId, apiKey, client]);

  const revertToVersion = useCallback(async (versionId: string) => {
    const { documentId } = state;
    if (!documentId || !apiKey) { setError('No active SuperDocs document to revert', true); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      updateStep('generating', 'Reverting to selected version...');
      const jobStatus = await client.revertToVersion(documentId, versionId, signal);
      if (signal.aborted) return;

      if (jobStatus.status === 'failed') throw new Error(jobStatus.error || 'Revert failed');
      if (jobStatus.status === 'completed') {
        updateStep('completed', 'Reverted to selected version');
        await loadVersions();
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      setError(error instanceof Error ? error.message : 'Failed to revert version', true);
    }
  }, [state.documentId, apiKey, client, updateStep, setError, loadVersions]);

  const loadTemplates = useCallback(async () => {
    if (!apiKey) { setError('SuperDocs API key is required', true); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      setState(prev => ({ ...prev, templatesLoading: true, error: undefined }));
      const response = await client.getTemplates(signal);
      if (signal.aborted) return;
      setState(prev => ({ ...prev, templates: response.templates, templatesLoading: false }));
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      const message = error instanceof Error ? error.message : 'Failed to load templates';
      setState(prev => ({ ...prev, templatesLoading: false, error: message }));
    }
  }, [apiKey, client, setError]);

  const loadPrompts = useCallback(async () => {
    if (!apiKey) { setError('SuperDocs API key is required', true); return; }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    const signal = abortController.signal;

    try {
      setState(prev => ({ ...prev, templatesLoading: true, error: undefined }));
      const response = await client.getPrompts(signal);
      if (signal.aborted) return;
      setState(prev => ({ ...prev, prompts: response.prompts, templatesLoading: false }));
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return;
      const message = error instanceof Error ? error.message : 'Failed to load prompts';
      setState(prev => ({ ...prev, templatesLoading: false, error: message }));
    }
  }, [apiKey, client, setError]);

  return [state, { generateDocument, regenerateFromSource, approveChanges, continueJob, exportDocument, cancel, retry, dismissError, reset, syncHtml, loadVersions, loadVersion, revertToVersion, loadTemplates, loadPrompts }];
}