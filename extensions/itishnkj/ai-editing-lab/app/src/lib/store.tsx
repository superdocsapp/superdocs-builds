import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  createGuestPersistence,
  type LabPersistence,
  type WorkspaceSaveStatus,
} from './persistence';
import { v4 as uuidv4 } from 'uuid';
import type {
  EditInputEngine,
  EditInputScope,
  EditResult,
} from '@workspace/api-client-react';
import { INITIAL_DOCUMENT_HTML } from './constants';
import type { BenchmarkObservation } from './experiment';
import {
  DEFAULT_TELEMETRY_SETTINGS,
  TELEMETRY_SCHEMA_VERSION,
  type TelemetryRecord,
  type TelemetrySettings,
  type DocumentTelemetryMetadata,
} from './telemetry';
import type {
  DocumentSourceType,
  ImportedDocument,
  ImportPersistence,
} from './import/types';
import {
  adaptPersistedHistory,
  appendMessageToConversations,
  updateMessageInConversations,
  type ChatMessage,
  type Conversation,
  type EditEvent,
} from './history';

export type ActivityStatus =
  | 'pending'
  | 'success'
  | 'error'
  | 'accepted'
  | 'rejected'
  | 'stopped';

export type ActivityLogEntry = {
  id: string;
  timestamp: string;
  action: string;
  details: string;
  user: string;
  engine?: EditInputEngine | 'both';
  status?: ActivityStatus;
  requestId?: string;
  scope?: EditInputScope;
  latencyMs?: number | null;
  retryCount?: number | null;
  totalTokens?: number | null;
};

export type ActivityMetadata = Omit<
  ActivityLogEntry,
  'id' | 'timestamp' | 'action' | 'details' | 'user'
>;

export type DocumentVersion = {
  id: string;
  timestamp: string;
  html: string;
  author: string;
  description: string;
};

export type DocumentSession = {
  id: string;
  sourceType: DocumentSourceType;
  originalHtml: string;
  importedDocument: ImportedDocument | null;
  persistence: ImportPersistence;
  /** Optional user-assigned display name; derived from the source when absent. */
  title?: string;
  /**
   * Unique identity for THIS session instance. Telemetry keeps using `id`
   * (every canonical session is 'canonical-demo' for benchmark
   * comparability), but chat/edit history is scoped by sessionKey so a new
   * standard-document session never inherits an earlier session's
   * conversations. Assigned at load time for legacy snapshots.
   */
  sessionKey?: string;
};

export function documentSessionTitle(session: DocumentSession): string {
  if (session.title?.trim()) return session.title.trim();
  if (session.importedDocument) {
    return session.importedDocument.originalFileName.replace(/\.[^.]+$/, '');
  }
  return 'Quarterly Client Update';
}

export type ReviewerScore = {
  instructionAdherence: number;
  writingQuality: number;
  formattingPreservation: number;
  overallUsefulness: number;
  notes: string;
};

export type CompareRun = {
  id: string;
  timestamp: string;
  snapshotHtml: string;
  startingDocumentHash: string;
  startingVersionId: string;
  instruction: string;
  scope: EditInputScope;
  diyResult: EditResult | null;
  superdocsResult: EditResult | null;
  diyError: string | null;
  superdocsError: string | null;
  diyReview: ReviewerScore;
  superdocsReview: ReviewerScore;
};

export type BenchmarkRun = {
  id: string;
  timestamp: string;
  config: {
    declaredBudgetCap: number;
    runsPerTest: number;
    engines: EditInputEngine[];
    maximumRequests: number;
    source?: DocumentSourceType;
    documentId?: string;
  };
  observations: BenchmarkObservation[];
  actualSpendReported: number | null;
  totalRuntimeMs: number;
  stopped: boolean;
};

export type PersistedState = {
  currentDocumentHtml: string;
  documentSession: DocumentSession;
  versions: DocumentVersion[];
  activity: ActivityLogEntry[];
  compareRuns: CompareRun[];
  benchmarkRuns: BenchmarkRun[];
  latestResults: EditResult[];
  telemetry: TelemetryRecord[];
  observabilitySettings: TelemetrySettings;
  conversations: Conversation[];
  editEvents: EditEvent[];
  activeConversationId: string | null;
};

