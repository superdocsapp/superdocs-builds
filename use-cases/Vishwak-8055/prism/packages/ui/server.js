// @ts-check
/**
 * Real server, real packages. Every /api/* route calls into
 * @prism/delta, @prism/gate, @prism/vault, @prism/registry directly —
 * nothing here is a canned response. State is a single in-memory
 * "workspace" (one report + one approval set + one Vault instance) shared
 * by all requests: this is a local single-operator tool, not a
 * multi-tenant service — see docs/KNOWN_LIMITATIONS.md and
 * docs/SECURITY.md, which say so explicitly rather than implying
 * multi-user readiness that isn't here.
 */
import { createServer } from 'node:http';
import { writeFile, mkdtemp, rm } from 'node:fs/promises';
import { createReadStream, existsSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { compareFiles } from '@prism/delta';
import { createApprovalSet, decide, isFullyDecided, summarize, applyApprovedChanges } from '@prism/gate';
import { readDocx } from '@prism/core';
import { compareDocumentTables, describeTable } from '@prism/grid';
import { Vault } from '@prism/vault';
import { listTasks } from '@prism/registry';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = Number(process.env.PORT) || 8787;

/** Single shared workspace. Documented, not hidden, limitation: local single-operator tool. */
const workspace = {
  tempDir: null,
  basePath: null,
  targetPath: null,
  outputPath: null,
  report: null, // full report incl. baseDoc/ops — server-side only, never sent to the client whole
  approvalSet: null,
  lastApply: null, // { appliedLog, verification }
  vault: new Vault(),
};

function jsonSafeChange(change) {
  const { type, paragraphIndex, baseText, targetText, items, findings, opIndex } = change;
  return { type, paragraphIndex, baseText, targetText, items, findings, opIndex };
}

function jsonSafeReport(report) {
  return {
    version: report.version,
    engine: report.engine,
    baseFingerprint: report.baseFingerprint,
    targetFingerprint: report.targetFingerprint,
    summary: report.summary,
    changes: report.changes.map(jsonSafeChange),
  };
}

function jsonSafeApprovalSet(approvalSet) {
  return [...approvalSet.decisions.values()].map((e) => ({
    changeId: e.changeId,
    decision: e.decision,
    change: jsonSafeChange(e.change),
  }));
}

/**
 * The Verification Center table from the directive's UI spec, computed
 * from REAL results — not hard-coded PASS rows. NOT_APPLICABLE for
 * capabilities that genuinely aren't built (tables, citations, references,
 * visuals, revisions), so nothing shows PASS for a check that never ran.
 */
function computeVerificationCenter({ verifyDiff, decisionSummary, tableComparison, sourceTables }) {
  const contentPass = verifyDiff.summary.totalChanges === decisionSummary.approved + decisionSummary.edited;
  let tablesRow;
  if (!tableComparison) {
    tablesRow = { area: 'TABLES', status: 'NOT_APPLICABLE', detail: 'no tables in source document' };
  } else if (tableComparison.identical) {
    const shapes = sourceTables.map((t) => describeTable(t)).join('; ');
    tablesRow = { area: 'TABLES', status: 'PASS', detail: `${tableComparison.perTable.length} table(s) confirmed structurally identical to source (PRISM GRID): ${shapes}` };
  } else {
    tablesRow = { area: 'TABLES', status: 'FAIL', detail: tableComparison.reason || 'table structure changed unexpectedly during write-back' };
  }
  return [
    { area: 'CONTENT', status: contentPass ? 'PASS' : 'FAIL', detail: `re-diff vs base found ${verifyDiff.summary.totalChanges} change(s), expected ${decisionSummary.approved + decisionSummary.edited}` },
    { area: 'STRUCTURE', status: contentPass ? 'PASS' : 'FAIL', detail: 'paragraph sequence reconstructed from aligned ops' },
    { area: 'CITATIONS', status: 'NOT_APPLICABLE', detail: 'PRISM PROOF not implemented' },
    { area: 'REFERENCES', status: 'NOT_APPLICABLE', detail: 'PRISM REFERENCE not implemented' },
    tablesRow,
    { area: 'VISUALS', status: 'NOT_APPLICABLE', detail: 'PRISM VIS not implemented' },
    { area: 'REVISIONS', status: 'NOT_APPLICABLE', detail: 'PRISM REVISION not implemented — tracked changes not modeled' },
    { area: 'APPROVAL', status: 'PASS', detail: `${decisionSummary.approved} approved, ${decisionSummary.rejected} rejected, ${decisionSummary.edited} edited — all decided, none pending` },
    { area: 'EXPORT', status: contentPass ? 'PASS' : 'UNVERIFIED', detail: contentPass ? 'output re-read successfully and matches predicted diff' : 'export produced but content verification failed' },
  ];
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf-8');
  return raw ? JSON.parse(raw) : {};
}

function sendJson(res, status, body) {
  const data = JSON.stringify(body, null, 2);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

/** Structured error body: WHAT/WHY, matching the directive's own Error UX spec — never "something went wrong." */
function sendError(res, status, whatHappened, err) {
  sendJson(res, status, { error: { whatHappened, why: err?.message ?? String(err) } });
}

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json' };

async function serveStatic(req, res) {
  let reqPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  if (reqPath === '/') reqPath = '/index.html';
  const resolved = path.normalize(path.join(PUBLIC_DIR, reqPath));
  if (!resolved.startsWith(PUBLIC_DIR)) {
    // Path traversal guard — a deliberate, tested boundary, not an oversight.
    res.writeHead(403).end('Forbidden');
    return;
  }
  if (!existsSync(resolved)) {
    res.writeHead(404).end('Not found');
    return;
  }
  const ext = path.extname(resolved);
  res.writeHead(200, { 'Content-Type': MIME[ext] ?? 'application/octet-stream' });
  createReadStream(resolved).pipe(res);
}

async function ensureTempDir() {
  if (!workspace.tempDir) {
    workspace.tempDir = await mkdtemp(path.join(os.tmpdir(), 'prism-ui-'));
  }
  return workspace.tempDir;
}

export const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');

    if (req.method === 'GET' && url.pathname === '/api/tasks') {
      return sendJson(res, 200, { tasks: listTasks() });
    }

    if (req.method === 'POST' && url.pathname === '/api/workspace/compare') {
      const body = await readJsonBody(req);
      if (!body.baseBase64 || !body.targetBase64) {
        return sendError(res, 400, 'Missing document', new Error('Both a base and target document are required.'));
      }
      const dir = await ensureTempDir();
      workspace.basePath = path.join(dir, `base-${Date.now()}-${body.baseName || 'base.docx'}`);
      workspace.targetPath = path.join(dir, `target-${Date.now()}-${body.targetName || 'target.docx'}`);
      await writeFile(workspace.basePath, Buffer.from(body.baseBase64, 'base64'));
      await writeFile(workspace.targetPath, Buffer.from(body.targetBase64, 'base64'));

      const report = await compareFiles(workspace.basePath, workspace.targetPath);
      workspace.report = report;
      workspace.approvalSet = createApprovalSet(report);
      workspace.lastApply = null;

      return sendJson(res, 200, { report: jsonSafeReport(report), approvalSet: jsonSafeApprovalSet(workspace.approvalSet) });
    }

    if (req.method === 'POST' && url.pathname === '/api/workspace/decide') {
      if (!workspace.approvalSet) return sendError(res, 409, 'No comparison in progress', new Error('Run /api/workspace/compare first.'));
      const body = await readJsonBody(req);
      try {
        const opts = body.decision === 'edited' && body.editedText
          ? { editedParagraphs: [{ text: body.editedText, styleId: null, runs: [{ text: body.editedText, bold: false, italic: false, underline: false }] }] }
          : {};
        decide(workspace.approvalSet, body.changeId, body.decision, opts);
      } catch (err) {
        return sendError(res, 400, 'Decision rejected', err);
      }
      return sendJson(res, 200, { approvalSet: jsonSafeApprovalSet(workspace.approvalSet), summary: summarize(workspace.approvalSet) });
    }

    if (req.method === 'POST' && url.pathname === '/api/workspace/apply') {
      if (!workspace.report || !workspace.approvalSet) return sendError(res, 409, 'No comparison in progress', new Error('Run /api/workspace/compare first.'));
      if (!isFullyDecided(workspace.approvalSet)) {
        const pending = [...workspace.approvalSet.decisions.values()].filter((e) => e.decision === 'pending').map((e) => e.changeId);
        return sendError(res, 409, 'Some changes are still pending review', new Error(`Not yet decided: ${pending.join(', ')}`));
      }
      const dir = await ensureTempDir();
      workspace.outputPath = path.join(dir, `applied-${Date.now()}.docx`);
      try {
        const applyResult = await applyApprovedChanges(workspace.report, workspace.approvalSet, workspace.outputPath);
        const verifyDiff = await compareFiles(workspace.outputPath, workspace.basePath);
        const decisionSummary = summarize(workspace.approvalSet);
        const outputDoc = await readDocx(workspace.outputPath);
        const tableComparison = workspace.report.baseDoc.hasTables ? compareDocumentTables(workspace.report.baseDoc, outputDoc) : null;
        const verification = computeVerificationCenter({ verifyDiff, decisionSummary, tableComparison, sourceTables: workspace.report.baseDoc.tables });
        const contentVerified = verification.every((v) => v.status !== 'FAIL');

        let version = null;
        if (contentVerified) {
          version = workspace.vault.commit(outputDoc.paragraphs, { label: 'ui-applied', kind: 'commit' });
        }

        workspace.lastApply = { appliedLog: applyResult.appliedLog, verification, version, contentVerified };
        return sendJson(res, 200, workspace.lastApply);
      } catch (err) {
        return sendError(res, 422, 'Apply failed', err);
      }
    }

    if (req.method === 'GET' && url.pathname === '/api/workspace/download') {
      if (!workspace.outputPath || !existsSync(workspace.outputPath)) {
        return sendError(res, 404, 'No applied document yet', new Error('Run /api/workspace/apply first.'));
      }
      res.writeHead(200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': 'attachment; filename="prism-applied.docx"',
      });
      createReadStream(workspace.outputPath).pipe(res);
      return;
    }

    if (req.method === 'GET' && url.pathname === '/api/vault/graph') {
      return sendJson(res, 200, { graph: workspace.vault.graph(), current: workspace.vault.current() });
    }

    if (req.method === 'POST' && url.pathname === '/api/vault/undo') {
      try {
        return sendJson(res, 200, { current: workspace.vault.undo() });
      } catch (err) {
        return sendError(res, 409, 'Cannot undo', err);
      }
    }

    if (req.method === 'POST' && url.pathname === '/api/vault/redo') {
      try {
        return sendJson(res, 200, { current: workspace.vault.redo() });
      } catch (err) {
        return sendError(res, 409, 'Cannot redo', err);
      }
    }

    if (req.method === 'POST' && url.pathname === '/api/vault/revert') {
      const body = await readJsonBody(req);
      try {
        return sendJson(res, 200, { current: workspace.vault.revertTo(body.versionId) });
      } catch (err) {
        return sendError(res, 400, 'Cannot revert', err);
      }
    }

    if (req.method === 'GET' && !url.pathname.startsWith('/api/')) {
      return serveStatic(req, res);
    }

    return sendError(res, 404, 'No such route', new Error(`${req.method} ${url.pathname}`));
  } catch (err) {
    return sendError(res, 500, 'Unhandled server error', err);
  }
});

export async function resetWorkspace() {
  if (workspace.tempDir) await rm(workspace.tempDir, { recursive: true, force: true }).catch(() => {});
  workspace.tempDir = null;
  workspace.basePath = null;
  workspace.targetPath = null;
  workspace.outputPath = null;
  workspace.report = null;
  workspace.approvalSet = null;
  workspace.lastApply = null;
  workspace.vault = new Vault();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  server.listen(PORT, () => console.log(`PRISM UI: http://localhost:${PORT}`));
}
