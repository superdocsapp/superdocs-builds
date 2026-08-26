import assert from "node:assert/strict";
import test, { after } from "node:test";
import { randomUUID } from "node:crypto";

import express from "express";
import { clerkMiddleware } from "@clerk/express";
import { eq } from "drizzle-orm";

import { createUserDataRouter } from "../src/routes/userData.ts";
import {
  db,
  labConversations,
  labEditEvents,
  labPreferences,
  labVersions,
  labWorkspaces,
  pool,
} from "@workspace/db";

/**
 * Route tests for the user-scoped persistence API. They run against the
 * development database with random per-test user ids; every row created here
 * is removed in the `after` hook.
 */

const testUserIds = new Set();

function newTestUserId() {
  const id = `test-user-${randomUUID()}`;
  testUserIds.add(id);
  return id;
}

after(async () => {
  for (const userId of testUserIds) {
    await db.delete(labVersions).where(eq(labVersions.userId, userId));
    await db
      .delete(labConversations)
      .where(eq(labConversations.userId, userId));
    await db.delete(labEditEvents).where(eq(labEditEvents.userId, userId));
    await db.delete(labWorkspaces).where(eq(labWorkspaces.userId, userId));
    await db.delete(labPreferences).where(eq(labPreferences.userId, userId));
  }
  await pool.end();
});

/** Routes log through pino-http in the real app; tests stub it out. */
function quietLogger(req, _res, next) {
  req.log = { error() {}, warn() {}, info() {}, debug() {} };
  next();
}

function fakeAuthAs(userId) {
  return (_req, res, next) => {
    res.locals.labUserId = userId;
    next();
  };
}

/** App with a deterministic identity — exercises routes + storage. */
function buildAppAs(userId) {
  const app = express();
  app.use(express.json({ limit: "25mb" }));
  app.use(quietLogger);
  app.use("/api", createUserDataRouter(fakeAuthAs(userId)));
  return app;
}

/** App with the real Clerk auth chain — no session means 401. */
function buildUnauthenticatedApp() {
  const app = express();
  app.use(express.json());
  app.use(quietLogger);
  app.use(clerkMiddleware());
  app.use("/api", createUserDataRouter());
  return app;
}

async function withServer(app, run) {
  const server = app.listen(0, "127.0.0.1");
  await new Promise((resolve) => server.once("listening", resolve));
  const { port } = server.address();
  try {
    return await run(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

function workspacePayload(overrides = {}) {
  return {
    currentDocumentHtml: "<p>Hello from the test suite.</p>",
    documentSession: {
      id: "canonical-demo",
      sessionKey: "session-abc",
      sourceType: "canonical",
      persistence: "durable",
    },
    activeConversationId: "conv-1",
    versions: [
      { id: "v1", label: "Version 1" },
      { id: "v2", label: "Version 2" },
    ],
    conversations: [
      { id: "conv-1", title: "First conversation", messages: [] },
    ],
    editEvents: [{ id: "event-1", decision: "accepted" }],
    activity: [{ id: "act-1", action: "document.import" }],
    compareRuns: [],
    benchmarkRuns: [],
    latestResults: [],
    telemetry: [{ requestId: "req-1", engine: "diy" }],
    observabilitySettings: { enabled: true },
    ...overrides,
  };
}

async function putWorkspace(base, payload) {
  const response = await fetch(`${base}/api/user/workspace`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  assert.equal(response.status, 200);
  return response.json();
}

async function getWorkspace(base) {
  const response = await fetch(`${base}/api/user/workspace`);
  assert.equal(response.status, 200);
  return response.json();
}

test("every user-data route requires authentication", async () => {
  await withServer(buildUnauthenticatedApp(), async (base) => {
    const requests = [
      ["GET", "/api/user/workspace"],
      ["PUT", "/api/user/workspace"],
      ["DELETE", "/api/user/workspace"],
      ["GET", "/api/user/preferences"],
      ["PUT", "/api/user/preferences"],
    ];
    for (const [method, path] of requests) {
      const response = await fetch(`${base}${path}`, {
        method,
        headers: { "content-type": "application/json" },
        body: method === "PUT" ? "{}" : undefined,
      });
      assert.equal(response.status, 401, `${method} ${path}`);
      assert.deepEqual(await response.json(), {
        error: "Authentication required.",
      });
    }
  });
});

test("workspace round-trips through PUT and GET", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    assert.deepEqual(await getWorkspace(base), {
      workspace: null,
      updatedAt: null,
    });

    const payload = workspacePayload();
    const putBody = await putWorkspace(base, payload);
    assert.equal(putBody.ok, true);
    assert.ok(putBody.savedAt, "PUT reports when the save happened");

    const { workspace, updatedAt } = await getWorkspace(base);
    assert.ok(updatedAt);
    assert.equal(workspace.currentDocumentHtml, payload.currentDocumentHtml);
    assert.deepEqual(workspace.documentSession, payload.documentSession);
    assert.equal(workspace.activeConversationId, "conv-1");
    assert.deepEqual(workspace.versions, payload.versions);
    assert.deepEqual(workspace.conversations, payload.conversations);
    assert.deepEqual(workspace.editEvents, payload.editEvents);
    assert.deepEqual(workspace.activity, payload.activity);
    assert.deepEqual(workspace.telemetry, payload.telemetry);
    assert.deepEqual(workspace.observabilitySettings, { enabled: true });
  });
});

test("a second PUT replaces the previous snapshot", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    await putWorkspace(base, workspacePayload());
    await putWorkspace(
      base,
      workspacePayload({
        currentDocumentHtml: "<p>Updated.</p>",
        versions: [{ id: "v3", label: "Version 3" }],
        conversations: [],
        editEvents: [],
      }),
    );

    const { workspace } = await getWorkspace(base);
    assert.equal(workspace.currentDocumentHtml, "<p>Updated.</p>");
    assert.deepEqual(workspace.versions, [{ id: "v3", label: "Version 3" }]);
    assert.deepEqual(workspace.conversations, []);
    assert.deepEqual(workspace.editEvents, []);
  });
});

