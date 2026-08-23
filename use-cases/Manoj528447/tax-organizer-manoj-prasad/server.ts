// MUST be the first import: dotenv is a listed dependency but was never
// actually invoked anywhere in this codebase, so .env was silently ignored
// the whole time -- GEMINI_API_KEY / SUPERDOCS_API_KEY only "worked" if they
// happened to already be exported in the shell environment. This has to run
// before any other import, since some modules (geminiService.ts) read
// process.env at import time, not call time -- import order matters here.
import 'dotenv/config';

// Prefer IPv4 for outbound calls. On some Windows/Node setups the default
// (verbatim) DNS order hands back an IPv6 address that the OS then can't
// actually route, so fetch() sits on the dead IPv6 socket until it hits the
// connect timeout (UND_ERR_CONNECT_TIMEOUT) -- even though the same host is
// reachable over IPv4 (curl succeeds because it falls back). Forcing IPv4-first
// makes the app's Gemini/SuperDocs calls take the route that actually works.
// Harmless on machines where IPv6 is fine; it only reorders preference.
import dns from 'dns';
dns.setDefaultResultOrder('ipv4first');

import express from 'express';
import path from 'path';
import multer from 'multer';
import { createServer as createViteServer } from 'vite';
import { batchAgentEngine } from './src/services/batchEngine';
import {
  extractTaxReturnFromDocument,
  generateSuperDocsTargetedDiff,
  generateMissingItemsFollowUpLetter
} from './src/services/geminiService';
import { superDocsApiClient } from './src/services/superDocsApiService';
import { buildExportContent } from './src/services/exportContent';
import { CURRENT_TAX_LAW_UPDATES } from './src/data/taxLawUpdates';
import { persistenceService } from './src/services/persistenceService';
import { parseUploadedDocument } from './src/services/documentParser';
import { TaxReturnData } from './src/types';

const app = express();
const PORT = 3000;

app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ extended: true, limit: '20mb' }));

const upload = multer({ storage: multer.memoryStorage() });

// --- REST API ENDPOINTS ---

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// GET current checkpoint state
app.get('/api/checkpoint', (_req, res) => {
  res.json(batchAgentEngine.getCheckpoint());
});

// POST restore saved checkpoint
app.post('/api/checkpoint/restore', (req, res) => {
  if (req.body) {
    batchAgentEngine.restoreCheckpoint(req.body);
    res.json({ success: true, checkpoint: batchAgentEngine.getCheckpoint() });
  } else {
    res.status(400).json({ error: 'Missing checkpoint body' });
  }
});

// POST reset engine
app.post('/api/checkpoint/reset', (_req, res) => {
  res.json(batchAgentEngine.resetEngine());
});

// POST execute specific stage
app.post('/api/batch/run-stage', async (req, res) => {
  const { stage } = req.body;
  if (!stage) {
    res.status(400).json({ error: 'Stage parameter required' });
    return;
  }
  const updated = await batchAgentEngine.runStage(stage);
  res.json(updated);
});

// POST trigger full agent pipeline
app.post('/api/batch/run-all', async (_req, res) => {
  const updated = await batchAgentEngine.runFullPipeline();
  res.json(updated);
});