interface LabState extends PersistedState {
  /** Where this session's data lives: guest localStorage or the user's account. */
  persistenceMode: 'guest' | 'authenticated';
  /** Save state of the active persistence provider ('local' for guests). */
  saveStatus: WorkspaceSaveStatus;
  /** Force any queued account save to finish (used before sign-out). */
  flushPersistence: () => Promise<void>;
  setDocumentHtml: (html: string) => void;
  startImportedDocument: (document: ImportedDocument) => void;
  startCanonicalDocument: () => void;
  restoreDocumentOriginal: () => void;
  renameDocument: (title: string) => void;
  saveVersion: (
    html: string,
    author: string,
    description: string,
  ) => DocumentVersion;
  logActivity: (
    action: string,
    details: string,
    metadata?: ActivityMetadata,
  ) => void;
  addCompareRun: (
    run: Omit<CompareRun, 'id' | 'timestamp'>,
  ) => CompareRun;
  updateCompareRun: (id: string, updates: Partial<CompareRun>) => void;
  addBenchmarkRun: (
    run: Omit<BenchmarkRun, 'timestamp'>,
  ) => BenchmarkRun;
  updateLatestBenchmark: (updates: Partial<BenchmarkRun>) => void;
  setLatestResults: (results: EditResult[]) => void;
  recordTelemetry: (
    record: Omit<TelemetryRecord, 'id' | 'createdAt'>,
  ) => TelemetryRecord;
  updateTelemetry: (
    id: string,
    updates: Partial<TelemetryRecord>,
  ) => void;
  updateTelemetryForRequest: (
    requestId: string,
    engine: EditInputEngine,
    updates: Partial<TelemetryRecord>,
  ) => void;
  clearTelemetry: () => void;
  setObservabilitySettings: (settings: Partial<TelemetrySettings>) => void;
  startConversation: (
    seed: Pick<
      Conversation,
      'documentId' | 'documentTitle' | 'title' | 'sessionKey'
    >,
  ) => Conversation;
  appendConversationMessage: (
    conversationId: string,
    message: ChatMessage,
  ) => void;
  updateConversationMessage: (
    conversationId: string,
    messageId: string,
    updates: Partial<ChatMessage>,
  ) => void;
  setActiveConversation: (conversationId: string | null) => void;
  addEditEvent: (event: EditEvent) => void;
  resetAll: () => void;
}

const LabContext = createContext<LabState | undefined>(undefined);

function canonicalSession(): DocumentSession {
  return {
    id: 'canonical-demo',
    sourceType: 'canonical',
    originalHtml: INITIAL_DOCUMENT_HTML,
    importedDocument: null,
    persistence: 'persistent',
    sessionKey: uuidv4(),
  };
}

function originalVersion(session: DocumentSession): DocumentVersion {
  return {
    id: uuidv4(),
    timestamp: new Date().toISOString(),
    html: session.originalHtml,
    author: 'System',
    description:
      session.sourceType === 'imported'
        ? `Version 1 — Imported original (${session.importedDocument?.originalFileName ?? 'document'})`
        : 'Version 1 — Original',
  };
}

function initialState(): PersistedState {
  const session = canonicalSession();
  return {
    currentDocumentHtml: INITIAL_DOCUMENT_HTML,
    documentSession: session,
    versions: [originalVersion(session)],
    activity: [],
    compareRuns: [],
    benchmarkRuns: [],
    latestResults: [],
    telemetry: [],
    observabilitySettings: { ...DEFAULT_TELEMETRY_SETTINGS },
    conversations: [],
    editEvents: [],
    activeConversationId: null,
  };
}