test("entity order is preserved and duplicate ids are dropped", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    await putWorkspace(
      base,
      workspacePayload({
        versions: [
          { id: "v1", label: "first" },
          { id: "v2", label: "second" },
          { id: "v1", label: "duplicate — must be ignored" },
          { id: "v3", label: "third" },
        ],
      }),
    );

    const { workspace } = await getWorkspace(base);
    assert.deepEqual(
      workspace.versions.map((version) => [version.id, version.label]),
      [
        ["v1", "first"],
        ["v2", "second"],
        ["v3", "third"],
      ],
    );
  });
});

test("workspaces are isolated per user", async () => {
  const alice = newTestUserId();
  const bob = newTestUserId();

  await withServer(buildAppAs(alice), async (base) => {
    await putWorkspace(
      base,
      workspacePayload({ currentDocumentHtml: "<p>Alice's doc.</p>" }),
    );
  });

  await withServer(buildAppAs(bob), async (base) => {
    const { workspace } = await getWorkspace(base);
    assert.equal(workspace, null, "Bob cannot see Alice's workspace");
    await putWorkspace(
      base,
      workspacePayload({ currentDocumentHtml: "<p>Bob's doc.</p>" }),
    );
  });

  await withServer(buildAppAs(alice), async (base) => {
    const { workspace } = await getWorkspace(base);
    assert.equal(
      workspace.currentDocumentHtml,
      "<p>Alice's doc.</p>",
      "Bob's write did not touch Alice's workspace",
    );
  });
});

test("DELETE clears the workspace but keeps preferences", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    await putWorkspace(base, workspacePayload());
    const putPrefs = await fetch(`${base}/api/user/preferences`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ developerMode: true }),
    });
    assert.equal(putPrefs.status, 200);

    const del = await fetch(`${base}/api/user/workspace`, {
      method: "DELETE",
    });
    assert.equal(del.status, 200);
    assert.deepEqual(await del.json(), { ok: true });

    const { workspace } = await getWorkspace(base);
    assert.equal(workspace, null);

    const prefs = await (
      await fetch(`${base}/api/user/preferences`)
    ).json();
    assert.deepEqual(prefs, { preferences: { developerMode: true } });
  });
});

test("rejects invalid workspace payloads without storing anything", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    const missingSession = await fetch(`${base}/api/user/workspace`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ currentDocumentHtml: "<p>No session.</p>" }),
    });
    assert.equal(missingSession.status, 400);
    assert.deepEqual(await missingSession.json(), {
      error: "Invalid workspace payload.",
    });

    const { workspace } = await getWorkspace(base);
    assert.equal(workspace, null);
  });
});

test("preferences round-trip and reject oversized payloads", async () => {
  const userId = newTestUserId();
  await withServer(buildAppAs(userId), async (base) => {
    const initial = await (
      await fetch(`${base}/api/user/preferences`)
    ).json();
    assert.deepEqual(initial, { preferences: null });

    const put = await fetch(`${base}/api/user/preferences`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ developerMode: true, sidebarCollapsed: false }),
    });
    assert.equal(put.status, 200);

    const { preferences } = await (
      await fetch(`${base}/api/user/preferences`)
    ).json();
    assert.deepEqual(preferences, {
      developerMode: true,
      sidebarCollapsed: false,
    });

    const oversized = await fetch(`${base}/api/user/preferences`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ blob: "x".repeat(25_000) }),
    });
    assert.equal(oversized.status, 400);
    assert.deepEqual(await oversized.json(), {
      error: "Invalid preferences payload.",
    });
  });
});