// 1. Upload Document API (SuperDocs Contract: POST /api/documents/upload)
app.post('/api/documents/upload', upload.single('file'), async (req, res) => {
  try {
    let textContent = req.body.rawText || '';

    if (req.file) {
      const parsed = await parseUploadedDocument(
        req.file.buffer,
        req.file.originalname,
        req.file.mimetype
      );
      textContent = parsed.textContent;
    }

    if (!textContent) {
      res.status(400).json({ error: 'No document file or raw text provided' });
      return;
    }

    // Attempt remote SuperDocs API upload if configured via SUPERDOCS_API_KEY.
    // Note: the real SuperDocs upload endpoint (POST /v1/documents/upload) takes
    // the raw file bytes via multipart, not a rawText JSON field, and is scoped
    // to a session_id rather than returning a document id. We only attempt this
    // when an actual file (not pasted rawText) was provided, since a real file
    // buffer + mimetype is what the endpoint expects.
    const provisionalClientId = `cli-${Date.now()}`;
    // batchEngine.buildClientRecord() below derives record.id as `batch-${clientId}`;
    // compute it up front so the SuperDocs session_id we upload into is the same
    // one later chat/approve/export calls will target for this client record.
    const provisionalRecordId = `batch-${provisionalClientId}`;
    if (superDocsApiClient.isConfigured() && req.file) {
      const apiResult = await superDocsApiClient.uploadDocument(
        req.file.buffer,
        req.file.originalname,
        req.file.mimetype,
        provisionalRecordId
      );
      if (apiResult) {
        // Log to the TERMINAL as well as the in-app audit trail. Previously the
        // success confirmation went only to the audit log, so a successful real
        // upload printed nothing in the console -- making it impossible to tell
        // "succeeded" from "never ran" by watching the terminal. Now every
        // outcome (success / failure / skipped) is visible on stdout.
        console.log(
          `[SuperDocs] Uploaded document via real SuperDocs REST API (session ${apiResult.sessionId}, ${apiResult.chunksCount} chunks): ${req.file.originalname}`
        );
        persistenceService.addAuditEntry({
          actor: 'SuperDocsRestAPI',
          action: 'UPLOAD_DOCUMENT_REMOTE',
          details: `Uploaded document via real SuperDocs REST API (session ${apiResult.sessionId}, ${apiResult.chunksCount} chunks): ${req.file.originalname}`
        });
      } else {
        console.warn('[SuperDocs] Remote upload returned no result; continuing with local extraction only.');
      }
    } else if (req.file && !superDocsApiClient.isConfigured()) {
      console.log('[SuperDocs] Skipped remote upload: SUPERDOCS_API_KEY not configured. Using local extraction only.');
    } else if (!req.file) {
      console.log('[SuperDocs] Skipped remote upload: pasted text (no file). The real /v1/documents/upload endpoint needs an actual file.');
    }

    const extracted = await extractTaxReturnFromDocument(textContent);

    const fullTaxReturn: TaxReturnData = {
      clientId: provisionalClientId,
      // NEVER fall back to the raw uploaded filename here -- clientName gets
      // used directly in client-facing prose ("Dear ${clientName}," and
      // "your 2024 tax return (...)"). A filename like "extra.pdf" produced
      // "Dear extra.pdf," in a real letter, which is a genuine bug, not just
      // a cosmetic one: a CPA could accidentally send that as-is. The
      // filename is still preserved below as sourceFileName so the card can
      // show it for traceability without it leaking into letter text.
      clientName: extracted.clientName || 'Unidentified Client',
      sourceFileName: req.file?.originalname,
      // Previously Math.random() -- generated a DIFFERENT fake SSN/EIN suffix
      // every time the exact same file was uploaded (verified directly: the
      // same sample-1-business-scorp.txt produced "**-3220" in one test and
      // "**-9572" in another). The extraction schema doesn't even request
      // SSN/EIN (appropriately -- it's sensitive PII), so there was never a
      // real value to fall back to. 'N/A' matches the honesty convention
      // already used elsewhere in this app for genuinely unavailable data,
      // instead of presenting a random number as if it meant something.
      ssnEinLast4: 'N/A',
      segment: (extracted.segment as any) || 'business',
      taxYear: extracted.taxYear || 2024,
      filingStatus: extracted.filingStatus || 'Single / Sole Proprietor',
      income: extracted.income || { businessNetProfit: 120000 },
      schedulesApplied: extracted.schedulesApplied || ['Form 1040', 'Schedule C'],
      deductionsClaimed: extracted.deductionsClaimed || { standardOrItemized: 'standard' },
      entitiesInvolved: extracted.entitiesInvolved || ['Uploaded Client Entity'],
      priorYearFormSources: extracted.priorYearFormSources || [
        { field: 'Extracted Net Revenue', value: '$120,000', sourceLine: 'Schedule C, Line 31' }
      ],
      // Present only when AI extraction fell back (network/auth/quota). Drives
      // an honest "AI extraction unavailable" notice on the client card instead
      // of a generic record that looks like a real-but-thin extraction.
      extractionNotice: extracted.extractionNotice
    };

    const record = batchAgentEngine.buildClientRecord(fullTaxReturn);
    const updated = batchAgentEngine.addClientRecord(record);

    persistenceService.addAuditEntry({
      actor: 'SystemUpload',
      action: 'UPLOAD_DOCUMENT',
      clientRecordId: record.id,
      details: `Uploaded tax document for ${record.clientName}`
    });

    res.json({
      success: true,
      extractedReturn: fullTaxReturn,
      record,
      checkpoint: updated
    });
  } catch (err: any) {
    res.status(500).json({ error: err.message || 'Failed to process uploaded document' });
  }
});