function migrateTelemetry(records: unknown[]): TelemetryRecord[] {
  return records.flatMap((record) => {
    if (!record || typeof record !== 'object') return [];
    const raw = record as Record<string, unknown>;
    if (raw.schemaVersion === TELEMETRY_SCHEMA_VERSION) {
      return [raw as unknown as TelemetryRecord];
    }
    if (raw.schemaVersion === 'telemetry-v1' && typeof raw.id === 'string') {
      const { exactRequestHash: _requestHash, instructionHash: _instructionHash, ...safe } =
        raw;
      return [
        {
          ...safe,
          schemaVersion: TELEMETRY_SCHEMA_VERSION,
          requestFingerprint: `legacy-unavailable-${raw.id}`,
          instructionFingerprint: `legacy-unavailable-${raw.id}`,
        } as TelemetryRecord,
      ];
    }
    return [];
  });
}

/**
 * Adapts a raw persisted snapshot (from guest localStorage or the account
 * workspace API) into a complete PersistedState, applying the same
 * migrations regardless of where the snapshot came from.
 */
export function adaptPersistedState(raw: unknown): PersistedState {
  try {
    if (raw && typeof raw === 'object') {
      const parsed = raw as Partial<PersistedState>;
      return {
        ...initialState(),
        ...parsed,
        documentSession: (() => {
          const session =
            parsed.documentSession &&
            typeof parsed.documentSession === 'object' &&
            'sourceType' in parsed.documentSession
              ? (parsed.documentSession as DocumentSession)
              : canonicalSession();
          // Legacy snapshots predate session keys; assigning one here keeps
          // the current session's future history correctly scoped.
          return session.sessionKey
            ? session
            : { ...session, sessionKey: uuidv4() };
        })(),
        telemetry: Array.isArray(parsed.telemetry)
          ? migrateTelemetry(parsed.telemetry)
          : [],
        observabilitySettings: {
          ...DEFAULT_TELEMETRY_SETTINGS,
          ...(parsed.observabilitySettings ?? {}),
        },
        // Pre-redesign snapshots have no chat history; they must load with
        // empty history instead of being discarded.
        ...adaptPersistedHistory(parsed),
      };
    }
  } catch {
    // Corrupt snapshots fall through to a fresh initial state.
  }
  return initialState();
}

const WORKSPACE_LOAD_ERROR =
  "Couldn't load your workspace. Check your connection and try again.";

