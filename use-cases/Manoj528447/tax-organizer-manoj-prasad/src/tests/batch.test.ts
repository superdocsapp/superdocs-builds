import { INITIAL_SAMPLE_TAX_RETURNS } from '../data/sampleClients';
import { buildClientSpecificOrganizer } from '../services/organizerGenerator';
import { generateClientLawAnalysis } from '../services/taxLawAnalyzer';
import { generateSuperDocsTargetedDiff, generateMissingItemsFollowUpLetter, classifyExtractionError, isTransientConnectError, withConnectRetry } from '../services/geminiService';
import { buildExportContent } from '../services/exportContent';
import { batchAgentEngine } from '../services/batchEngine';
import { persistenceService } from '../services/persistenceService';
import { parseUploadedDocument } from '../services/documentParser';
import { extractTaxReturnFromDocument } from '../services/geminiService';
import { runSuperDocsApiTests, runTimeoutHardeningTests } from './superDocsApi.test';
import { runDocumentParserTests } from './documentParser.test';
import { runFormattingTests, runGreetingRegressionTests, runCitationGroundingTests } from './formatting.test';

/**
 * SuperDocs Tax Batch Engine Automated Test Suite
 * Covers Unit Tests, API Contracts, and Integration Tests.
 */
async function runTestSuite() {
  console.log('🧪 Starting SuperDocs Automated Test Suite...\n');
  let passed = 0;
  let failed = 0;

  function assert(condition: boolean, testName: string) {
    if (condition) {
      console.log(`  ✅ [PASS] ${testName}`);
      passed++;
    } else {
      console.error(`  ❌ [FAIL] ${testName}`);
      failed++;
    }
  }

  // --- UNIT TESTS ---
  console.log('--- 1. Unit Tests ---');

  // Test 1: Dynamic Organizer Generator
  const sampleBusinessClient = INITIAL_SAMPLE_TAX_RETURNS[0];
  const organizer = buildClientSpecificOrganizer(sampleBusinessClient);
  assert(organizer.length >= 3, 'Organizer builds at least 3 client-specific sections');
  assert(
    organizer.some((sec) => sec.category === 'entities'),
    'Business client organizer includes Business Entities section'
  );
  assert(
    organizer.some((sec) =>
      sec.requiredDocuments.some((d) => d.sourceCitation.includes('Schedule C'))
    ),
    'Organizer document items include grounded line citations (Schedule C)'
  );

  // Test 2: Client Law Analysis Generator
  const lawLetter = generateClientLawAnalysis(sampleBusinessClient);
  assert(lawLetter.personalizedLawParagraphs.length > 0, 'Generates personalized tax law update paragraphs');
  assert(
    lawLetter.personalizedLawParagraphs.some((p) => p.lawTitle.includes('QBI') || p.lawTitle.includes('§179')),
    'Law update matches QBI / Section 179 for business segment'
  );

  // Test 3: SuperDocs Diff Engine
  const diffs = await generateSuperDocsTargetedDiff(
    'Tax Letter',
    'Add note about $50,000 Section 179 equipment purchase',
    'Initial letter text'
  );
  assert(diffs.length > 0, 'Generates targeted proposed diffs array');
  assert(diffs[0].status === 'pending', 'Diff status defaults to pending for human review gate');

  // Test 4: Missing Items Follow-up Generator
  const followUpText = await generateMissingItemsFollowUpLetter(
    'Apex Innovations LLC',
    'business',
    ['Form 1099-NEC', 'Section 179 Invoices'],
    ['Form W-2']
  );
  assert(followUpText.includes('Apex Innovations LLC') || followUpText.includes('Form 1099-NEC') || followUpText.length > 50, 'Follow-up letter is generated with client parameters');

  // Test 5: Document Parsing & Validation
  console.log('\n--- Document Parser & Validation Tests ---');

  // 5a. Valid TXT upload
  const txtBuffer = Buffer.from('Client Name: Acme Corp\nForm 1040 Line 1a: $150,000\nSchedule C Net Profit: $95,000');
  const txtResult = await parseUploadedDocument(txtBuffer, 'acme_return.txt', 'text/plain');
  assert(txtResult.fileType === 'txt', 'Correctly identifies TXT document format');
  assert(txtResult.textContent.includes('Acme Corp'), 'Extracts text content from TXT file');

  // 5b. Empty file validation
  try {
    await parseUploadedDocument(Buffer.from(''), 'empty.txt', 'text/plain');
    assert(false, 'Should reject empty document');
  } catch (err: any) {
    assert(err.message.includes('empty'), 'Rejects empty document with clear error message');
  }

  // 5c. Unsupported file type validation
  try {
    await parseUploadedDocument(Buffer.from('some binary data'), 'executable.exe', 'application/x-msdownload');
    assert(false, 'Should reject unsupported file type');
  } catch (err: any) {
    assert(err.message.includes('Unsupported file type'), 'Rejects unsupported file type (.exe)');
  }

  // 5d. Corrupted PDF validation
  try {
    await parseUploadedDocument(Buffer.from('NOT_A_REAL_PDF_HEADER'), 'corrupted.pdf', 'application/pdf');
    assert(false, 'Should reject corrupted PDF');
  } catch (err: any) {
    assert(err.message.includes('PDF') || err.message.includes('Failed'), 'Rejects corrupted PDF file cleanly without crashing');
  }

  // 5e. Corrupted DOCX validation
  try {
    await parseUploadedDocument(Buffer.from('NOT_A_ZIP_OR_DOCX_HEADER'), 'corrupted.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    assert(false, 'Should reject corrupted DOCX');
  } catch (err: any) {
    assert(err.message.includes('DOCX') || err.message.includes('Failed'), 'Rejects corrupted DOCX file cleanly without crashing');
  }

  // 5f. Verify extracted text passes to extractTaxReturnFromDocument
  const extractedReturn = await extractTaxReturnFromDocument(txtResult.textContent);
  assert(Boolean(extractedReturn.clientName || extractedReturn.income), 'Passes parsed document text to extractTaxReturnFromDocument successfully');

  // --- INTEGRATION TESTS ---
  console.log('\n--- 2. Batch Engine Integration Tests ---');

  const initialCheckpoint = batchAgentEngine.getCheckpoint();
  assert(initialCheckpoint.clientRecords.length >= 5, 'Engine initializes with at least 5 sample client profiles');

  // Stage execution test
  const stageUpdated = await batchAgentEngine.runStage('INGEST_PRIOR_RETURN');
  assert(
    stageUpdated.completedStages.includes('INGEST_PRIOR_RETURN'),
    'Stage INGEST_PRIOR_RETURN completes successfully'
  );

  // Idempotency: re-running an already-completed stage must NOT add cost again.
  // (Regression for: clicking Run Full Pipeline repeatedly kept increasing cost
  // for work already checkpointed.)
  const costBeforeRerun = stageUpdated.totalCostEstimate;
  const afterRerun = await batchAgentEngine.runStage('INGEST_PRIOR_RETURN');
  assert(
    afterRerun.totalCostEstimate === costBeforeRerun,
    `Re-running a completed stage does not re-charge cost (was ${costBeforeRerun}, still ${afterRerun.totalCostEstimate})`
  );

  // Reset clears completed stages and cost so a fresh run starts clean.
  const afterReset = batchAgentEngine.resetEngine();
  assert(
    afterReset.completedStages.length === 0 && afterReset.totalCostEstimate === 0,
    'Reset clears completed stages and zeroes the cost estimate'
  );

  // Approve-then-resume flow: first full run stops at the human gate; after
  // all diffs are approved, a second full run must advance through the
  // post-gate stages (EXECUTE_APPROVALS, TRACK_MISSING_ITEMS, DRAFT_FOLLOWUP)
  // instead of staying stuck at stage 5. Regression for: the runFullPipeline
  // stages array was missing EXECUTE_APPROVALS, so it could never advance.
  const firstRun = await batchAgentEngine.runFullPipeline();
  assert(
    firstRun.completedStages.includes('SUPERDOCS_DIFF_GATE') &&
      !firstRun.completedStages.includes('DRAFT_FOLLOWUP'),
    'First full pipeline run stops at the human review gate (does not auto-complete)'
  );
  // Approve every diff on every client.
  firstRun.clientRecords.forEach((c) => {
    c.diffs.forEach((d) => batchAgentEngine.updateDiffStatus(c.id, d.id, 'approved'));
  });
  const resumed = await batchAgentEngine.runFullPipeline();
  assert(
    resumed.completedStages.includes('SUPERDOCS_DIFF_GATE'),
    'Diff gate (stage 5) stays marked complete after all diffs are decided (ticks green like other stages)'
  );
  assert(
    resumed.completedStages.includes('EXECUTE_APPROVALS'),
    'After approval, pipeline advances through EXECUTE_APPROVALS (stage 6)'
  );
  assert(
    resumed.completedStages.includes('DRAFT_FOLLOWUP'),
    'After approval, pipeline runs to completion (DRAFT_FOLLOWUP, stage 8)'
  );
  const runtimeAfterComplete = resumed.totalDurationMs;
  const runAgain = await batchAgentEngine.runFullPipeline();
  assert(
    runAgain.totalDurationMs === runtimeAfterComplete,
    `Re-running a completed pipeline does not increase runtime (was ${runtimeAfterComplete}, still ${runAgain.totalDurationMs})`
  );
  batchAgentEngine.resetEngine();

  // --- Partial-approval gate + bulk-release regression ---------------------
  // The exact failure from the field: the review UI approves diffs one client
  // at a time, but the gate is batch-wide. Approving only the FIRST client and
  // then running the full pipeline must STILL hold at the gate (because other
  // clients remain pending) -- and it must not silently advance. Then a single
  // batch-level "approve all remaining" must release the gate so the pipeline
  // completes. This is the class of bug behind "stuck at stage 5 with the
  // yellow dot and climbing runtime".
  const partialFirst = await batchAgentEngine.runFullPipeline();
  const firstClientOnly = partialFirst.clientRecords[0];
  firstClientOnly.diffs.forEach((d) =>
    batchAgentEngine.updateDiffStatus(firstClientOnly.id, d.id, 'approved')
  );
  const stillHeld = await batchAgentEngine.runFullPipeline();
  assert(
    !stillHeld.completedStages.includes('EXECUTE_APPROVALS'),
    'Approving only one client does NOT release the batch-wide gate (pipeline stays at stage 5)'
  );
  const stillPendingCount = stillHeld.clientRecords.reduce(
    (acc, c) => acc + c.diffs.filter((d) => d.status === 'pending').length,
    0
  );
  assert(
    stillPendingCount > 0,
    `Other clients' diffs remain pending after a single-client approval (found ${stillPendingCount})`
  );
  // The gate should have logged WHY it held, naming the blocking clients,
  // rather than re-pausing silently.
  const heldLog = stillHeld.logs.some(
    (l) => l.stage === 'SUPERDOCS_DIFF_GATE' && /Gate held:/.test(l.message)
  );
  assert(heldLog, 'Gate logs an explicit "Gate held" reason naming the blocking clients');

  // Bulk-decide the remainder in one action -> gate releases.
  const bulk = batchAgentEngine.decideAllPendingDiffs('approved');
  assert(
    bulk.decidedCount === stillPendingCount,
    `Bulk approve decides exactly the remaining pending diffs (decided ${bulk.decidedCount}, expected ${stillPendingCount})`
  );
  const afterBulk = await batchAgentEngine.runFullPipeline();
  assert(
    afterBulk.completedStages.includes('EXECUTE_APPROVALS') &&
      afterBulk.completedStages.includes('DRAFT_FOLLOWUP'),
    'After bulk approve-all, pipeline releases the gate and runs to completion'
  );
  // Bulk decide must never overwrite an existing decision, and is a no-op when
  // nothing is pending.
  const bulkAgain = batchAgentEngine.decideAllPendingDiffs('rejected');
  assert(
    bulkAgain.decidedCount === 0,
    'Bulk decide is a no-op once no diffs are pending (never overwrites existing decisions)'
  );
  batchAgentEngine.resetEngine();

  // --- Extraction error classifier (honest fallback diagnosis) -------------
  // The exact failure hit in live testing: Gemini unreachable with
  // UND_ERR_CONNECT_TIMEOUT. The classifier must diagnose network vs auth vs
  // quota vs unknown so the UI can tell the user WHY a generic organizer was
  // shown instead of dumping a raw stack trace or silently looking thin.
  const netErr = classifyExtractionError({ message: 'fetch failed', cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } });
  assert(netErr.code === 'network_unreachable', 'Classifier tags UND_ERR_CONNECT_TIMEOUT as network_unreachable');
  assert(/unreachable|network|VPN|firewall/i.test(netErr.message), 'Network diagnosis names the likely cause (network/VPN/firewall)');

  assert(
    classifyExtractionError(new Error('getaddrinfo ENOTFOUND generativelanguage.googleapis.com')).code === 'network_unreachable',
    'Classifier tags DNS ENOTFOUND as network_unreachable'
  );
  assert(
    classifyExtractionError({ message: 'Request failed: 403 PERMISSION_DENIED (API key invalid)' }).code === 'auth',
    'Classifier tags 403/PERMISSION_DENIED as auth'
  );
  assert(
    classifyExtractionError({ message: '429 RESOURCE_EXHAUSTED: quota exceeded' }).code === 'rate_limit',
    'Classifier tags 429/RESOURCE_EXHAUSTED as rate_limit'
  );
  assert(
    classifyExtractionError({ message: 'something weird happened' }).code === 'unknown',
    'Classifier falls back to unknown for unrecognized errors'
  );
  assert(
    /generic organizer|instead of fabricated/i.test(netErr.message),
    'Every diagnosis reassures that generic (not fabricated) data is shown'
  );

  // --- Connect-retry (transient IPv6 stall recovery) -----------------------
  // The live symptom: an occasional UND_ERR_CONNECT_TIMEOUT on a Gemini call
  // (IPv6 route stalls while IPv4 works). A single retry should recover it,
  // while a non-transient error (auth) must fail fast without retrying.
  assert(isTransientConnectError({ cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } }), 'Connect-timeout is treated as transient (retryable)');
  assert(!isTransientConnectError({ message: '403 PERMISSION_DENIED' }), 'Auth error is NOT treated as transient (fails fast)');
  assert(isTransientConnectError({ status: 500, message: 'Internal error encountered.' }), 'Transient 500 INTERNAL is retryable (Google-side hiccup)');
  assert(!isTransientConnectError({ status: 429, message: '429 RESOURCE_EXHAUSTED quota' }), 'Quota 429 is NOT retried as transient (would just burn quota)');

  let calls = 0;
  const recovered = await withConnectRetry(async () => {
    calls++;
    if (calls === 1) throw { cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } };
    return 'ok';
  });
  assert(recovered === 'ok' && calls === 2, 'withConnectRetry recovers on the second attempt after a transient connect failure');

  let authCalls = 0;
  let failedFast = false;
  try {
    await withConnectRetry(async () => {
      authCalls++;
      throw new Error('403 PERMISSION_DENIED');
    });
  } catch {
    failedFast = true;
  }
  assert(failedFast && authCalls === 1, 'withConnectRetry does NOT retry a non-transient (auth) error');

  batchAgentEngine.resetEngine();

  // --- Export content includes approved edits (Option B) -------------------
  // "Export the finished file" must return a document containing the edits the
  // CPA approved -- not the raw source. Verify approved diffs appear in the
  // exported content, and rejected/pending diffs do NOT.
  const exportCp = await batchAgentEngine.runFullPipeline();
  const exClient = JSON.parse(JSON.stringify(exportCp.clientRecords[0])) as typeof exportCp.clientRecords[0];
  exClient.diffs = [
    { id: 'd-appr', targetSectionId: 's1', locationLabel: 'Solar & Battery Upgrade', changeType: 'addition', originalText: '', proposedText: 'APPROVED_EDIT_MARKER: retain §25D manufacturer certification statement.', explanation: 'x', citation: '', status: 'approved' },
    { id: 'd-rej', targetSectionId: 's2', locationLabel: 'Rejected Section', changeType: 'modification', originalText: '', proposedText: 'REJECTED_EDIT_MARKER should not appear.', explanation: 'x', citation: '', status: 'rejected' },
    { id: 'd-pend', targetSectionId: 's3', locationLabel: 'Pending Section', changeType: 'modification', originalText: '', proposedText: 'PENDING_EDIT_MARKER should not appear.', explanation: 'x', citation: '', status: 'pending' }
  ];
  const letterExport = buildExportContent(exClient, 'letter');
  assert(letterExport.includes('APPROVED_EDIT_MARKER'), 'Exported letter INCLUDES the approved diff text');
  assert(!letterExport.includes('REJECTED_EDIT_MARKER'), 'Exported letter EXCLUDES rejected diff text');
  assert(!letterExport.includes('PENDING_EDIT_MARKER'), 'Exported letter EXCLUDES still-pending diff text');
  assert(/APPROVED EDITS/.test(letterExport), 'Exported letter labels the applied-edits section');

  const organizerExport = buildExportContent(exClient, 'organizer');
  assert(organizerExport.includes('APPROVED_EDIT_MARKER'), 'Exported organizer also includes approved diff text');

  // With no approved diffs, export is just the base document (no edits section).
  exClient.diffs = exClient.diffs.map((d) => ({ ...d, status: 'rejected' as const }));
  const noApproved = buildExportContent(exClient, 'letter');
  assert(!/APPROVED EDITS/.test(noApproved), 'Export omits the applied-edits section when nothing is approved');
  batchAgentEngine.resetEngine();

  batchAgentEngine.resetEngine();

  // --- Approved edits merge into the letter (root fix) ----------------------
  // Approving a diff must merge its text into yearEndLetter.appliedEdits, so
  // EVERY view (preview, copy, print, export) reflects it -- not just export.
  // Rejecting must remove it again, so toggling stays consistent.
  const mergeCp = await batchAgentEngine.runFullPipeline();
  const mClient = mergeCp.clientRecords[0];
  const firstDiff = mClient.diffs[0];
  batchAgentEngine.updateDiffStatus(mClient.id, firstDiff.id, 'approved');
  let refreshed = batchAgentEngine.getCheckpoint().clientRecords[0];
  assert(
    (refreshed.yearEndLetter.appliedEdits || []).some((e) => e.includes(firstDiff.locationLabel)),
    'Approving a diff merges its text into yearEndLetter.appliedEdits (preview/export share one source)'
  );
  // Export now reads the merged appliedEdits.
  const mergedExport = buildExportContent(refreshed, 'letter');
  assert(mergedExport.includes(firstDiff.locationLabel), 'Export reflects the merged appliedEdits');
  // Reject removes it again.
  batchAgentEngine.updateDiffStatus(mClient.id, firstDiff.id, 'rejected');
  refreshed = batchAgentEngine.getCheckpoint().clientRecords[0];
  assert(
    !(refreshed.yearEndLetter.appliedEdits || []).some((e) => e.startsWith(`${firstDiff.locationLabel}:`)),
    'Rejecting a previously-approved diff removes it from appliedEdits (consistent toggle)'
  );
  batchAgentEngine.resetEngine();

  // Diff Approval test
  const testClient = stageUpdated.clientRecords[0];
  if (testClient.diffs.length > 0) {
    const diffId = testClient.diffs[0].id;
    const afterApproval = batchAgentEngine.updateDiffStatus(testClient.id, diffId, 'approved');
    const updatedDiff = afterApproval.clientRecords
      .find((c) => c.id === testClient.id)
      ?.diffs.find((d) => d.id === diffId);
    assert(updatedDiff?.status === 'approved', 'Diff status updates to approved');
  }

  // Persistence test
  const auditLogs = persistenceService.getAuditTrail();
  assert(auditLogs.length > 0, 'Persistence service logs audit trail entries');

  // --- 3. SuperDocs API Client Contract Tests (mocked, no live key needed) ---
  const superDocsApiResult = await runSuperDocsApiTests();
  passed += superDocsApiResult.passed;
  failed += superDocsApiResult.failed;

  // --- 4. Document Parser Tests (real PDF bytes, not mocked) ---
  const docParserResult = await runDocumentParserTests();
  passed += docParserResult.passed;
  failed += docParserResult.failed;

  // --- 5. Network Timeout Hardening Tests ---
  const timeoutResult = await runTimeoutHardeningTests();
  passed += timeoutResult.passed;
  failed += timeoutResult.failed;

  // --- 6. Currency Formatting Tests (locale regression) ---
  const formattingResult = await runFormattingTests();
  passed += formattingResult.passed;
  failed += formattingResult.failed;

  // --- 7. Greeting & Schedule-List Regression Tests ("Dear extra.pdf," / "()") ---
  const greetingResult = await runGreetingRegressionTests();
  passed += greetingResult.passed;
  failed += greetingResult.failed;

  // --- 8. Citation Grounding Tests (false "Schedule E, Part II" regression) ---
  const citationResult = await runCitationGroundingTests();
  passed += citationResult.passed;
  failed += citationResult.failed;

  console.log(`\n========================================`);
  console.log(`🎉 TEST SUMMARY: ${passed} PASSED, ${failed} FAILED.`);
  console.log(`========================================\n`);

  if (failed > 0) {
    process.exit(1);
  }
}

runTestSuite().catch((err) => {
  console.error('Test execution error:', err);
  process.exit(1);
});