// 2. Chat/Edit API (SuperDocs Contract: POST /api/documents/:id/chat & POST /api/documents/chat-edit)
const handleChatEdit = async (req: express.Request, res: express.Response) => {
  try {
    const documentId = req.params.id || req.body.documentId || req.body.clientRecordId;
    const { documentTitle, instruction, currentContent, clientRecordId } = req.body;

    if (!instruction) {
      res.status(400).json({ error: 'Edit instruction parameter required' });
      return;
    }

    const targetClientId = documentId || clientRecordId;
    let generatedDiffs: any = null;
    let usedRealApi = false;

    // Call the real SuperDocs REST API if configured with SUPERDOCS_API_KEY.
    // Real flow (session-based, async, HITL): POST /v1/chat/async to start the
    // edit with approval_mode='ask_every_time', then poll GET /v1/jobs/{job_id}
    // until status='awaiting_approval' and read metadata.pending_changes.
    // Operations can legitimately take 30s-several minutes with no visible
    // progress (documented behavior) -- pollJob() accounts for that.
    if (superDocsApiClient.isConfigured() && targetClientId) {
      const started = await superDocsApiClient.startEditInstruction(targetClientId, instruction);
      if (started) {
        // Remember this job_id so the later approve call can supply it (the
        // real approve endpoint requires job_id).
        superDocsApiClient.rememberJobId(targetClientId, started.jobId);
        const jobResult = await superDocsApiClient.pollJob(started.jobId, targetClientId);
        if (jobResult && jobResult.status === 'awaiting_approval') {
          generatedDiffs = jobResult.pendingChanges;
          usedRealApi = true;
        } else if (jobResult) {
          console.warn(`SuperDocs job settled with status "${jobResult.status}" instead of awaiting_approval; falling back to local diff generation.`);
        }
      }
    }

    // Fallback to internal Gemini / SuperDocs diff generator if the remote call
    // was not configured, failed, or did not produce a reviewable diff set.
    if (!generatedDiffs) {
      generatedDiffs = await generateSuperDocsTargetedDiff(
        documentTitle || 'Tax Document',
        instruction,
        currentContent || ''
      );
    }

    if (targetClientId) {
      const cp = batchAgentEngine.getCheckpoint();
      const client = cp.clientRecords.find((c) => c.id === targetClientId);
      if (client) {
        client.diffs.push(...generatedDiffs);
      }
    }

    persistenceService.addAuditEntry({
      actor: 'CPA_Editor',
      action: 'CHAT_EDIT_INSTRUCTION',
      clientRecordId: targetClientId,
      details: `Issued instruction via ${usedRealApi ? 'real SuperDocs API' : 'local fallback engine'}: "${instruction}"`
    });

    res.json({
      success: true,
      diffs: generatedDiffs,
      checkpoint: batchAgentEngine.getCheckpoint()
    });
  } catch (err: any) {
    res.status(500).json({ error: err.message || 'SuperDocs chat edit failed' });
  }
};

app.post('/api/documents/:id/chat', handleChatEdit);
app.post('/api/documents/chat-edit', handleChatEdit);

