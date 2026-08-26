import assert from 'node:assert/strict';
import test from 'node:test';
import {
  adaptPersistedHistory,
  appendMessageToConversations,
  updateMessageInConversations,
  diffWords,
  htmlToPreview,
  titleFromInstruction,
  formatRelativeTime,
  partitionEditEventsBySession,
  type ChatMessage,
  type Conversation,
  type EditEvent,
} from '../src/lib/history.ts';

function editEventFixture(overrides: Partial<EditEvent> = {}): EditEvent {
  return {
    id: 'event-1',
    timestamp: '2026-08-20T10:00:00.000Z',
    documentId: 'canonical-demo',
    documentTitle: 'Quarterly Client Update',
    conversationId: null,
    requestId: null,
    engine: 'diy',
    engineLabel: 'DIY Toolkit',
    instruction: 'Tighten the opening paragraph',
    scope: 'document',
    decision: 'accepted',
    versionBeforeId: null,
    versionBeforeNumber: null,
    versionAfterId: null,
    versionAfterNumber: null,
    beforePreview: '',
    afterPreview: '',
    ...overrides,
  };
}

function conversationFixture(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'conversation-1',
    documentId: 'canonical-demo',
    documentTitle: 'Quarterly Client Update',
    title: 'Make the summary tighter',
    createdAt: '2026-08-20T10:00:00.000Z',
    updatedAt: '2026-08-20T10:00:00.000Z',
    messages: [],
    ...overrides,
  };
}

test('pre-redesign persisted state loads with empty history instead of being invalidated', () => {
  const legacyState = {
    currentDocumentHtml: '<p>Existing document</p>',
    versions: [{ id: 'v1', html: '<p>Existing document</p>' }],
    telemetry: [],
  };
  const adapted = adaptPersistedHistory(legacyState);
  assert.deepEqual(adapted.conversations, []);
  assert.deepEqual(adapted.editEvents, []);
  assert.equal(adapted.activeConversationId, null);
});

test('valid persisted conversations and edit events survive adaptation', () => {
  const adapted = adaptPersistedHistory({
    conversations: [conversationFixture()],
    editEvents: [
      {
        id: 'event-1',
        timestamp: '2026-08-20T10:05:00.000Z',
        documentId: 'canonical-demo',
        decision: 'accepted',
      },
    ],
    activeConversationId: 'conversation-1',
  });
  assert.equal(adapted.conversations.length, 1);
  assert.equal(adapted.editEvents.length, 1);
  assert.equal(adapted.activeConversationId, 'conversation-1');
});

test('malformed history entries and dangling active ids are dropped safely', () => {
  const adapted = adaptPersistedHistory({
    conversations: [conversationFixture(), null, { id: 42 }, { id: 'x' }],
    editEvents: [
      null,
      7,
      // No decision → cannot render in any timeline; dropped.
      { id: 'undecided', timestamp: '2026-08-20T10:00:00.000Z' },
      {
        id: 'ok',
        timestamp: '2026-08-20T10:00:00.000Z',
        decision: 'rejected',
      },
    ],
    activeConversationId: 'missing-conversation',
  });
  assert.equal(adapted.conversations.length, 1);
  assert.equal(adapted.editEvents.length, 1);
  assert.equal(adapted.activeConversationId, null);
});

test('appending a message updates only the target conversation and its timestamp', () => {
  const conversations = [
    conversationFixture(),
    conversationFixture({ id: 'conversation-2', title: 'Second chat' }),
  ];
  const message: ChatMessage = {
    id: 'message-1',
    role: 'user',
    kind: 'instruction',
    text: 'Fix grammar',
    timestamp: '2026-08-20T11:00:00.000Z',
  };
  const next = appendMessageToConversations(conversations, 'conversation-2', message);
  assert.equal(next[0].messages.length, 0);
  assert.equal(next[1].messages.length, 1);
  assert.equal(next[1].updatedAt, '2026-08-20T11:00:00.000Z');
  // Source array is not mutated.
  assert.equal(conversations[1].messages.length, 0);
});

