import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createApp } from "../src/app.js";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

test("accepts Twilio fields, traces the message, and sends one result link", async () => {
  const calls = [];
  const sent = [];
  const logs = [];
  const app = createApp({
    config: {
      publicBaseUrl: "https://bridge.example.org",
      twilioAuthToken: "test",
      twilioPhoneNumber: "+15550000000",
      validateTwilioSignatures: false,
      logMessageBody: true
    },
    bridge: { run: async (job) => { calls.push(job); return "https://bridge.example.org/files/result.pdf"; } },
    twilioClient: { messages: { create: async (message) => sent.push(message) } },
    logger: { info: (line) => logs.push(line), warn: () => {}, error: () => {} }
  });
  const server = app.listen(0);
  await once(server, "listening");
  const port = server.address().port;
  const response = await fetch(`http://127.0.0.1:${port}/twilio/inbound`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      From: "+919999999999",
      Body: "EDIT PDF https://files.example.org/report.docx :: add a summary",
      MessageSid: "SM123"
    })
  });
  assert.equal(response.status, 200);
  await new Promise((resolve) => setTimeout(resolve, 10));
  server.close();

  assert.deepEqual(calls[0], {
    messageSid: "SM123", action: "EDIT", format: "pdf",
    reference: "https://files.example.org/report.docx", instruction: "add a summary"
  });
  assert.deepEqual(sent, [{ to: "+919999999999", from: "+15550000000", body: "Done: https://bridge.example.org/files/result.pdf" }]);
  assert.match(logs[0], /"messageSid":"SM123"/);
  assert.match(logs[0], /"from":"\+919999999999"/);
  assert.match(logs[0], /add a summary/);
});

test("serves generated result files from /files", async () => {
  const resultsDir = await mkdtemp(path.join(os.tmpdir(), "sms-bridge-"));
  await writeFile(path.join(resultsDir, "result.txt"), "hello");
  const app = createApp({
    config: {
      publicBaseUrl: "https://bridge.example.org",
      resultsDir,
      twilioAuthToken: "test",
      twilioPhoneNumber: "+15550000000",
      validateTwilioSignatures: false,
      logMessageBody: false
    },
    bridge: { run: async () => "https://bridge.example.org/files/result.txt" },
    twilioClient: { messages: { create: async () => {} } },
    logger: { info: () => {}, warn: () => {}, error: () => {} }
  });
  const server = app.listen(0);
  await once(server, "listening");
  const port = server.address().port;
  try {
    const response = await fetch(`http://127.0.0.1:${port}/files/result.txt`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "hello");
  } finally {
    server.close();
    await rm(resultsDir, { recursive: true, force: true });
  }
});