// 3. Approve Changes API (SuperDocs Contract: POST /api/documents/:id/approve & POST /api/documents/approve-diff)
const handleApproveDiff = async (req: express.Request, res: express.Response) => {
  try {
    const clientRecordId = req.params.id || req.body.clientRecordId;
    const { diffId, status } = req.body;

    if (!clientRecordId || !diffId || !status) {
      res.status(400).json({ error: 'clientRecordId, diffId, and status are required' });
      return;
    }

    // Real endpoint: POST /v1/chat/{session_id}/approve. The API requires
    // job_id + approved at the top level (a nested changes[] array returns a
    // 422). approveChange() resolves the job_id from the one we remembered
    // when the async chat/edit for this client was started.
    if (superDocsApiClient.isConfigured()) {
      const remoteResult = await superDocsApiClient.approveChange(
        clientRecordId,
        diffId,
        status === 'approved',
        superDocsApiClient.getRememberedJobId(clientRecordId)
      );
      if (remoteResult && remoteResult.skipped) {
        // Expected for locally pre-seeded diffs (no live chat/async job to
        // approve remotely). The local approval below is the real decision.
        // Logged calmly, not as a failure.
        console.info('SuperDocs remote approve not applicable for this diff (local pre-seeded change, no remote job); committing approval locally.');
      } else if (remoteResult) {
        // Real remote approve succeeded against a live awaiting_approval job.
        console.log(`[SuperDocs] ${status === 'approved' ? 'Approved' : 'Rejected'} change via real SuperDocs REST API (diff ${diffId}) for client ${clientRecordId}.`);
      } else {
        console.warn('SuperDocs remote approve failed or was not configured correctly; local approval state still updates.');
      }
    }

    const updated = batchAgentEngine.updateDiffStatus(clientRecordId, diffId, status);
    res.json({ success: true, checkpoint: updated });
  } catch (err: any) {
    res.status(500).json({ error: err.message || 'Diff approval failed' });
  }
};

app.post('/api/documents/:id/approve', handleApproveDiff);
app.post('/api/documents/approve-diff', handleApproveDiff);

// Bulk approve/reject every remaining pending diff across the whole batch.
// Releases the batch-wide human-review gate in one audited action, for the
// common case where per-client review has left other clients' diffs pending.
app.post('/api/documents/approve-all', (req, res) => {
  const status = req.body.status === 'rejected' ? 'rejected' : 'approved';
  const { decidedCount, checkpoint } = batchAgentEngine.decideAllPendingDiffs(status);
  res.json({ success: true, decidedCount, status, checkpoint });
});

// 4. Export Finished Document API (SuperDocs Contract: POST /api/documents/:id/export & POST /api/documents/export)
const handleExportDocument = async (req: express.Request, res: express.Response) => {
  try {
    const clientRecordId = req.params.id || req.body.clientRecordId;
    const exportType = req.body.exportType || 'letter';
    const exportedBy = req.body.exportedBy || 'CPA User';

    const cp = batchAgentEngine.getCheckpoint();
    const client = cp.clientRecords.find((c) => c.id === clientRecordId);

    if (!client) {
      res.status(404).json({ error: 'Client record not found' });
      return;
    }

    // The app's local exportType ('letter' | 'organizer' etc.) picks WHICH piece
    // of generated content to export, which isn't the same axis as SuperDocs'
    // export `format` (docx/pdf/html/markdown/txt) -- that picks the FILE TYPE
    // of whatever document is live in the session. We only call the real export
    // endpoint when a real SuperDocs session exists for this client (i.e. a
    // document was actually uploaded to it earlier), and request PDF as a
    // reasonable default. The binary comes back separately from this app's own
    // locally-rendered text content below, which remains the primary output.
    let remoteExport: { base64: string; contentType: string } | null = null;
    if (superDocsApiClient.isConfigured()) {
      const remoteResult = await superDocsApiClient.exportDocument(clientRecordId, 'pdf');
      if (remoteResult) {
        remoteExport = {
          base64: remoteResult.buffer.toString('base64'),
          contentType: remoteResult.contentType
        };
        console.log(
          `[SuperDocs] Exported document via real SuperDocs REST API (${remoteResult.contentType}, ${remoteResult.buffer.length} bytes) for client ${clientRecordId}.`
        );
      } else {
        console.warn('SuperDocs remote export failed, not configured, or no live session document exists for this client; returning locally-rendered content only.');
      }
    }

    // The finished, edited document (approved diffs applied). Shared, tested
    // builder -- see src/services/exportContent.ts.
    const exportedContent = buildExportContent(client, exportType);

    const record = persistenceService.recordExport(clientRecordId, exportType, exportedBy, exportedContent);

    // Also surface the export in the on-screen decision log (checkpoint.logs),
    // not only the persisted audit trail, so "Execution Audit Trail & Decisions
    // Log" shows exports alongside stage and gate events.
    batchAgentEngine.recordEvent(
      'COMPLETED',
      `Exported ${exportType} for ${client.clientName}${remoteExport ? ' via real SuperDocs API' : ' (local render)'}.`,
      'success'
    );

    res.json({
      success: true,
      exportRecord: record,
      content: exportedContent, // the finished, edited document (approved diffs applied) -- this is what the user downloads
      remoteExportConfirmed: !!remoteExport, // the real SuperDocs /v1/documents/export call was made and returned a file
      remoteFile: remoteExport, // raw SuperDocs-session document (the uploaded source), kept for reference; not the primary download
      checkpoint: batchAgentEngine.getCheckpoint() // updated checkpoint incl. the export event, so the UI decision log refreshes immediately
    });
  } catch (err: any) {
    res.status(500).json({ error: err.message || 'Export document failed' });
  }
};