export function LabProvider({
  children,
  persistence,
  hydrationFallback,
}: {
  children: React.ReactNode;
  /** Server-backed storage for signed-in users; omit for guest localStorage. */
  persistence?: LabPersistence;
  /** Rendered while a signed-in user's workspace loads or fails to load. */
  hydrationFallback?: (props: {
    error: string | null;
    retry: () => void;
  }) => React.ReactNode;
}) {
  // The provider is fixed for the lifetime of this mount; identity changes
  // remount the provider tree with a new `key` in App.tsx.
  const [provider] = useState<LabPersistence>(
    () => persistence ?? createGuestPersistence(),
  );
  const [state, setState] = useState<PersistedState>(() =>
    provider.mode === 'guest'
      ? adaptPersistedState(provider.loadSync())
      : initialState(),
  );
  const [hydrated, setHydrated] = useState(provider.mode === 'guest');
  const [hydrationError, setHydrationError] = useState<string | null>(null);
  const [hydrationAttempt, setHydrationAttempt] = useState(0);
  const [saveStatus, setSaveStatus] = useState<WorkspaceSaveStatus>(
    provider.mode === 'guest' ? 'local' : 'saved',
  );
  // The freshly loaded (or initial) state must not immediately round-trip
  // back into storage: signed-in users would re-upload what the server just
  // sent, and merely visiting would create a guest snapshot.
  const skipNextPersistRef = useRef(true);

  useEffect(() => {
    if (provider.mode !== 'authenticated' || hydrated) return;
    let cancelled = false;
    setHydrationError(null);
    provider
      .load()
      .then((raw) => {
        if (cancelled) return;
        if (raw != null) setState(adaptPersistedState(raw));
        skipNextPersistRef.current = true;
        setHydrated(true);
      })
      .catch(() => {
        if (!cancelled) setHydrationError(WORKSPACE_LOAD_ERROR);
      });
    return () => {
      cancelled = true;
    };
  }, [provider, hydrated, hydrationAttempt]);

  useEffect(() => {
    if (provider.mode !== 'authenticated') return;
    return provider.onStatusChange(setSaveStatus);
  }, [provider]);

  useEffect(() => {
    return () => {
      if (provider.mode === 'authenticated') provider.dispose();
    };
  }, [provider]);

  useEffect(() => {
    if (!hydrated) return;
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    provider.persist(state);
  }, [state, hydrated, provider]);

  const flushPersistence = useCallback(async () => {
    if (provider.mode === 'authenticated') await provider.flush();
  }, [provider]);

  const retryHydration = useCallback(() => {
    setHydrationError(null);
    setHydrationAttempt((attempt) => attempt + 1);
  }, []);

  const logActivity: LabState['logActivity'] = (
    action,
    details,
    metadata = {},
  ) => {
    setState((current) => ({
      ...current,
      activity: [
        {
          id: uuidv4(),
          timestamp: new Date().toISOString(),
          action,
          details,
          user: 'Evaluator',
          ...metadata,
        },
        ...current.activity,
      ],
    }));
  };

  const setDocumentHtml = (html: string) => {
    setState((current) => ({ ...current, currentDocumentHtml: html }));
  };

  const startImportedDocument = (document: ImportedDocument) => {
    const session: DocumentSession = {
      id: document.id,
      sourceType: 'imported',
      originalHtml: document.html,
      importedDocument: document,
      persistence: document.persistence,
      sessionKey: uuidv4(),
    };
    const original = originalVersion(session);
    setState((current) => ({
      ...current,
      documentSession: session,
      currentDocumentHtml: document.html,
      versions: [original],
      compareRuns: [],
      benchmarkRuns: [],
      latestResults: [],
      // Chat + edit history intentionally survive a document replacement so
      // the History page can show earlier sessions.
      activeConversationId: null,
      activity: [
        {
          id: uuidv4(),
          timestamp: original.timestamp,
          action: 'Document imported',
          details: `${document.originalFileName} · ${document.format.toUpperCase()} · ${document.wordCount.toLocaleString()} words`,
          user: 'Evaluator',
          status: 'accepted',
        },
        ...current.activity,
      ],
    }));
  };

  const startCanonicalDocument = () => {
    const session = canonicalSession();
    const original = originalVersion(session);
    setState((current) => ({
      ...current,
      documentSession: session,
      currentDocumentHtml: session.originalHtml,
      versions: [original],
      compareRuns: [],
      benchmarkRuns: [],
      latestResults: [],
      activeConversationId: null,
      activity: [
        {
          id: uuidv4(),
          timestamp: original.timestamp,
          action: 'Standard document selected',
          details: 'Started a new session with the controlled benchmark document.',
          user: 'Evaluator',
          status: 'accepted',
        },
        ...current.activity,
      ],
    }));
  };

  const restoreDocumentOriginal = () => {
    setState((current) => {
      const version: DocumentVersion = {
        id: uuidv4(),
        timestamp: new Date().toISOString(),
        html: current.documentSession.originalHtml,
        author: 'System',
        description:
          current.documentSession.sourceType === 'imported'
            ? `Restored imported original (${current.documentSession.importedDocument?.originalFileName ?? 'document'})`
            : 'Restored canonical original',
      };
      return {
        ...current,
        currentDocumentHtml: version.html,
        versions: [version, ...current.versions],
        latestResults: [],
        activity: [
          {
            id: uuidv4(),
            timestamp: version.timestamp,
            action: 'Document original restored',
            details: version.description,
            user: 'Evaluator',
            status: 'accepted',
          },
          ...current.activity,
        ],
      };
    });
  };

  const saveVersion = (
    html: string,
    author: string,
    description: string,
  ): DocumentVersion => {
    const version: DocumentVersion = {
      id: uuidv4(),
      timestamp: new Date().toISOString(),
      html,
      author,
      description,
    };
    setState((current) => ({
      ...current,
      currentDocumentHtml: html,
      versions: [version, ...current.versions],
      activity: [
        {
          id: uuidv4(),
          timestamp: version.timestamp,
          action: 'Version saved',
          details: `${description} by ${author}`,
          user: 'Evaluator',
          status: 'accepted',
        },
        ...current.activity,
      ],
    }));
    return version;
  };

  const renameDocument = (title: string) => {
    const cleaned = title.trim();
    if (!cleaned) return;
    setState((current) => ({
      ...current,
      documentSession: { ...current.documentSession, title: cleaned },
      activity: [
        {
          id: uuidv4(),
          timestamp: new Date().toISOString(),
          action: 'Document renamed',
          details: `Renamed to “${cleaned}”`,
          user: 'Evaluator',
          status: 'accepted',
        },
        ...current.activity,
      ],
    }));
  };

  const addCompareRun: LabState['addCompareRun'] = (run) => {
    const complete: CompareRun = {
      ...run,
      id: uuidv4(),
      timestamp: new Date().toISOString(),
    };
    setState((current) => ({
      ...current,
      compareRuns: [complete, ...current.compareRuns],
      activity: [
        {
          id: uuidv4(),
          timestamp: complete.timestamp,
          action: 'Compare completed',
          details: run.instruction,
          user: 'Evaluator',
          engine: 'both',
          status:
            run.diyResult || run.superdocsResult ? 'success' : 'error',
          scope: run.scope,
        },
        ...current.activity,
      ],
    }));
    return complete;
  };

  const updateCompareRun = (id: string, updates: Partial<CompareRun>) => {
    setState((current) => ({
      ...current,
      compareRuns: current.compareRuns.map((run) =>
        run.id === id ? { ...run, ...updates } : run,
      ),
    }));
  };

  const addBenchmarkRun: LabState['addBenchmarkRun'] = (run) => {
    const complete: BenchmarkRun = {
      ...run,
      timestamp: new Date().toISOString(),
    };
    setState((current) => ({
      ...current,
      benchmarkRuns: [complete, ...current.benchmarkRuns],
      activity: [
        {
          id: uuidv4(),
          timestamp: complete.timestamp,
          action: run.stopped ? 'Benchmark stopped' : 'Benchmark completed',
          details: `${run.observations.length}/${run.config.maximumRequests} requests recorded`,
          user: 'Evaluator',
          engine:
            run.config.engines.length === 2
              ? 'both'
              : run.config.engines[0],
          status: run.stopped ? 'stopped' : 'success',
        },
        ...current.activity,
      ],
    }));
    return complete;
  };

  const updateLatestBenchmark = (updates: Partial<BenchmarkRun>) => {
    setState((current) => ({
      ...current,
      benchmarkRuns: current.benchmarkRuns.map((run, index) =>
        index === 0 ? { ...run, ...updates } : run,
      ),
    }));
  };

  const setLatestResults = (latestResults: EditResult[]) => {
    setState((current) => ({ ...current, latestResults }));
  };

  const recordTelemetry: LabState['recordTelemetry'] = (record) => {
    const complete: TelemetryRecord = {
      ...record,
      id: uuidv4(),
      createdAt: new Date().toISOString(),
    };
    setState((current) => ({
      ...current,
      telemetry: [complete, ...current.telemetry],
    }));
    return complete;
  };

  const updateTelemetry: LabState['updateTelemetry'] = (id, updates) => {
    setState((current) => ({
      ...current,
      telemetry: current.telemetry.map((record) =>
        record.id === id ? { ...record, ...updates } : record,
      ),
    }));
  };

  const updateTelemetryForRequest: LabState['updateTelemetryForRequest'] = (
    requestId,
    engine,
    updates,
  ) => {
    setState((current) => ({
      ...current,
      telemetry: current.telemetry.map((record) =>
        record.requestId === requestId && record.engine === engine
          ? { ...record, ...updates }
          : record,
      ),
    }));
  };

  const clearTelemetry = () => {
    setState((current) => ({ ...current, telemetry: [] }));
  };

  const setObservabilitySettings = (
    settings: Partial<TelemetrySettings>,
  ) => {
    setState((current) => ({
      ...current,
      observabilitySettings: {
        ...current.observabilitySettings,
        ...settings,
      },
    }));
  };

  const startConversation: LabState['startConversation'] = (seed) => {
    const now = new Date().toISOString();
    const conversation: Conversation = {
      id: uuidv4(),
      documentId: seed.documentId,
      documentTitle: seed.documentTitle,
      sessionKey: seed.sessionKey,
      title: seed.title,
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    setState((current) => ({
      ...current,
      conversations: [conversation, ...current.conversations],
      activeConversationId: conversation.id,
    }));
    return conversation;
  };

  const appendConversationMessage: LabState['appendConversationMessage'] = (
    conversationId,
    message,
  ) => {
    setState((current) => ({
      ...current,
      conversations: appendMessageToConversations(
        current.conversations,
        conversationId,
        message,
      ),
    }));
  };

  const updateConversationMessage: LabState['updateConversationMessage'] = (
    conversationId,
    messageId,
    updates,
  ) => {
    setState((current) => ({
      ...current,
      conversations: updateMessageInConversations(
        current.conversations,
        conversationId,
        messageId,
        updates,
      ),
    }));
  };

  const setActiveConversation = (conversationId: string | null) => {
    setState((current) => ({
      ...current,
      activeConversationId: conversationId,
    }));
  };

  const addEditEvent = (event: EditEvent) => {
    setState((current) => ({
      ...current,
      editEvents: [event, ...current.editEvents],
    }));
  };

  const resetAll = () => setState(initialState());

  if (provider.mode === 'authenticated' && !hydrated) {
    return (
      <>
        {hydrationFallback ? (
          hydrationFallback({ error: hydrationError, retry: retryHydration })
        ) : (
          <div className="flex min-h-svh items-center justify-center bg-background text-sm text-muted-foreground">
            {hydrationError ?? 'Loading your workspace…'}
          </div>
        )}
      </>
    );
  }

  return (
    <LabContext.Provider
      value={{
        ...state,
        persistenceMode: provider.mode,
        saveStatus,
        flushPersistence,
        setDocumentHtml,
        startImportedDocument,
        startCanonicalDocument,
        restoreDocumentOriginal,
        renameDocument,
        saveVersion,
        logActivity,
        addCompareRun,
        updateCompareRun,
        addBenchmarkRun,
        updateLatestBenchmark,
        setLatestResults,
        recordTelemetry,
        updateTelemetry,
        updateTelemetryForRequest,
        clearTelemetry,
        setObservabilitySettings,
        startConversation,
        appendConversationMessage,
        updateConversationMessage,
        setActiveConversation,
        addEditEvent,
        resetAll,
      }}
    >
      {children}
    </LabContext.Provider>
  );
}

export function useLabStore() {
  const context = useContext(LabContext);
  if (!context) throw new Error('useLabStore must be used within LabProvider');
  return context;
}

export function telemetryMetadataForDocument(
  session: DocumentSession,
  currentHtml: string,
): DocumentTelemetryMetadata {
  if (session.importedDocument) {
    return {
      documentId: session.id,
      documentSource: 'imported',
      fileType: session.importedDocument.format,
      documentWordCount: session.importedDocument.wordCount,
      documentCharacterCount: session.importedDocument.characterCount,
    };
  }
  const plainText = currentHtml
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return {
    documentId: session.id,
    documentSource: 'canonical',
    fileType: null,
    documentWordCount: plainText ? plainText.split(/\s+/).length : 0,
    documentCharacterCount: plainText.length,
  };
}

export function canonicalTelemetryMetadata(
  currentHtml = INITIAL_DOCUMENT_HTML,
): DocumentTelemetryMetadata {
  return telemetryMetadataForDocument(canonicalSession(), currentHtml);
}