test('updating a message merges fields without touching siblings', () => {
  const base = conversationFixture({
    messages: [
      {
        id: 'message-1',
        role: 'assistant',
        kind: 'proposal',
        text: 'Suggested edit ready',
        timestamp: '2026-08-20T11:00:00.000Z',
        decision: 'pending',
      },
      {
        id: 'message-2',
        role: 'assistant',
        kind: 'status',
        text: 'Another note',
        timestamp: '2026-08-20T11:01:00.000Z',
      },
    ],
  });
  const next = updateMessageInConversations([base], 'conversation-1', 'message-1', {
    decision: 'accepted',
    versionAfterNumber: 4,
  });
  assert.equal(next[0].messages[0].decision, 'accepted');
  assert.equal(next[0].messages[0].versionAfterNumber, 4);
  assert.equal(next[0].messages[0].text, 'Suggested edit ready');
  assert.equal(next[0].messages[1].decision, undefined);
});

test('html previews strip markup and truncate long content', () => {
  const preview = htmlToPreview('<p>The <strong>quick</strong> brown fox</p>');
  assert.equal(preview, 'The quick brown fox');
  const long = htmlToPreview(`<p>${'word '.repeat(100)}</p>`, 40);
  assert.ok(long.length <= 41);
  assert.ok(long.endsWith('…'));
});

test('conversation titles come from the first instruction, trimmed and truncated', () => {
  assert.equal(titleFromInstruction('  Fix   the grammar  '), 'Fix the grammar');
  assert.equal(titleFromInstruction(''), 'New conversation');
  const long = titleFromInstruction('a'.repeat(100));
  assert.ok(long.length <= 65);
  assert.ok(long.endsWith('…'));
});

test('corrupted nested history records are dropped or normalized, never crash', () => {
  const adapted = adaptPersistedHistory({
    conversations: [
      null,
      42,
      { id: 'missing-messages' },
      {
        id: 'messy',
        messages: [
          null,
          'not-an-object',
          { id: 12, role: 'user', timestamp: '2026-08-20T10:00:00.000Z' },
          { id: 'no-role', role: 'system', timestamp: '2026-08-20T10:00:00.000Z' },
          {
            id: 'ok-1',
            role: 'user',
            timestamp: '2026-08-20T10:00:00.000Z',
            // kind/text missing → normalized, decision invalid → dropped
            decision: 'bogus',
          },
          {
            id: 'ok-2',
            role: 'assistant',
            kind: 'proposal',
            text: 'A suggestion',
            timestamp: '2026-08-20T10:01:00.000Z',
            decision: 'accepted',
          },
        ],
        // title/documentTitle/timestamps missing → normalized with fallbacks
      },
    ],
    editEvents: [
      null,
      { id: 'no-timestamp' },
      { id: 'bad-decision', timestamp: '2026-08-20T10:00:00.000Z', decision: 'maybe' },
      {
        id: 'event-ok',
        timestamp: '2026-08-20T10:02:00.000Z',
        decision: 'accepted',
        engine: 'superdocs',
        // remaining fields missing → normalized
      },
    ],
    activeConversationId: 'messy',
  });

  assert.equal(adapted.conversations.length, 1);
  const conversation = adapted.conversations[0];
  assert.equal(conversation.id, 'messy');
  assert.equal(conversation.title, 'Conversation');
  assert.equal(conversation.documentTitle, 'Untitled document');
  assert.equal(typeof conversation.createdAt, 'string');
  assert.equal(conversation.updatedAt, conversation.createdAt);
  assert.equal(conversation.messages.length, 2);
  assert.equal(conversation.messages[0].id, 'ok-1');
  assert.equal(conversation.messages[0].kind, 'instruction');
  assert.equal(conversation.messages[0].text, '');
  assert.equal(conversation.messages[0].decision, undefined);
  assert.equal(conversation.messages[1].decision, 'accepted');

  assert.equal(adapted.editEvents.length, 1);
  const event = adapted.editEvents[0];
  assert.equal(event.id, 'event-ok');
  assert.equal(event.engine, 'superdocs');
  assert.equal(event.engineLabel, 'SuperDocs Hosted');
  assert.equal(event.scope, 'document');
  assert.equal(event.instruction, '');
  assert.equal(event.versionAfterId, null);

  // The surviving conversation is still resolvable as active.
  assert.equal(adapted.activeConversationId, 'messy');
});