app.post('/api/documents/:id/export', handleExportDocument);
app.post('/api/documents/export', handleExportDocument);

// POST update document status (received / outstanding / waived)
app.post('/api/documents/update-doc-status', (req, res) => {
  const { clientRecordId, docId, status, fileName } = req.body;
  if (!clientRecordId || !docId || !status) {
    res.status(400).json({ error: 'Missing parameters' });
    return;
  }

  const updated = batchAgentEngine.updateDocumentStatus(clientRecordId, docId, status, fileName);
  res.json({ success: true, checkpoint: updated });
});

// POST generate personalized missing items follow-up letter
app.post('/api/documents/followup-letter', async (req, res) => {
  const { clientName, segment, outstandingItems, receivedItems, clientRecordId } = req.body;

  const letterText = await generateMissingItemsFollowUpLetter(
    clientName || 'Valued Client',
    segment || 'business',
    outstandingItems || [],
    receivedItems || []
  );

  if (clientRecordId) {
    const cp = batchAgentEngine.getCheckpoint();
    const client = cp.clientRecords.find((c) => c.id === clientRecordId);
    if (client) {
      client.followUpLetterDraft = letterText;
    }
  }

  res.json({ success: true, followUpLetter: letterText });
});

// GET audit trail history
app.get('/api/audit-trail', (_req, res) => {
  res.json({
    auditLogs: persistenceService.getAuditTrail(),
    exportHistory: persistenceService.getExportHistory()
  });
});

// GET tax law updates database
app.get('/api/law-updates', (_req, res) => {
  res.json(CURRENT_TAX_LAW_UPDATES);
});

// --- VITE & PRODUCTION SETUP ---

async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa'
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*all', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`TaxOrganizer AI & SuperDocs Engine running on http://0.0.0.0:${PORT}`);

    // Preflight: report whether each key was actually loaded from .env, WITHOUT
    // printing any part of the values (never log secrets, not even a suffix).
    // This turns "I uploaded and saw nothing" into a clear answer: if a key
    // shows "not detected", the live path can't run and the app falls back to
    // local extraction.
    const present = (v?: string) =>
      v && v.trim() ? 'detected ✓' : 'NOT detected — will fall back to local only';
    console.log('  Preflight — environment keys:');
    console.log(`    GEMINI_API_KEY:      ${present(process.env.GEMINI_API_KEY)}`);
    console.log(`    SUPERDOCS_API_KEY:   ${present(process.env.SUPERDOCS_API_KEY)}`);
    console.log(`    SUPERDOCS_API_BASE:  ${process.env.SUPERDOCS_API_BASE_URL || 'https://api.superdocs.app (default)'}`);
    if (!process.env.SUPERDOCS_API_KEY?.trim()) {
      console.log('    -> SuperDocs live path OFF. Upload will use local extraction; the real-API session line will not appear.');
    } else {
      console.log('    -> SuperDocs live path ON. Upload a real FILE (not pasted text) to exercise POST /v1/documents/upload.');
    }
  });
}

startServer();
