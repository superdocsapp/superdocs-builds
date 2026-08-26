import type {
  EditInputEngine,
  EditInputScope,
} from '@workspace/api-client-react';
import { stripHtml } from './telemetry';

/**
 * Chat + edit history persistence.
 *
 * These records are presentation-layer history: they reference the EXISTING
 * version system (DocumentVersion ids) and the existing request machinery
 * (requestId) instead of duplicating either. Replaying or restoring from
 * history never issues a new AI request.
 */

export type ChatEngineChoice = EditInputEngine | 'both';

export type ChatDecision =
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'cancelled'
  | 'error';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  /** 'instruction' = user ask, 'proposal' = engine produced a suggestion,
   *  'status' = plain assistant note, 'error' = failed request. */
  kind: 'instruction' | 'proposal' | 'status' | 'error';
  text: string;
  timestamp: string;
  engine?: ChatEngineChoice;
  engineLabel?: string;
  scope?: EditInputScope;
  requestId?: string;
  decision?: ChatDecision;
  versionAfterId?: string | null;
  /** Display number of the version created by accepting this proposal. */
  versionAfterNumber?: number | null;
};

export type Conversation = {
  id: string;
  documentId: string;
  documentTitle: string;
  /**
   * Identity of the document SESSION the chat belongs to. Distinct from
   * documentId because repeated canonical sessions share the id
   * 'canonical-demo' (a telemetry-comparability requirement); the sessionKey
   * keeps chats from an earlier canonical session read-only instead of
   * attaching to the current one. Absent on legacy records, which are then
   * always treated as belonging to an earlier session.
   */
  sessionKey?: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

export type EditEventDecision = 'accepted' | 'rejected';

export type EditEvent = {
  id: string;
  timestamp: string;
  documentId: string;
  /** See Conversation.sessionKey — scopes the event to a document session. */
  sessionKey?: string;
  documentTitle: string;
  conversationId: string | null;
  requestId: string | null;
  engine: EditInputEngine;
  engineLabel: string;
  instruction: string;
  scope: EditInputScope;
  decision: EditEventDecision;
  /** Version that was current when the proposal was reviewed. */
  versionBeforeId: string | null;
  versionBeforeNumber: number | null;
  /** Version created by accepting; null when rejected. */
  versionAfterId: string | null;
  versionAfterNumber: number | null;
  beforePreview: string;
  afterPreview: string;
};

export function htmlToPreview(html: string, maxChars = 220): string {
  const text = stripHtml(html);
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars).trimEnd()}…`;
}

export function titleFromInstruction(instruction: string, maxChars = 64): string {
  const cleaned = instruction.replace(/\s+/g, ' ').trim();
  if (!cleaned) return 'New conversation';
  if (cleaned.length <= maxChars) return cleaned;
  return `${cleaned.slice(0, maxChars).trimEnd()}…`;
}

export function appendMessageToConversations(
  conversations: Conversation[],
  conversationId: string,
  message: ChatMessage,
): Conversation[] {
  return conversations.map((conversation) =>
    conversation.id === conversationId
      ? {
          ...conversation,
          updatedAt: message.timestamp,
          messages: [...conversation.messages, message],
        }
      : conversation,
  );
}

export function updateMessageInConversations(
  conversations: Conversation[],
  conversationId: string,
  messageId: string,
  updates: Partial<ChatMessage>,
): Conversation[] {
  return conversations.map((conversation) =>
    conversation.id === conversationId
      ? {
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === messageId ? { ...message, ...updates } : message,
          ),
        }
      : conversation,
  );
}

const CHAT_DECISIONS: readonly ChatDecision[] = [
  'pending',
  'accepted',
  'rejected',
  'cancelled',
  'error',
];

function adaptMessage(raw: unknown): ChatMessage | null {
  if (!raw || typeof raw !== 'object') return null;
  const message = raw as Record<string, unknown>;
  if (typeof message.id !== 'string' || typeof message.timestamp !== 'string') {
    return null;
  }
  if (message.role !== 'user' && message.role !== 'assistant') return null;
  const kind =
    message.kind === 'instruction' ||
    message.kind === 'proposal' ||
    message.kind === 'status' ||
    message.kind === 'error'
      ? message.kind
      : message.role === 'user'
        ? 'instruction'
        : 'status';
  return {
    ...(message as Partial<ChatMessage>),
    id: message.id,
    role: message.role,
    kind,
    text: typeof message.text === 'string' ? message.text : '',
    timestamp: message.timestamp,
    decision: CHAT_DECISIONS.includes(message.decision as ChatDecision)
      ? (message.decision as ChatDecision)
      : undefined,
  };
}

function adaptConversation(raw: unknown): Conversation | null {
  if (!raw || typeof raw !== 'object') return null;
  const conversation = raw as Record<string, unknown>;
  if (
    typeof conversation.id !== 'string' ||
    !Array.isArray(conversation.messages)
  ) {
    return null;
  }
  const createdAt =
    typeof conversation.createdAt === 'string'
      ? conversation.createdAt
      : new Date(0).toISOString();
  return {
    id: conversation.id,
    documentId:
      typeof conversation.documentId === 'string' ? conversation.documentId : '',
    documentTitle:
      typeof conversation.documentTitle === 'string'
        ? conversation.documentTitle
        : 'Untitled document',
    sessionKey:
      typeof conversation.sessionKey === 'string'
        ? conversation.sessionKey
        : undefined,
    title:
      typeof conversation.title === 'string' && conversation.title.trim()
        ? conversation.title
        : 'Conversation',
    createdAt,
    updatedAt:
      typeof conversation.updatedAt === 'string'
        ? conversation.updatedAt
        : createdAt,
    messages: conversation.messages
      .map(adaptMessage)
      .filter((message): message is ChatMessage => message !== null),
  };
}

function adaptEditEvent(raw: unknown): EditEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const event = raw as Record<string, unknown>;
  if (typeof event.id !== 'string' || typeof event.timestamp !== 'string') {
    return null;
  }
  if (event.decision !== 'accepted' && event.decision !== 'rejected') {
    return null;
  }
  const engine =
    event.engine === 'diy' || event.engine === 'superdocs'
      ? event.engine
      : 'diy';
  return {
    id: event.id,
    timestamp: event.timestamp,
    documentId: typeof event.documentId === 'string' ? event.documentId : '',
    sessionKey:
      typeof event.sessionKey === 'string' ? event.sessionKey : undefined,
    documentTitle:
      typeof event.documentTitle === 'string'
        ? event.documentTitle
        : 'Untitled document',
    conversationId:
      typeof event.conversationId === 'string' ? event.conversationId : null,
    requestId: typeof event.requestId === 'string' ? event.requestId : null,
    engine,
    engineLabel:
      typeof event.engineLabel === 'string'
        ? event.engineLabel
        : engine === 'superdocs'
          ? 'SuperDocs Hosted'
          : 'DIY Toolkit',
    instruction:
      typeof event.instruction === 'string' ? event.instruction : '',
    scope:
      event.scope === 'selection' || event.scope === 'document'
        ? event.scope
        : 'document',
    decision: event.decision,
    versionBeforeId:
      typeof event.versionBeforeId === 'string' ? event.versionBeforeId : null,
    versionBeforeNumber:
      typeof event.versionBeforeNumber === 'number'
        ? event.versionBeforeNumber
        : null,
    versionAfterId:
      typeof event.versionAfterId === 'string' ? event.versionAfterId : null,
    versionAfterNumber:
      typeof event.versionAfterNumber === 'number'
        ? event.versionAfterNumber
        : null,
    beforePreview:
      typeof event.beforePreview === 'string' ? event.beforePreview : '',
    afterPreview:
      typeof event.afterPreview === 'string' ? event.afterPreview : '',
  };
}

/**
 * Adapt a possibly-older persisted payload. Older snapshots (before chat
 * history existed) simply lack these arrays; they must load untouched with
 * empty history rather than being invalidated. Corrupted-but-JSON-valid
 * records (e.g. null messages, missing required fields) are dropped or
 * normalized record-by-record so one bad entry never breaks the app.
 */
export function adaptPersistedHistory(parsed: unknown): {
  conversations: Conversation[];
  editEvents: EditEvent[];
  activeConversationId: string | null;
} {
  const raw = (parsed ?? {}) as Record<string, unknown>;
  const conversations = Array.isArray(raw.conversations)
    ? raw.conversations
        .map(adaptConversation)
        .filter((conversation): conversation is Conversation => conversation !== null)
    : [];
  const editEvents = Array.isArray(raw.editEvents)
    ? raw.editEvents
        .map(adaptEditEvent)
        .filter((event): event is EditEvent => event !== null)
    : [];
  const activeConversationId =
    typeof raw.activeConversationId === 'string' &&
    conversations.some((conversation) => conversation.id === raw.activeConversationId)
      ? raw.activeConversationId
      : null;
  return { conversations, editEvents, activeConversationId };
}

/**
 * Split edit events into those belonging to the CURRENT document session and
 * those from earlier sessions. Scoping is by sessionKey — never by document
 * id, because repeated canonical sessions share one document id. Events
 * without a sessionKey predate session identity and are always treated as
 * earlier-session (read-only) history.
 */
export function partitionEditEventsBySession(
  editEvents: EditEvent[],
  currentSessionKey: string | undefined,
): { currentSession: EditEvent[]; earlierSessions: EditEvent[] } {
  const currentSession: EditEvent[] = [];
  const earlierSessions: EditEvent[] = [];
  for (const event of editEvents) {
    if (currentSessionKey != null && event.sessionKey === currentSessionKey) {
      currentSession.push(event);
    } else {
      earlierSessions.push(event);
    }
  }
  return { currentSession, earlierSessions };
}

export type DiffSegment = {
  type: 'same' | 'added' | 'removed';
  text: string;
};

const DIFF_INPUT_LIMIT_CHARS = 6_000;

/**
 * Word-level LCS diff for the review card's before/after highlight. Purely
 * presentational; oversized inputs fall back to un-highlighted segments so the
 * UI stays responsive.
 */
export function diffWords(before: string, after: string): DiffSegment[] {
  if (
    before.length > DIFF_INPUT_LIMIT_CHARS ||
    after.length > DIFF_INPUT_LIMIT_CHARS
  ) {
    const segments: DiffSegment[] = [];
    if (before) segments.push({ type: 'removed', text: before });
    if (after) segments.push({ type: 'added', text: after });
    return segments;
  }
  const beforeWords = before.split(/(\s+)/).filter((part) => part !== '');
  const afterWords = after.split(/(\s+)/).filter((part) => part !== '');
  const rows = beforeWords.length;
  const cols = afterWords.length;
  // LCS table (rows+1) x (cols+1)
  const table: number[] = new Array((rows + 1) * (cols + 1)).fill(0);
  const at = (row: number, col: number) => row * (cols + 1) + col;
  for (let row = rows - 1; row >= 0; row -= 1) {
    for (let col = cols - 1; col >= 0; col -= 1) {
      table[at(row, col)] =
        beforeWords[row] === afterWords[col]
          ? table[at(row + 1, col + 1)] + 1
          : Math.max(table[at(row + 1, col)], table[at(row, col + 1)]);
    }
  }
  const segments: DiffSegment[] = [];
  const push = (type: DiffSegment['type'], text: string) => {
    if (!text) return;
    const last = segments[segments.length - 1];
    if (last && last.type === type) {
      last.text += text;
    } else {
      segments.push({ type, text });
    }
  };
  let row = 0;
  let col = 0;
  while (row < rows && col < cols) {
    if (beforeWords[row] === afterWords[col]) {
      push('same', beforeWords[row]);
      row += 1;
      col += 1;
    } else if (table[at(row + 1, col)] >= table[at(row, col + 1)]) {
      push('removed', beforeWords[row]);
      row += 1;
    } else {
      push('added', afterWords[col]);
      col += 1;
    }
  }
  while (row < rows) {
    push('removed', beforeWords[row]);
    row += 1;
  }
  while (col < cols) {
    push('added', afterWords[col]);
    col += 1;
  }
  return segments;
}

export function formatRelativeTime(iso: string, now = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffMs = now.getTime() - then;
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}