test('session keys survive adaptation and legacy records stay keyless', () => {
  const adapted = adaptPersistedHistory({
    conversations: [
      conversationFixture({ id: 'with-key', sessionKey: 'session-a' }),
      conversationFixture({ id: 'legacy' }),
    ],
    editEvents: [],
    activeConversationId: null,
  });
  assert.equal(adapted.conversations[0].sessionKey, 'session-a');
  assert.equal(adapted.conversations[1].sessionKey, undefined);
});

test('earlier canonical-session decisions stay visible as earlier-session history', () => {
  // Two canonical sessions share documentId 'canonical-demo'; scoping must
  // rely on sessionKey so the first session's accepted AND rejected events
  // survive as read-only earlier-session history instead of vanishing.
  const events = [
    editEventFixture({ id: 'a-accepted', sessionKey: 'session-a' }),
    editEventFixture({
      id: 'a-rejected',
      sessionKey: 'session-a',
      decision: 'rejected',
    }),
    editEventFixture({ id: 'b-accepted', sessionKey: 'session-b' }),
    editEventFixture({ id: 'legacy-keyless' }),
  ];
  const { currentSession, earlierSessions } = partitionEditEventsBySession(
    events,
    'session-b',
  );
  assert.deepEqual(
    currentSession.map((event) => event.id),
    ['b-accepted'],
  );
  assert.deepEqual(
    earlierSessions.map((event) => event.id).sort(),
    ['a-accepted', 'a-rejected', 'legacy-keyless'],
  );
});

test('without a current session key every edit event is earlier-session history', () => {
  const { currentSession, earlierSessions } = partitionEditEventsBySession(
    [editEventFixture({ id: 'x', sessionKey: 'session-a' })],
    undefined,
  );
  assert.equal(currentSession.length, 0);
  assert.equal(earlierSessions.length, 1);
});

test('word diff marks additions and removals and keeps unchanged text', () => {
  const segments = diffWords('The quick brown fox', 'The slow brown fox');
  const removed = segments.filter((segment) => segment.type === 'removed');
  const added = segments.filter((segment) => segment.type === 'added');
  const same = segments.filter((segment) => segment.type === 'same');
  assert.equal(removed.map((segment) => segment.text).join(''), 'quick');
  assert.equal(added.map((segment) => segment.text).join(''), 'slow');
  assert.ok(same.some((segment) => segment.text.includes('brown fox')));
});

test('word diff on identical text yields a single unchanged segment', () => {
  const segments = diffWords('Same text here', 'Same text here');
  assert.deepEqual(segments, [{ type: 'same', text: 'Same text here' }]);
});

test('oversized diff input falls back to whole-block segments', () => {
  const big = 'x'.repeat(7_000);
  const segments = diffWords(big, `${big}y`);
  assert.equal(segments.length, 2);
  assert.equal(segments[0].type, 'removed');
  assert.equal(segments[1].type, 'added');
});

test('relative time formatting stays plain-language', () => {
  const now = new Date('2026-08-23T12:00:00.000Z');
  assert.equal(formatRelativeTime('2026-08-23T11:59:40.000Z', now), 'Just now');
  assert.equal(formatRelativeTime('2026-08-23T11:30:00.000Z', now), '30m ago');
  assert.equal(formatRelativeTime('2026-08-23T06:00:00.000Z', now), '6h ago');
  assert.equal(formatRelativeTime('2026-08-22T10:00:00.000Z', now), 'Yesterday');
});
