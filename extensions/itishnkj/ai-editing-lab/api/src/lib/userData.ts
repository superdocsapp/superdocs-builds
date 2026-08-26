import {
  db,
  labConversations,
  labEditEvents,
  labPreferences,
  labVersions,
  labWorkspaces,
} from "@workspace/db";
import { asc, eq } from "drizzle-orm";
import { z } from "zod";

/**
 * Server-side storage for authenticated AI Editing Lab workspaces.
 *
 * The client owns the canonical workspace shape (it mirrors the guest
 * localStorage snapshot, adapted on load by the client). The server treats it
 * as a bounded, loosely-validated document: entity arrays are decomposed into
 * per-user rows, everything else lives in the workspace row's `lab_state`
 * JSON. All reads and writes are scoped by the verified Clerk user id —
 * never by anything from the request body.
 */

const MAX_ID_LENGTH = 200;

/** Entities that get their own rows must carry a stable string id. */
const entityWithId = z
  .object({ id: z.string().min(1).max(MAX_ID_LENGTH) })
  .passthrough();

export const workspacePayloadSchema = z
  .object({
    currentDocumentHtml: z.string().max(12_000_000),
    documentSession: z
      .object({ id: z.string().min(1).max(MAX_ID_LENGTH) })
      .passthrough(),
    activeConversationId: z
      .string()
      .max(MAX_ID_LENGTH)
      .nullish()
      .default(null),
    versions: z.array(entityWithId).max(500).optional().default([]),
    conversations: z.array(entityWithId).max(1_000).optional().default([]),
    editEvents: z.array(entityWithId).max(10_000).optional().default([]),
    activity: z.array(z.unknown()).max(10_000).optional().default([]),
    compareRuns: z.array(z.unknown()).max(1_000).optional().default([]),
    benchmarkRuns: z.array(z.unknown()).max(1_000).optional().default([]),
    latestResults: z.array(z.unknown()).max(100).optional().default([]),
    telemetry: z.array(z.unknown()).max(10_000).optional().default([]),
    observabilitySettings: z.record(z.unknown()).optional().default({}),
  })
  .passthrough();

export type WorkspacePayload = z.infer<typeof workspacePayloadSchema>;

export const preferencesPayloadSchema = z
  .record(z.unknown())
  .refine((value) => JSON.stringify(value).length <= 20_000, {
    message: "Preferences payload is too large.",
  });

export type PreferencesPayload = z.infer<typeof preferencesPayloadSchema>;

type EntityRecord = { id: string } & Record<string, unknown>;

/** Keeps the first occurrence of each id, preserving array order. */
function dedupeById<T extends EntityRecord>(items: T[]): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    result.push(item);
  }
  return result;
}

export interface StoredWorkspace {
  workspace: Record<string, unknown>;
  updatedAt: string;
}

export async function readWorkspace(
  userId: string,
): Promise<StoredWorkspace | null> {
  const [row] = await db
    .select()
    .from(labWorkspaces)
    .where(eq(labWorkspaces.userId, userId));
  if (!row) return null;

  const [versionRows, conversationRows, editEventRows] = await Promise.all([
    db
      .select()
      .from(labVersions)
      .where(eq(labVersions.userId, userId))
      .orderBy(asc(labVersions.position)),
    db
      .select()
      .from(labConversations)
      .where(eq(labConversations.userId, userId))
      .orderBy(asc(labConversations.position)),
    db
      .select()
      .from(labEditEvents)
      .where(eq(labEditEvents.userId, userId))
      .orderBy(asc(labEditEvents.position)),
  ]);

  const labState = (row.labState ?? {}) as Record<string, unknown>;

  return {
    workspace: {
      ...labState,
      currentDocumentHtml: row.currentDocumentHtml,
      documentSession: row.documentSession,
      activeConversationId: row.activeConversationId,
      versions: versionRows.map((r) => r.payload),
      conversations: conversationRows.map((r) => r.payload),
      editEvents: editEventRows.map((r) => r.payload),
    },
    updatedAt: row.updatedAt.toISOString(),
  };
}

export async function writeWorkspace(
  userId: string,
  payload: WorkspacePayload,
): Promise<Date> {
  const {
    currentDocumentHtml,
    documentSession,
    activeConversationId,
    versions,
    conversations,
    editEvents,
    ...labState
  } = payload;

  const dedupedVersions = dedupeById(versions as EntityRecord[]);
  const dedupedConversations = dedupeById(conversations as EntityRecord[]);
  const dedupedEditEvents = dedupeById(editEvents as EntityRecord[]);
  const now = new Date();

  await db.transaction(async (tx) => {
    await tx
      .insert(labWorkspaces)
      .values({
        userId,
        documentSession,
        currentDocumentHtml,
        activeConversationId: activeConversationId ?? null,
        labState,
        updatedAt: now,
      })
      .onConflictDoUpdate({
        target: labWorkspaces.userId,
        set: {
          documentSession,
          currentDocumentHtml,
          activeConversationId: activeConversationId ?? null,
          labState,
          updatedAt: now,
        },
      });

    await tx.delete(labVersions).where(eq(labVersions.userId, userId));
    if (dedupedVersions.length > 0) {
      await tx.insert(labVersions).values(
        dedupedVersions.map((item, position) => ({
          userId,
          id: item.id,
          position,
          payload: item,
        })),
      );
    }

    await tx
      .delete(labConversations)
      .where(eq(labConversations.userId, userId));
    if (dedupedConversations.length > 0) {
      await tx.insert(labConversations).values(
        dedupedConversations.map((item, position) => ({
          userId,
          id: item.id,
          position,
          payload: item,
        })),
      );
    }

    await tx.delete(labEditEvents).where(eq(labEditEvents.userId, userId));
    if (dedupedEditEvents.length > 0) {
      await tx.insert(labEditEvents).values(
        dedupedEditEvents.map((item, position) => ({
          userId,
          id: item.id,
          position,
          payload: item,
        })),
      );
    }
  });

  return now;
}

/** Removes the stored workspace (used for session-only documents). Preferences are kept. */
export async function deleteWorkspace(userId: string): Promise<void> {
  await db.transaction(async (tx) => {
    await tx.delete(labVersions).where(eq(labVersions.userId, userId));
    await tx
      .delete(labConversations)
      .where(eq(labConversations.userId, userId));
    await tx.delete(labEditEvents).where(eq(labEditEvents.userId, userId));
    await tx.delete(labWorkspaces).where(eq(labWorkspaces.userId, userId));
  });
}

export async function readPreferences(
  userId: string,
): Promise<Record<string, unknown> | null> {
  const [row] = await db
    .select()
    .from(labPreferences)
    .where(eq(labPreferences.userId, userId));
  if (!row) return null;
  return (row.payload ?? {}) as Record<string, unknown>;
}

export async function writePreferences(
  userId: string,
  payload: PreferencesPayload,
): Promise<void> {
  await db
    .insert(labPreferences)
    .values({ userId, payload, updatedAt: new Date() })
    .onConflictDoUpdate({
      target: labPreferences.userId,
      set: { payload, updatedAt: new Date() },
    });
}
