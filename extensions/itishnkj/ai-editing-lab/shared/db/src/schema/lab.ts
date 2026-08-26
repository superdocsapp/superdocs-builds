import {
  index,
  integer,
  jsonb,
  pgTable,
  primaryKey,
  text,
  timestamp,
} from "drizzle-orm/pg-core";

/**
 * Per-user AI Editing Lab workspace state.
 *
 * The client owns the canonical shape of the workspace (it mirrors the guest
 * localStorage snapshot). The server decomposes the snapshot into a workspace
 * row plus per-entity rows so user data stays isolated, queryable, and
 * replaceable in one transaction.
 */
export const labWorkspaces = pgTable("lab_workspaces", {
  /** Clerk user id — the only identity key we store. */
  userId: text("user_id").primaryKey(),
  /** Document session metadata (id, title, source, import details…). */
  documentSession: jsonb("document_session").notNull(),
  /** Current document content as sanitized HTML. */
  currentDocumentHtml: text("current_document_html").notNull(),
  activeConversationId: text("active_conversation_id"),
  /**
   * Remaining lab state persisted as one JSON document: activity log,
   * compare runs, benchmark runs, latest results, telemetry records, and
   * observability settings.
   */
  labState: jsonb("lab_state").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const labVersions = pgTable(
  "lab_versions",
  {
    userId: text("user_id").notNull(),
    id: text("id").notNull(),
    /** Preserves client-side array order. */
    position: integer("position").notNull(),
    payload: jsonb("payload").notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.userId, table.id] }),
    index("lab_versions_user_idx").on(table.userId),
  ],
);

export const labConversations = pgTable(
  "lab_conversations",
  {
    userId: text("user_id").notNull(),
    id: text("id").notNull(),
    position: integer("position").notNull(),
    payload: jsonb("payload").notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.userId, table.id] }),
    index("lab_conversations_user_idx").on(table.userId),
  ],
);

export const labEditEvents = pgTable(
  "lab_edit_events",
  {
    userId: text("user_id").notNull(),
    id: text("id").notNull(),
    position: integer("position").notNull(),
    payload: jsonb("payload").notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.userId, table.id] }),
    index("lab_edit_events_user_idx").on(table.userId),
  ],
);

export const labPreferences = pgTable("lab_preferences", {
  userId: text("user_id").primaryKey(),
  payload: jsonb("payload").notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export type LabWorkspaceRow = typeof labWorkspaces.$inferSelect;
export type LabPreferencesRow = typeof labPreferences.$inferSelect;
