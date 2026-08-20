import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createApp } from "../server/app.js";
import { computeRegions } from "../server/lib/diff.js";

const FAKE_BLOCKS = [
  { nodeId: "b1", text: "Senior Engineer at Acme, led the platform team." },
  { nodeId: "b2", text: "Skills: Python, SQL, Kubernetes." },
];

class FakeSession {
  constructor() {
    this.calls = [];
  }
  async open(filePath) {
    this.calls.push(["open", filePath]);
  }
  async listBlocks() {
    this.calls.push(["listBlocks"]);
    return FAKE_BLOCKS;
  }
  async replaceBlockTracked(block, text) {
    // Mirror the real session: one replace call per word-level region.
    for (const r of computeRegions(block.text, text)) {
      this.calls.push(["replace", block.nodeId, r.newText]);
    }
  }
  async save() {
    this.calls.push(["save"]);
  }
  async close() {
    this.calls.push(["close"]);
  }
}

function makeForm(docx = Buffer.from("fake-docx-bytes"), jd = "A job description.") {
  const form = new FormData();
  form.append(
    "resume",
    new Blob([new Uint8Array(docx)], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
    "resume.docx"
  );
  form.append("jobDescription", jd);
  return form;
}

async function startApp({ llm }) {
  const sessions = [];
  const app = createApp({
    sessionFactory: () => {
      const s = new FakeSession();
      sessions.push(s);
      return s;
    },
    llm,
  });
  const server = app.listen(0);
  await new Promise((resolve) => server.once("listening", resolve));
  return {
    base: `http://127.0.0.1:${server.address().port}`,
    sessions,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

const HAPPY_LLM = async () => [
  { nodeId: "b1", revisedText: "Staff Engineer at Acme, led the platform org." },
];

let app;

before(async () => {
  app = await startApp({ llm: HAPPY_LLM });
});

after(() => app.close());

test("400 when neither resume nor job description is sent", async () => {
  const res = await fetch(`${app.base}/api/tailor`, { method: "POST", body: new FormData() });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.error, /Upload a \.docx resume/i);
});

test("400 when the job description is missing", async () => {
  const form = makeForm();
  form.delete("jobDescription");
  const res = await fetch(`${app.base}/api/tailor`, { method: "POST", body: form });
  assert.equal(res.status, 400);
});

test("happy path: tracked replace + save + close, revision metadata", async () => {
  const res = await fetch(`${app.base}/api/tailor`, { method: "POST", body: makeForm() });
  assert.equal(res.status, 200);

  const body = await res.json();
  assert.ok(Buffer.from(body.docx, "base64").length > 0, "docx base64 payload present");

  const rev = body.revisions[0];
  assert.equal(rev.nodeId, "b1");
  assert.equal(rev.revisedText, "Staff Engineer at Acme, led the platform org.");
  assert.equal(rev.original, FAKE_BLOCKS[0].text);
  assert.equal(rev.line, 1);
  assert.equal(rev.page, 1);
  assert.equal(rev.lengthFlag, false);
});

test("session lifecycle: open -> listBlocks -> replace per region -> save -> close", async () => {
  const res = await fetch(`${app.base}/api/tailor`, { method: "POST", body: makeForm() });
  assert.equal(res.status, 200);

  const session = app.sessions[app.sessions.length - 1];
  const kinds = session.calls.map((c) => c[0]);
  assert.deepEqual(kinds, ["open", "listBlocks", "replace", "replace", "save", "close"]);
  // Word-level regions: "Senior" -> "Staff" and "team." -> "org.".
  assert.equal(session.calls[2][1], "b1");
  assert.equal(session.calls[2][2], "Staff ");
  assert.equal(session.calls[3][1], "b1");
  assert.equal(session.calls[3][2], "org.");
});

test("revision for an unknown nodeId is skipped, no replace, save still runs", async () => {
  const unknown = await startApp({
    llm: async () => [{ nodeId: "b9", revisedText: "does not exist" }],
  });
  const res = await fetch(`${unknown.base}/api/tailor`, { method: "POST", body: makeForm() });
  assert.equal(res.status, 200);

  const body = await res.json();
  assert.equal(body.revisions.length, 0);

  const session = unknown.sessions[unknown.sessions.length - 1];
  const kinds = session.calls.map((c) => c[0]);
  assert.deepEqual(kinds, ["open", "listBlocks", "save", "close"]);
  await unknown.close();
});

test("LLM failure returns 500 and the session is still closed", async () => {
  const broken = await startApp({
    llm: async () => {
      throw new Error("model exploded");
    },
  });
  const res = await fetch(`${broken.base}/api/tailor`, { method: "POST", body: makeForm() });
  assert.equal(res.status, 500);

  const session = broken.sessions[broken.sessions.length - 1];
  const kinds = session.calls.map((c) => c[0]);
  assert.deepEqual(kinds, ["open", "listBlocks", "close"]);
  await broken.close();
});