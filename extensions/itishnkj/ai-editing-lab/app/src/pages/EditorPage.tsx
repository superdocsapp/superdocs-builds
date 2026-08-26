import { useEffect, useMemo, useRef, useState } from 'react';
import {
  useGenerateEdit,
  useGetLabConfig,
  useDecideReview,
  useCancelReview,
  type EditInputEngine,
  type EditInputScope,
  type EditResult,
} from '@workspace/api-client-react';
import { Link, useLocation, useParams } from 'wouter';
import {
  AlertCircle,
  CheckCircle2,
  FilePlus2,
  FileText,
  History,
  Loader2,
  MoreHorizontal,
  Pencil,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import { toast } from 'sonner';
import {
  RichTextEditor,
  type RichTextEditorHandle,
} from '@/components/editor/RichTextEditor';
import {
  resolveSiblingProposals,
  runHostedAcceptFlow,
} from '@/lib/proposal-resolution';
import {
  AssistantPanel,
  type EngineStatusInfo,
} from '@/components/assistant/AssistantPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { analyzeFormatting } from '@/lib/experiment';
import { subscribeToEditorIntents } from '@/lib/editor-intents';
import {
  htmlToPreview,
  titleFromInstruction,
  type ChatMessage,
} from '@/lib/history';
import { usePreferences } from '@/lib/preferences';
import {
  documentSessionTitle,
  telemetryMetadataForDocument,
  useLabStore,
} from '@/lib/store';
import { importDocument } from '@/lib/import/importDocument';
import {
  DEFAULT_MAX_IMPORT_BYTES,
  DocumentImportError,
} from '@/lib/import/types';
import {
  applyEditResult,
  DIY_PROMPT_VERSION,
  estimateRequestContext,
  estimateDiyPreflightCost,
  makeRequestFingerprint,
} from '@/lib/telemetry';
import {
  buildEditRequest,
  contextLimitAction,
  createTelemetryDraftForRequest,
} from '@/lib/telemetry-workflows';

type FrozenRequest = {
  documentHtml: string;
  versionId: string;
  selectionHtml: string;
  selectionText: string;
  selectionFrom: number;
  selectionTo: number;
  scope: EditInputScope;
  instruction: string;
};

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = (error as { data?: { error?: string } }).data;
    if (data?.error) return data.error;
  }
  return error instanceof Error ? error.message : 'The editing request failed.';
}

const ONBOARDING_STEPS = [
  {
    icon: FileText,
    title: 'Your document comes first',
    body: 'Write directly on the page, or upload a DOCX, PDF, HTML, or TXT file. Everything is saved in this browser automatically.',
  },
  {
    icon: Sparkles,
    title: 'Ask the assistant for edits',
    body: 'Describe any change in plain words. Choose DIY, SuperDocs, or Compare to ask both engines at once.',
  },
  {
    icon: ShieldCheck,
    title: 'You approve every change',
    body: 'The assistant only suggests. Review the before and after, then accept or reject — and revisit anything later in History.',
  },
] as const;

export default function EditorPage() {
  const {
    currentDocumentHtml,
    documentSession,
    setDocumentHtml,
    startImportedDocument,
    startCanonicalDocument,
    restoreDocumentOriginal,
    saveVersion,
    logActivity,
    versions,
    compareRuns,
    benchmarkRuns,
    latestResults,
    setLatestResults,
    resetAll,
    telemetry,
    observabilitySettings,
    recordTelemetry,
    updateTelemetryForRequest,
    conversations,
    activeConversationId,
    startConversation,
    appendConversationMessage,
    updateConversationMessage,
    setActiveConversation,
    addEditEvent,
    renameDocument,
    persistenceMode,
    saveStatus,
  } = useLabStore();
  const { preferences, setPreference } = usePreferences();
  const { data: config } = useGetLabConfig();
  const generateEdit = useGenerateEdit();
  const decideReview = useDecideReview();
  const cancelReview = useCancelReview();
  const editorRef = useRef<RichTextEditorHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const params = useParams<{ documentId?: string }>();
  const [, navigate] = useLocation();

  const [engineMode, setEngineMode] = useState<
    EditInputEngine | 'both'
  >('diy');
  const [scope, setScope] = useState<EditInputScope>('document');
  const [instruction, setInstruction] = useState('');
  const [selectionText, setSelectionText] = useState('');
  const [selectionHtml, setSelectionHtml] = useState('');
  const [selectionFrom, setSelectionFrom] = useState(0);
  const [selectionTo, setSelectionTo] = useState(0);
  const [pendingResults, setPendingResults] = useState<EditResult[]>([]);
  const [frozenRequest, setFrozenRequest] = useState<FrozenRequest | null>(
    null,
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isResolvingReview, setIsResolvingReview] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [isDropActive, setIsDropActive] = useState(false);

  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [newDocumentOpen, setNewDocumentOpen] = useState(false);
  const [assistantDrawerOpen, setAssistantDrawerOpen] = useState(false);
  const [assistantDrawerSnap, setAssistantDrawerSnap] = useState<number | string | null>(
    1,
  );
  const [onboardingOpen, setOnboardingOpen] = useState(
    () => !preferences.onboardingDismissed,
  );
  const [onboardingStep, setOnboardingStep] = useState(0);
  const [isDesktopPanel, setIsDesktopPanel] = useState(
    () => window.matchMedia('(min-width: 1280px)').matches,
  );
  const [saveFlash, setSaveFlash] = useState(false);

  const runConversationIdRef = useRef<string | null>(null);
  const proposalMessageIds = useRef(new Map<string, string>());
  const firstHtmlRender = useRef(true);

  useEffect(() => {
    if (!isRunning) return;
    const started = performance.now();
    const timer = window.setInterval(
      () => setElapsedMs(performance.now() - started),
      100,
    );
    return () => window.clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    const mql = window.matchMedia('(min-width: 1280px)');
    const onChange = () => {
      setIsDesktopPanel(mql.matches);
      if (mql.matches) setAssistantDrawerOpen(false);
    };
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  useEffect(
    () =>
      subscribeToEditorIntents((intent) => {
        if (intent === 'upload-document') fileInputRef.current?.click();
        if (intent === 'new-document') setNewDocumentOpen(true);
      }),
    [],
  );

  useEffect(() => {
    if (firstHtmlRender.current) {
      firstHtmlRender.current = false;
      return;
    }
    setSaveFlash(true);
    const timer = window.setTimeout(() => setSaveFlash(false), 800);
    return () => window.clearTimeout(timer);
  }, [currentDocumentHtml]);

  useEffect(() => {
    if (
      pendingResults.length > 0 &&
      !window.matchMedia('(min-width: 1280px)').matches
    ) {
      setAssistantDrawerOpen(true);
    }
  }, [pendingResults.length]);

  const statuses = useMemo(
    () =>
      new Map(config?.engines.map((engine) => [engine.id, engine]) ?? []),
    [config],
  );
  const selectedConfigured =
    engineMode === 'both'
      ? Boolean(
          statuses.get('diy')?.configured &&
            statuses.get('superdocs')?.configured,
        )
      : Boolean(statuses.get(engineMode)?.configured);
  const preflight = useMemo(
    () =>
      estimateRequestContext({
        engine: engineMode === 'diy' ? 'diy' : 'superdocs',
        documentHtml: currentDocumentHtml,
        selectionHtml,
        selectionText,
        scope,
        instruction: instruction.trim(),
        contextBudgetChars: observabilitySettings.contextBudgetChars,
        softContextBudgetChars: observabilitySettings.softContextBudgetChars,
      }),
    [
      currentDocumentHtml,
      engineMode,
      instruction,
      observabilitySettings.contextBudgetChars,
      observabilitySettings.softContextBudgetChars,
      scope,
      selectionText,
      selectionHtml,
    ],
  );
  const diyPreflight = useMemo(
    () =>
      estimateDiyPreflightCost(
        statuses.get('diy')?.modelLabel ?? '',
        preflight.estimatedPromptChars,
      ),
    [preflight.estimatedPromptChars, statuses],
  );

  const activeConversation = useMemo(
    () =>
      conversations.find(
        (conversation) =>
          conversation.id === activeConversationId &&
          conversation.sessionKey != null &&
          conversation.sessionKey === documentSession.sessionKey,
      ) ?? null,
    [activeConversationId, conversations, documentSession.sessionKey],
  );

  const documentTitle = documentSessionTitle(documentSession);

  const handleSelectionChange = (
    text: string,
    html: string,
    from: number,
    to: number,
  ) => {
    setSelectionText(text);
    setSelectionHtml(html);
    setSelectionFrom(from);
    setSelectionTo(to);
    if (text.trim() && scope !== 'selection') setScope('selection');
    if (!text.trim() && scope === 'selection') setScope('document');
  };

  const canReplaceDocument = () => {
    if (pendingResults.some((result) => result.review)) {
      toast.error('Resolve or cancel the pending hosted review before replacing this document.');
      return false;
    }
    const wouldClearSession =
      documentSession.sourceType === 'imported' ||
      versions.length > 1 ||
      compareRuns.length > 0 ||
      benchmarkRuns.length > 0;
    if (
      (currentDocumentHtml !== documentSession.originalHtml || wouldClearSession) &&
      !window.confirm(
        'Replace this document? This starts a new document session and clears the current version history, comparisons, and benchmarks. Your chat and edit history stay available in History.',
      )
    ) {
      return false;
    }
    return true;
  };

  const clearEditorRequestState = () => {
    setPendingResults([]);
    setFrozenRequest(null);
    setLatestResults([]);
    setSelectionText('');
    setSelectionHtml('');
    setSelectionFrom(0);
    setSelectionTo(0);
    setScope('document');
    runConversationIdRef.current = null;
    proposalMessageIds.current.clear();
  };

  const handleImportFile = async (file: File | null) => {
    if (!file || isImporting || isRunning) return;
    if (!canReplaceDocument()) return;
    setImportError(null);
    setIsImporting(true);
    try {
      const imported = await importDocument(file);
      startImportedDocument(imported);
      clearEditorRequestState();
      toast.success(`Imported ${imported.originalFileName}.`);
    } catch (error) {
      const message =
        error instanceof DocumentImportError
          ? error.message
          : 'This document could not be parsed. Try a different file or export it as DOCX, HTML, or TXT.';
      setImportError(message);
      toast.error(message);
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const selectCanonicalDocument = () => {
    if (
      documentSession.sourceType === 'canonical' &&
      versions.length === 1 &&
      currentDocumentHtml === documentSession.originalHtml
    ) {
      toast.info('You are already on a fresh standard test document.');
      return;
    }
    if (!canReplaceDocument()) return;
    startCanonicalDocument();
    clearEditorRequestState();
    setImportError(null);
    toast.success('Started a new session with the standard test document.');
  };

  const restoreOriginal = () => {
    if (pendingResults.some((result) => result.review)) {
      toast.error('Resolve or cancel the pending hosted review before restoring the original.');
      return;
    }
    if (
      currentDocumentHtml !== documentSession.originalHtml &&
      !window.confirm(
        'Restore the original document? Current editor changes will be discarded and the restored original will be saved as a new version.',
      )
    ) {
      return;
    }
    restoreDocumentOriginal();
    clearEditorRequestState();
    toast.success(
      documentSession.sourceType === 'imported'
        ? 'Imported original restored as a new version.'
        : 'Original document restored as a new version.',
    );
  };

  const ensureConversationId = (instructionText: string) => {
    if (activeConversation) return activeConversation.id;
    const conversation = startConversation({
      documentId: documentSession.id,
      documentTitle,
      sessionKey: documentSession.sessionKey,
      title: titleFromInstruction(instructionText),
    });
    return conversation.id;
  };

  const updateProposalMessage = (
    result: EditResult,
    updates: Partial<ChatMessage>,
  ) => {
    const conversationId = runConversationIdRef.current ?? activeConversationId;
    if (!conversationId) return;
    const messageId = proposalMessageIds.current.get(
      `${result.requestId}:${result.engine}`,
    );
    if (messageId) updateConversationMessage(conversationId, messageId, updates);
  };

  const recordDecisionEvent = (
    result: EditResult,
    request: FrozenRequest,
    decision: 'accepted' | 'rejected',
    versionAfter: { id: string; number: number } | null,
  ) => {
    addEditEvent({
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      documentId: documentSession.id,
      sessionKey: documentSession.sessionKey,
      documentTitle,
      conversationId: runConversationIdRef.current ?? activeConversationId,
      requestId: result.requestId,
      engine: result.engine,
      engineLabel: result.engineLabel,
      instruction: request.instruction,
      scope: request.scope,
      decision,
      versionBeforeId: request.versionId,
      versionBeforeNumber: versions.length,
      versionAfterId: versionAfter?.id ?? null,
      versionAfterNumber: versionAfter?.number ?? null,
      beforePreview: htmlToPreview(
        request.scope === 'selection'
          ? request.selectionHtml
          : result.proposedChanges[0]?.oldHtml ?? request.documentHtml,
      ),
      afterPreview: htmlToPreview(
        result.candidateDocumentHtml ??
          result.proposedChanges[0]?.newHtml ??
          '',
      ),
    });
  };

  const handleRun = async () => {
    if (!instruction.trim()) {
      toast.error('Enter an editing instruction.');
      return;
    }
    if (scope === 'selection' && !selectionText.trim()) {
      toast.error('Select meaningful text or switch to the entire document.');
      return;
    }
    if (!selectedConfigured) {
      toast.error(
        engineMode === 'both'
          ? 'Both engines must be available for a controlled comparison.'
          : `${statuses.get(engineMode)?.label ?? engineMode} is not available.`,
      );
      return;
    }
    if (contextLimitAction(preflight) === 'block') {
      toast.error(
        `This request would send ${preflight.contextChars.toLocaleString()} context characters, above the configured application limit of ${observabilitySettings.contextBudgetChars.toLocaleString()}.`,
      );
      return;
    }
    if (
      contextLimitAction(preflight) === 'confirm' &&
      !window.confirm(
        `This request will send ${preflight.contextChars.toLocaleString()} context characters, above the ${observabilitySettings.softContextBudgetChars.toLocaleString()} soft budget. Continue without reducing the source document?`,
      )
    ) {
      return;
    }

    const engines: EditInputEngine[] =
      engineMode === 'both' ? ['diy', 'superdocs'] : [engineMode];
    const snapshot: FrozenRequest = {
      documentHtml: currentDocumentHtml,
      versionId: versions[0]?.id ?? uuidv4(),
      selectionHtml,
      selectionText,
      selectionFrom,
      selectionTo,
      scope,
      instruction: instruction.trim(),
    };
    const requestFingerprints = await Promise.all(
      engines.map(async (engine) => ({
        engine,
        requestFingerprint: await makeRequestFingerprint({
          engine,
          documentHtml: snapshot.documentHtml,
          selectionHtml:
            snapshot.scope === 'selection' ? snapshot.selectionHtml : null,
          selectionText:
            snapshot.scope === 'selection' ? snapshot.selectionText : null,
          scope: snapshot.scope,
          instruction: snapshot.instruction,
        }),
      })),
    );
    const duplicateRequests = requestFingerprints.filter(
      ({ requestFingerprint }) =>
        telemetry.some(
          (record) => record.requestFingerprint === requestFingerprint,
        ),
    );
    if (
      duplicateRequests.length &&
      !window.confirm(
        `An exact ${duplicateRequests.length === 1 ? 'request has' : 'set of requests have'} already been recorded. Running again will create fresh provider calls and will not reuse prior output. Continue?`,
      )
    ) {
      return;
    }

    const requestId = uuidv4();
    const conversationId = ensureConversationId(snapshot.instruction);
    runConversationIdRef.current = conversationId;
    appendConversationMessage(conversationId, {
      id: uuidv4(),
      role: 'user',
      kind: 'instruction',
      text: snapshot.instruction,
      timestamp: new Date().toISOString(),
      engine: engineMode,
      scope: snapshot.scope,
      requestId,
    });

    setFrozenRequest(snapshot);
    setPendingResults([]);
    setIsRunning(true);
    setElapsedMs(0);
    // Keep the submitted instruction in the conversation, not in the composer.
    // "Try another approach" explicitly restores it when that is useful.
    setInstruction('');
    logActivity('Edit requested', snapshot.instruction, {
      engine: engineMode,
      scope,
      requestId,
      status: 'pending',
    });

    const requestRecords = new Map<
      EditInputEngine,
      ReturnType<typeof recordTelemetry>
    >();
    const requestStarts = new Map<EditInputEngine, number>();
    const settled = await Promise.allSettled(
      engines.map(async (engine) => {
        const requestFingerprint = await makeRequestFingerprint({
          engine,
          documentHtml: snapshot.documentHtml,
          selectionHtml:
            snapshot.scope === 'selection' ? snapshot.selectionHtml : null,
          selectionText:
            snapshot.scope === 'selection' ? snapshot.selectionText : null,
          scope: snapshot.scope,
          instruction: snapshot.instruction,
        });
        const existingDuplicate = telemetry.find(
          (record) =>
            record.requestFingerprint === requestFingerprint,
        );
        const request = buildEditRequest({
          engine,
          documentHtml: snapshot.documentHtml,
          selectionHtml: snapshot.selectionHtml,
          selectionText: snapshot.selectionText,
          selectionFrom: snapshot.selectionFrom,
          selectionTo: snapshot.selectionTo,
          scope: snapshot.scope,
          instruction: snapshot.instruction,
          preset: null,
          requestId,
          currentVersionId: snapshot.versionId,
        });
        const record = recordTelemetry({
          ...(await createTelemetryDraftForRequest({
            request,
            modelLabel: statuses.get(engine)?.modelLabel ?? 'Not configured',
            settings: observabilitySettings,
            documentMetadata: telemetryMetadataForDocument(
              documentSession,
              snapshot.documentHtml,
            ),
          })),
          duplicateOf: existingDuplicate?.id ?? null,
        });
        requestRecords.set(engine, record);
        requestStarts.set(engine, performance.now());
        return generateEdit.mutateAsync({ data: request });
      }),
    );

    const successful: EditResult[] = [];
    settled.forEach((result, index) => {
      const engine = engines[index];
      if (result.status === 'fulfilled') {
        successful.push(result.value);
        const telemetryRecord = requestRecords.get(engine);
        if (telemetryRecord) {
          updateTelemetryForRequest(
            requestId,
            engine,
            applyEditResult(telemetryRecord, result.value),
          );
        }
        const proposalMessageId = uuidv4();
        proposalMessageIds.current.set(
          `${result.value.requestId}:${engine}`,
          proposalMessageId,
        );
        appendConversationMessage(conversationId, {
          id: proposalMessageId,
          role: 'assistant',
          kind: 'proposal',
          text:
            result.value.assistantMessage ??
            'I prepared a suggested edit for your review.',
          timestamp: new Date().toISOString(),
          engine,
          engineLabel: result.value.engineLabel,
          scope: snapshot.scope,
          requestId: result.value.requestId,
          decision: 'pending',
        });
        logActivity('Edit completed', snapshot.instruction, {
          engine,
          scope,
          requestId,
          status: 'success',
          latencyMs: result.value.latencyMs,
          retryCount: result.value.retryCount,
          totalTokens: result.value.usage?.totalTokens ?? null,
        });
      } else {
        updateTelemetryForRequest(requestId, engine, {
          outcome: 'error',
          error: errorMessage(result.reason),
          latencyMs: Math.round(
            performance.now() - (requestStarts.get(engine) ?? performance.now()),
          ),
          retryCount: null,
        });
        appendConversationMessage(conversationId, {
          id: uuidv4(),
          role: 'assistant',
          kind: 'error',
          text: `${statuses.get(engine)?.label ?? engine}: ${errorMessage(result.reason)}`,
          timestamp: new Date().toISOString(),
          engine,
          engineLabel: statuses.get(engine)?.label,
          scope: snapshot.scope,
          requestId,
        });
        logActivity('Edit failed', errorMessage(result.reason), {
          engine,
          scope,
          requestId,
          status: 'error',
        });
        toast.error(`${statuses.get(engine)?.label}: ${errorMessage(result.reason)}`);
      }
    });

    setPendingResults(successful);
    setLatestResults(successful);
    setIsRunning(false);
    if (successful.length) toast.success('Suggested edit ready for your review.');
  };

  const removePendingResult = (target: EditResult) => {
    setPendingResults((current) =>
      current.filter(
        (item) =>
          !(
            item.engine === target.engine &&
            item.requestId === target.requestId
          ),
      ),
    );
  };

  /**
   * When one of several pending proposals (e.g. from a Compare run) is
   * accepted, every OTHER pending proposal must be explicitly resolved — never
   * silently discarded. Open hosted reviews are cancelled server-side FIRST
   * and only recorded as cancelled after the server confirms; if a
   * cancellation fails the acceptance is aborted so the sibling review stays
   * pending in the UI (accepting again retries). Completed proposals are then
   * recorded as rejected in telemetry, chat, and the edit-event history.
   */
  const resolveOtherPendingResults = async (
    accepted: EditResult,
  ): Promise<boolean> => {
    const others = pendingResults.filter(
      (item) =>
        !(
          item.engine === accepted.engine &&
          item.requestId === accepted.requestId
        ),
    );
    if (!others.length) return true;

    const resolution = await resolveSiblingProposals({
      siblings: others,
      cancelHostedReview: async (reviewId) => {
        await cancelReview.mutateAsync({ data: { reviewId } });
      },
      onCancelled: (other) => {
        updateTelemetryForRequest(other.requestId, other.engine, {
          outcome: 'cancelled',
          decisionState: 'stopped',
        });
        updateProposalMessage(other, { decision: 'cancelled' });
        logActivity('Hosted review cancelled', frozenRequest?.instruction ?? '', {
          engine: other.engine,
          scope: frozenRequest?.scope,
          requestId: other.requestId,
          status: 'stopped',
        });
        removePendingResult(other);
      },
      onRejected: (other) => {
        updateTelemetryForRequest(other.requestId, other.engine, {
          decisionState: 'rejected',
        });
        updateProposalMessage(other, { decision: 'rejected' });
        if (frozenRequest) {
          recordDecisionEvent(other, frozenRequest, 'rejected', null);
        }
        logActivity('Proposal rejected', frozenRequest?.instruction ?? '', {
          engine: other.engine,
          scope: frozenRequest?.scope,
          requestId: other.requestId,
          status: 'rejected',
        });
        removePendingResult(other);
      },
    });

    if (!resolution.ok) {
      toast.error(
        `${resolution.failed.engineLabel}: its open hosted review could not be cancelled, so nothing was accepted. Accept again to retry, or resolve that review directly.`,
      );
      return false;
    }
    return true;
  };

  const saveAcceptedResult = async (
    result: EditResult,
    options?: {
      /**
       * Set by the hosted accept flow, which already resolved every sibling
       * BEFORE sending the hosted accept request. Prevents double-recording
       * from this function's stale pendingResults closure.
       */
      siblingsAlreadyResolved?: boolean;
    },
  ) => {
    if (!frozenRequest) return;
    if (currentDocumentHtml !== frozenRequest.documentHtml) {
      toast.error(
        'This document changed since the proposal was generated. Discard or regenerate it.',
      );
      return;
    }

    // Resolve every other pending proposal BEFORE touching the document so a
    // failed hosted cancellation aborts the acceptance cleanly.
    if (!options?.siblingsAlreadyResolved) {
      setIsResolvingReview(true);
      try {
        if (!(await resolveOtherPendingResults(result))) return;
      } finally {
        setIsResolvingReview(false);
      }
    }

    let nextHtml = result.candidateDocumentHtml ?? null;
    if (!nextHtml && frozenRequest.scope === 'selection') {
      const replacement = result.proposedChanges[0]?.newHtml;
      if (replacement) {
        nextHtml = editorRef.current?.replaceRange(
          frozenRequest.selectionFrom,
          frozenRequest.selectionTo,
          replacement,
        ) ?? null;
      }
    }
    if (!nextHtml) {
      toast.error('This proposal does not contain an applicable document edit.');
      return;
    }

    const version = saveVersion(nextHtml, result.engineLabel, frozenRequest.instruction);
    const versionAfterNumber = versions.length + 1;
    updateTelemetryForRequest(result.requestId, result.engine, {
      decisionState: 'accepted',
    });
    recordDecisionEvent(result, frozenRequest, 'accepted', {
      id: version.id,
      number: versionAfterNumber,
    });
    updateProposalMessage(result, {
      decision: 'accepted',
      versionAfterId: version.id,
      versionAfterNumber,
    });
    logActivity('Proposal accepted', frozenRequest.instruction, {
      engine: result.engine,
      scope: frozenRequest.scope,
      requestId: result.requestId,
      status: 'accepted',
      latencyMs: result.latencyMs,
      retryCount: result.retryCount,
      totalTokens: result.usage?.totalTokens ?? null,
    });
    setPendingResults([]);
    setFrozenRequest(null);
    setInstruction('');
    toast.success(`Accepted — saved as version ${versionAfterNumber}.`);
  };

  const replaceHostedResult = (result: EditResult) => {
    setPendingResults((current) =>
      result.review
        ? current.map((item) => (item.engine === result.engine ? result : item))
        : current.filter((item) => item.engine !== result.engine),
    );
    setLatestResults(
      latestResults.map((item) =>
        item.engine === result.engine ? result : item,
      ),
    );
  };

  const telemetryPatchFor = (result: EditResult) => {
    const record = telemetry.find(
      (item) =>
        item.requestId === result.requestId && item.engine === result.engine,
    );
    return record ? applyEditResult(record, result) : {};
  };

  const acceptResult = async (result: EditResult) => {
    if (result.engine !== 'superdocs' || !result.review) {
      await saveAcceptedResult(result);
      return;
    }
    const review = result.review;
    setIsResolvingReview(true);
    try {
      // Contract: siblings are resolved — hosted cancellations
      // server-confirmed — BEFORE the selected hosted review is accepted.
      // A failed sibling cancellation aborts here, before decideReview, so
      // the selected proposal stays pending and retryable with no
      // server-side state changed.
      const flow = await runHostedAcceptFlow({
        resolveSiblings: () => resolveOtherPendingResults(result),
        decideReview: () =>
          decideReview.mutateAsync({
            data: {
              reviewId: review.reviewId,
              decision: 'accept',
              changeIds: result.proposedChanges.map((change) => change.id),
            },
          }),
      });
      if (flow.status === 'aborted-sibling-resolution') return;
      const resolved = flow.resolved;
      if (resolved.review) {
        updateTelemetryForRequest(result.requestId, result.engine, {
          ...telemetryPatchFor(resolved),
        });
        replaceHostedResult(resolved);
        toast.info(
          `SuperDocs has more suggestions — step ${resolved.review.batchNumber} is ready below.`,
        );
        return;
      }
      replaceHostedResult(resolved);
      updateTelemetryForRequest(result.requestId, result.engine, {
        ...telemetryPatchFor(resolved),
      });
      if (!resolved.candidateDocumentHtml) {
        toast.error(
          'SuperDocs accepted the batch but did not return document state. No local version was created.',
        );
        return;
      }
      await saveAcceptedResult(resolved, { siblingsAlreadyResolved: true });
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setIsResolvingReview(false);
    }
  };

  const rejectResult = async (result: EditResult) => {
    if (result.engine !== 'superdocs' || !result.review) {
      updateTelemetryForRequest(result.requestId, result.engine, {
        decisionState: 'rejected',
      });
      logActivity('Proposal rejected', frozenRequest?.instruction ?? '', {
        engine: result.engine,
        scope: frozenRequest?.scope,
        requestId: result.requestId,
        status: 'rejected',
      });
      if (frozenRequest) {
        recordDecisionEvent(result, frozenRequest, 'rejected', null);
      }
      updateProposalMessage(result, { decision: 'rejected' });
      setPendingResults((current) =>
        current.filter((item) => item.engine !== result.engine),
      );
      return;
    }
    setIsResolvingReview(true);
    try {
      const resolved = await decideReview.mutateAsync({
        data: {
          reviewId: result.review.reviewId,
          decision: 'reject',
          changeIds: result.proposedChanges.map((change) => change.id),
        },
      });
      logActivity('Hosted proposal rejected', frozenRequest?.instruction ?? '', {
        engine: result.engine,
        scope: frozenRequest?.scope,
        requestId: result.requestId,
        status: 'rejected',
      });
      updateTelemetryForRequest(result.requestId, result.engine, {
        ...telemetryPatchFor(resolved),
        decisionState: 'rejected',
      });
      replaceHostedResult(resolved);
      if (resolved.review) {
        toast.info(
          `SuperDocs sent a revised suggestion — step ${resolved.review.batchNumber} is ready below.`,
        );
      } else {
        if (frozenRequest) {
          recordDecisionEvent(result, frozenRequest, 'rejected', null);
        }
        updateProposalMessage(result, { decision: 'rejected' });
        toast.info('Suggestion rejected; the document was not changed.');
      }
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setIsResolvingReview(false);
    }
  };

  const rejectResults = async () => {
    for (const result of [...pendingResults]) {
      await rejectResult(result);
    }
    if (pendingResults.every((result) => !result.review)) {
      setFrozenRequest(null);
    }
  };

  const cancelHostedReview = async (result: EditResult) => {
    if (!result.review) return;
    setIsResolvingReview(true);
    try {
      await cancelReview.mutateAsync({ data: { reviewId: result.review.reviewId } });
      logActivity('Hosted review cancelled', frozenRequest?.instruction ?? '', {
        engine: result.engine,
        scope: frozenRequest?.scope,
        requestId: result.requestId,
        status: 'stopped',
      });
      updateTelemetryForRequest(result.requestId, result.engine, {
        outcome: 'cancelled',
        decisionState: 'stopped',
      });
      updateProposalMessage(result, { decision: 'cancelled' });
      setPendingResults((current) =>
        current.filter((item) => item.engine !== result.engine),
      );
      toast.info('SuperDocs review cancelled; the document was not changed.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setIsResolvingReview(false);
    }
  };

  const askForAnotherApproach = (result: EditResult) => {
    const original = frozenRequest?.instruction ?? '';
    void rejectResult(result);
    setInstruction(original);
    window.setTimeout(() => composerRef.current?.focus(), 80);
    toast.info('Rejected. Adjust the instruction and send it again.');
  };

  const startNewChat = () => {
    setActiveConversation(null);
    runConversationIdRef.current = null;
    proposalMessageIds.current.clear();
  };

  const latest = latestResults[0];
  const formatting = analyzeFormatting(currentDocumentHtml);

  const assistantPanel = (
    <AssistantPanel
      engineMode={engineMode}
      onEngineModeChange={setEngineMode}
      statuses={statuses as Map<string, EngineStatusInfo>}
      selectedConfigured={selectedConfigured}
      messages={activeConversation?.messages ?? []}
      onNewChat={startNewChat}
      isRunning={isRunning}
      elapsedMs={elapsedMs}
      pendingResults={pendingResults}
      reviewScope={frozenRequest?.scope ?? null}
      scope={scope}
      selectionText={selectionText}
      onUseWholeDocument={() => setScope('document')}
      instruction={instruction}
      onInstructionChange={setInstruction}
      onSubmit={() => void handleRun()}
      canSubmit={
        !isRunning &&
        Boolean(instruction.trim()) &&
        selectedConfigured &&
        !preflight.hardExceeded
      }
      preflight={preflight}
      diyCostUsd={diyPreflight.usd}
      hardBudgetChars={observabilitySettings.contextBudgetChars}
      developerMode={preferences.developerMode}
      busyReview={isResolvingReview}
      onAccept={(result) => void acceptResult(result)}
      onReject={(result) => void rejectResult(result)}
      onRejectAll={() => void rejectResults()}
      onAskAgain={askForAnotherApproach}
      onCancelHosted={(result) => void cancelHostedReview(result)}
      composerRef={composerRef}
      devMetrics={{
        diyModelLabel: statuses.get('diy')?.modelLabel ?? 'Not configured',
        superdocsModelLabel:
          statuses.get('superdocs')?.modelLabel ?? 'Not configured',
        promptVersion: DIY_PROMPT_VERSION,
        chunkSummary: String(formatting.chunkIds),
        latestLatencyMs: latest?.latencyMs ?? null,
        latestTokens: latest?.usage?.totalTokens ?? null,
        latestRetries: latest?.retryCount ?? null,
      }}
    />
  );

  if (params.documentId && params.documentId !== documentSession.id) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-md text-center">
          <FileText className="mx-auto h-10 w-10 text-muted-foreground" />
          <h1 className="mt-4 text-lg font-semibold">
            That document is not in this session
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This workspace keeps one active document at a time. The document you
            are looking for was part of an earlier session — its conversations
            and edit decisions are still available in History.
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <Button onClick={() => navigate('/')} data-testid="button-open-current-document">
              Open current document
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate('/history')}
              data-testid="button-view-history"
            >
              View history
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const onboarding = ONBOARDING_STEPS[onboardingStep];
  const OnboardingIcon = onboarding.icon;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3 md:px-4">
        <button
          type="button"
          onClick={() => {
            setRenameValue(documentTitle);
            setRenameOpen(true);
          }}
          className="group flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-left hover:bg-muted"
          aria-label={`Rename document ${documentTitle}`}
          data-testid="button-rename-document"
        >
          <h1 className="truncate text-sm font-semibold">{documentTitle}</h1>
          <Pencil className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
        </button>

        {documentSession.sourceType === 'imported' &&
        documentSession.importedDocument ? (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="Imported document details"
                data-testid="badge-document-source"
              >
                <Badge variant="outline" className="text-[10px]">
                  Uploaded · {documentSession.importedDocument.format.toUpperCase()}
                </Badge>
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-72 text-xs" align="start">
              <p className="mb-2 truncate font-medium">
                {documentSession.importedDocument.originalFileName}
              </p>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-muted-foreground">
                <dt>File size</dt>
                <dd className="text-right">
                  {(documentSession.importedDocument.fileSize / 1024).toFixed(1)} KB
                </dd>
                <dt>Text</dt>
                <dd className="text-right">
                  {documentSession.importedDocument.wordCount.toLocaleString()} words
                </dd>
                <dt>Import time</dt>
                <dd className="text-right">
                  {documentSession.importedDocument.importDurationMs} ms
                </dd>
                <dt>Storage</dt>
                <dd className="text-right">
                  {documentSession.importedDocument.persistence === 'persistent'
                    ? 'Saved in this browser'
                    : 'This session only'}
                </dd>
              </dl>
              {documentSession.importedDocument.importWarnings.map((warning) => (
                <p
                  key={warning}
                  className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px] text-amber-800 dark:text-amber-200"
                >
                  {warning}
                </p>
              ))}
            </PopoverContent>
          </Popover>
        ) : (
          <Badge
            variant="secondary"
            className="text-[10px]"
            data-testid="badge-document-source"
          >
            Demo
          </Badge>
        )}

        <span
          className="hidden items-center gap-1 text-[11px] text-muted-foreground sm:flex"
          aria-live="polite"
          data-testid="text-save-state"
        >
          {persistenceMode === 'authenticated' ? (
            saveStatus === 'saving' ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Saving…
              </>
            ) : saveStatus === 'error' ? (
              <>
                <AlertCircle className="h-3 w-3 text-destructive" />
                Save failed — retrying
              </>
            ) : (
              <>
                <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                Saved to your account
              </>
            )
          ) : saveFlash ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <CheckCircle2 className="h-3 w-3 text-emerald-500" />
              Saved locally
            </>
          )}
        </span>

        <Link
          href="/history"
          className="hidden sm:block"
          data-testid="link-version-chip"
        >
          <Badge variant="outline" className="font-mono text-[10px]">
            v{versions.length}
          </Badge>
        </Link>

        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/history" data-testid="link-history">
              <History className="h-4 w-4 sm:mr-1.5" />
              <span className="hidden sm:inline">History</span>
            </Link>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="More document actions"
                data-testid="button-document-menu"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem
                onSelect={() => {
                  setRenameValue(documentTitle);
                  setRenameOpen(true);
                }}
                data-testid="menu-item-rename"
              >
                <Pencil className="mr-2 h-4 w-4" />
                Rename document
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => setNewDocumentOpen(true)}
                disabled={isImporting || isRunning}
                data-testid="menu-item-new-document"
              >
                <FilePlus2 className="mr-2 h-4 w-4" />
                New document…
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => fileInputRef.current?.click()}
                disabled={isImporting || isRunning}
                data-testid="menu-item-upload"
              >
                <Upload className="mr-2 h-4 w-4" />
                Upload a replacement…
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => restoreOriginal()}
                data-testid="menu-item-restore-original"
              >
                <RotateCcw className="mr-2 h-4 w-4" />
                Restore original document
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => {
                  if (
                    window.confirm(
                      'Reset the demo? This clears the document, versions, conversations, telemetry, and activity.',
                    )
                  ) {
                    resetAll();
                    clearEditorRequestState();
                    toast.success('Demo reset.');
                  }
                }}
                data-testid="menu-item-reset-demo"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Reset demo…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div
          className="relative min-w-0 flex-1 bg-muted/30"
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDropActive(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setIsDropActive(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDropActive(false);
            void handleImportFile(event.dataTransfer.files?.[0] ?? null);
          }}
        >
          {isDropActive && (
            <div className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/5">
              <p className="rounded-md bg-background px-3 py-1.5 text-sm font-medium text-primary shadow-sm">
                Drop to import — DOCX, HTML, TXT, or PDF · up to{' '}
                {(DEFAULT_MAX_IMPORT_BYTES / 1024 / 1024).toFixed(0)} MB
              </p>
            </div>
          )}
          {isImporting && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60">
              <p className="flex items-center gap-2 rounded-md bg-background px-3 py-2 text-sm shadow-md">
                <Loader2 className="h-4 w-4 animate-spin" />
                Parsing document…
              </p>
            </div>
          )}
          <div className="mx-auto flex h-full max-w-[860px] flex-col px-3 py-3 md:px-6 md:py-5">
            {importError && (
              <p className="mb-2 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                {importError}
              </p>
            )}
            <div className="min-h-0 flex-1">
              <RichTextEditor
                ref={editorRef}
                content={currentDocumentHtml}
                onChange={setDocumentHtml}
                onSelectionChange={handleSelectionChange}
              />
            </div>
          </div>
        </div>

        {isDesktopPanel && (
          <aside
            className="w-[400px] shrink-0 border-l 2xl:w-[440px]"
            aria-label="AI Assistant"
          >
            {assistantPanel}
          </aside>
        )}
      </div>

      {!isDesktopPanel && (
        <>
          <Drawer
            open={assistantDrawerOpen}
            onOpenChange={setAssistantDrawerOpen}
            snapPoints={[1]}
            activeSnapPoint={assistantDrawerSnap}
            setActiveSnapPoint={setAssistantDrawerSnap}
            fixed
          >
            <DrawerContent className="h-[100dvh] max-h-[100dvh] overflow-hidden rounded-none">
              <DrawerHeader className="sr-only">
                <DrawerTitle>AI Assistant</DrawerTitle>
              </DrawerHeader>
              <div className="min-h-0 flex-1">{assistantPanel}</div>
            </DrawerContent>
          </Drawer>
          {!assistantDrawerOpen && (
            <Button
              className="fixed bottom-4 right-4 z-40 h-12 rounded-full px-4 shadow-lg"
              onClick={() => setAssistantDrawerOpen(true)}
              data-testid="button-open-assistant"
            >
              <Sparkles className="mr-2 h-4 w-4" />
              Assistant
              {pendingResults.length > 0 && (
                <span className="ml-2 flex h-5 min-w-5 items-center justify-center rounded-full bg-background px-1 text-[11px] font-semibold text-foreground">
                  {pendingResults.length}
                </span>
              )}
            </Button>
          )}
        </>
      )}

      <input
        ref={fileInputRef}
        type="file"
        className="sr-only"
        aria-label="Upload a document"
        accept=".docx,.html,.htm,.txt,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/html,text/plain,application/pdf"
        onChange={(event) => void handleImportFile(event.target.files?.[0] ?? null)}
      />

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Rename document</DialogTitle>
            <DialogDescription>
              The name is only used to identify this document in your workspace.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && renameValue.trim()) {
                renameDocument(renameValue.trim());
                setRenameOpen(false);
                toast.success('Document renamed.');
              }
            }}
            aria-label="Document name"
            data-testid="input-document-name"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!renameValue.trim()}
              onClick={() => {
                renameDocument(renameValue.trim());
                setRenameOpen(false);
                toast.success('Document renamed.');
              }}
              data-testid="button-save-document-name"
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={newDocumentOpen} onOpenChange={setNewDocumentOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New document</DialogTitle>
            <DialogDescription>
              Starting a new document begins a fresh session. Your conversations
              and edit decisions stay available in History.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <button
              type="button"
              onClick={() => {
                setNewDocumentOpen(false);
                selectCanonicalDocument();
              }}
              disabled={isImporting || isRunning}
              className="flex items-start gap-3 rounded-md border p-3 text-left transition hover:border-primary/40 hover:bg-accent/40 disabled:opacity-50"
              data-testid="button-new-standard-document"
            >
              <FileText className="mt-0.5 h-5 w-5 text-primary" />
              <span>
                <span className="block text-sm font-medium">
                  Standard test document
                </span>
                <span className="block text-xs text-muted-foreground">
                  The built-in demo letter — ideal for trying edits and fair
                  engine comparisons.
                </span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                setNewDocumentOpen(false);
                fileInputRef.current?.click();
              }}
              disabled={isImporting || isRunning}
              className="flex items-start gap-3 rounded-md border p-3 text-left transition hover:border-primary/40 hover:bg-accent/40 disabled:opacity-50"
              data-testid="button-new-upload-document"
            >
              <Upload className="mt-0.5 h-5 w-5 text-primary" />
              <span>
                <span className="block text-sm font-medium">Upload a document</span>
                <span className="block text-xs text-muted-foreground">
                  DOCX, HTML, TXT, or PDF · up to{' '}
                  {(DEFAULT_MAX_IMPORT_BYTES / 1024 / 1024).toFixed(0)} MB.
                </span>
              </span>
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={onboardingOpen}
        onOpenChange={(open) => {
          if (!open) {
            setOnboardingOpen(false);
            setPreference('onboardingDismissed', true);
          }
        }}
      >
        <DialogContent className="sm:max-w-sm" data-testid="dialog-onboarding">
          <DialogHeader>
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent">
              <OnboardingIcon className="h-5 w-5 text-primary" />
            </span>
            <DialogTitle className="text-center">{onboarding.title}</DialogTitle>
            <DialogDescription className="text-center">
              {onboarding.body}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center justify-center gap-1.5">
            {ONBOARDING_STEPS.map((step, index) => (
              <span
                key={step.title}
                className={`h-1.5 rounded-full transition-all ${
                  index === onboardingStep ? 'w-6 bg-primary' : 'w-1.5 bg-muted'
                }`}
              />
            ))}
          </div>
          <DialogFooter className="sm:justify-between">
            <Button
              variant="ghost"
              onClick={() => {
                setOnboardingOpen(false);
                setPreference('onboardingDismissed', true);
              }}
              data-testid="button-onboarding-skip"
            >
              Skip tour
            </Button>
            <Button
              onClick={() => {
                if (onboardingStep < ONBOARDING_STEPS.length - 1) {
                  setOnboardingStep(onboardingStep + 1);
                } else {
                  setOnboardingOpen(false);
                  setPreference('onboardingDismissed', true);
                }
              }}
              data-testid="button-onboarding-next"
            >
              {onboardingStep < ONBOARDING_STEPS.length - 1 ? 'Next' : 'Get started'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
