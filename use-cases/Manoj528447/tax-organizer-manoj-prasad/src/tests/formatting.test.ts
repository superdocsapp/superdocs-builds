import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { buildClientSpecificOrganizer } from '../services/organizerGenerator';
import { generateClientLawAnalysis } from '../services/taxLawAnalyzer';
import { TaxReturnData } from '../types';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Regression test for a real bug hit during manual testing: dollar amounts
 * were rendered with `.toLocaleString()` and no locale argument, so the
 * digit grouping followed whatever OS/environment locale Node resolved at
 * runtime -- correct on a US-locale machine, but showing Indian-style
 * grouping ("$1,20,000" instead of "$120,000") on a machine configured for
 * India. That's exactly what showed up in a screenshot of the fillable
 * organizer view.
 *
 * This is caught two ways:
 *   1. A functional check that a known value formats with US grouping.
 *   2. A source-scan that fails if any bare, unlocalized `.toLocaleString()`
 *      call is reintroduced in the services that render dollar amounts --
 *      this is the only way to reliably catch this class of bug in a test
 *      environment whose own OS locale may not reproduce the issue (ours
 *      defaults to POSIX/en-US-equivalent grouping, so a purely functional
 *      test alone wouldn't fail here even without the fix).
 */
export async function runFormattingTests() {
  console.log('\n--- Currency Formatting Tests (locale regression) ---');
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

  // --- 1. Functional check ---
  const testClient: TaxReturnData = {
    clientId: 'fmt-test',
    clientName: 'Formatting Test Client',
    ssnEinLast4: '0000',
    segment: 'business',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { businessNetProfit: 120000, w2Wages: 0 },
    schedulesApplied: ['Form 1040', 'Schedule C'],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: ['Test LLC'],
    priorYearFormSources: []
  };

  const organizer = buildClientSpecificOrganizer(testClient);
  const allValues = organizer.flatMap((sec) => sec.requiredDocuments.map((d) => d.priorYearValue));
  const netProfitLine = allValues.find((v) => v.includes('120,000') || v.includes('1,20,000'));

  assert(!!netProfitLine, 'Organizer includes a formatted net profit value for $120,000');
  assert(
    netProfitLine?.includes('$120,000') ?? false,
    `Currency renders with US digit grouping ("$120,000"), not Indian grouping (got: "${netProfitLine}")`
  );
  assert(
    !(netProfitLine?.includes('1,20,000') ?? false),
    'Currency does NOT render with Indian-style digit grouping ("$1,20,000")'
  );

  const lawAnalysis = generateClientLawAnalysis(testClient);
  const lawText = lawAnalysis.personalizedLawParagraphs
    .map((p) => p.relevanceReason + p.estimatedImpact)
    .join(' ');
  if (lawText.includes('120,000') || lawText.includes('1,20,000')) {
    assert(lawText.includes('$120,000'), 'Tax law paragraph currency renders with US digit grouping, not Indian grouping');
  }

  // --- 2. Source-scan guard ---
  // This is the real regression guard: even though this test environment's
  // own default locale happens to match en-US grouping (so a functional
  // test alone could pass by coincidence), a bare .toLocaleString() call
  // will render incorrectly the moment it runs somewhere with a different
  // OS locale -- which is exactly what happened. Scan the actual source of
  // every file that formats currency and fail if any unlocalized call exists.
  const filesToScan = [
    path.join(__dirname, '..', 'services', 'organizerGenerator.ts'),
    path.join(__dirname, '..', 'services', 'taxLawAnalyzer.ts'),
    path.join(__dirname, '..', 'data', 'sampleClients.ts')
  ];

  let foundUnlocalizedCall = false;
  const offendingLines: string[] = [];

  for (const filePath of filesToScan) {
    if (!fs.existsSync(filePath)) continue;
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      // Matches .toLocaleString() with no arguments (locale-dependent), but
      // not .toLocaleString('en-US') or similar explicit-locale calls.
      if (/\.toLocaleString\(\s*\)/.test(line)) {
        foundUnlocalizedCall = true;
        offendingLines.push(`${path.basename(filePath)}:${idx + 1}: ${line.trim()}`);
      }
    });
  }

  assert(
    !foundUnlocalizedCall,
    foundUnlocalizedCall
      ? `No unlocalized .toLocaleString() calls in currency-formatting source files (found: ${offendingLines.join('; ')})`
      : 'No unlocalized .toLocaleString() calls in currency-formatting source files'
  );

  // --- Print isolation contract (regression for duplicated-page printout) ---
  // The Print Page path prints exactly one copy of the document by copying its
  // text into #print-portal (a direct child of <body>, sibling of #root) and
  // showing only that while hiding #root. If any of these three pieces drift
  // out of sync -- the portal node in index.html, the CSS that isolates it, or
  // the modal writing into it -- printing regresses to the old two-sheet
  // duplicate. Assert the contract holds across all three files.
  const indexHtml = fs.readFileSync(path.join(__dirname, '../../index.html'), 'utf8');
  assert(
    /id=["']print-portal["']/.test(indexHtml),
    'index.html contains the #print-portal isolation node'
  );

  const indexCss = fs.readFileSync(path.join(__dirname, '../index.css'), 'utf8');
  const cssCollapsed = indexCss.replace(/\s+/g, ' ');
  assert(
    /@media print/.test(indexCss) && /html\.printing #root \{ display: none/.test(cssCollapsed),
    'Print CSS hides #root (the live app) inside @media print'
  );
  assert(
    /html\.printing\s+#print-portal/.test(indexCss),
    'Print CSS reveals #print-portal inside @media print'
  );

  const modalSrc = fs.readFileSync(path.join(__dirname, '../components/PrintExportModal.tsx'), 'utf8');
  assert(
    /getElementById\(['"]print-portal['"]\)/.test(modalSrc) &&
      /classList\.add\(['"]printing['"]\)/.test(modalSrc),
    'Print modal writes into #print-portal and toggles the printing class'
  );
  assert(
    /classList\.remove\(['"]printing['"]\)/.test(modalSrc),
    'Print modal cleans up the printing class after printing (restore path)'
  );

  console.log(`\n  Formatting tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}

/**
 * Regression tests for two real bugs found via a screenshot of the live app:
 *   1. "Dear extra.pdf," -- a raw uploaded filename leaked into a
 *      client-facing letter greeting because clientName fell back to
 *      req.file.originalname when extraction found no name.
 *   2. Literal "()" in letter prose -- when schedulesApplied was empty,
 *      `arr.join(', ')` produced an empty string that still got wrapped in
 *      parentheses in the sentence template.
 */
export async function runGreetingRegressionTests() {
  console.log('\n--- Greeting & Schedule-List Regression Tests ---');
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

  const { getGreetingName, formatScheduleList } = await import('../utils/greeting');

  // --- Bug 1: filename-shaped names never produce a filename greeting ---
  assert(getGreetingName('extra.pdf') === 'Valued Client', 'getGreetingName rejects a raw filename ("extra.pdf" -> "Valued Client")');
  assert(
    getGreetingName('Playpower Labs Assignment_Airbnb-Clone App.pdf') === 'Valued Client',
    'getGreetingName rejects a long filename with an extension'
  );
  assert(getGreetingName('Unidentified Client') === 'Valued Client', 'getGreetingName normalizes the "Unidentified Client" placeholder');
  assert(getGreetingName('Extracted Client Document') === 'Valued Client', 'getGreetingName normalizes the "Extracted Client Document" placeholder');
  assert(getGreetingName('') === 'Valued Client', 'getGreetingName handles an empty string');
  assert(getGreetingName(null) === 'Valued Client', 'getGreetingName handles null');
  assert(getGreetingName(undefined) === 'Valued Client', 'getGreetingName handles undefined');
  assert(getGreetingName('Alex Rivera') === 'Alex', 'getGreetingName extracts a real first name from a normal full name');
  assert(getGreetingName('Marcus') === 'Marcus', 'getGreetingName passes through a normal single first name');

  // --- Bug 2: empty schedule lists never produce a literal "()" ---
  assert(formatScheduleList([]) === '', 'formatScheduleList returns empty string (not parens) for an empty array');
  assert(formatScheduleList(undefined) === '', 'formatScheduleList handles undefined safely');
  assert(formatScheduleList(null) === '', 'formatScheduleList handles null safely');
  assert(formatScheduleList(['Schedule C', 'Schedule SE']) === 'Schedule C, Schedule SE', 'formatScheduleList joins a real schedule list correctly');

  // --- End-to-end: build a client with no name and no schedules (exactly
  // the "extra.pdf" scenario) and confirm the generated letter contains
  // neither bug.
  const { generateClientLawAnalysis } = await import('../services/taxLawAnalyzer');
  const noDataClient: TaxReturnData = {
    clientId: 'regression-test',
    clientName: 'Unidentified Client',
    ssnEinLast4: '0000',
    segment: 'individual' as any,
    taxYear: 2024,
    filingStatus: 'Single',
    income: {},
    schedulesApplied: [],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: [],
    priorYearFormSources: [],
    sourceFileName: 'extra.pdf'
  };

  const letter = generateClientLawAnalysis(noDataClient);
  assert(letter.greeting === 'Dear Valued Client,', `Full letter greeting is professional, not a filename (got: "${letter.greeting}")`);
  assert(!letter.overview.includes('()'), `Letter overview has no literal empty "()" (overview: "${letter.overview}")`);
  assert(
    !letter.personalizedLawParagraphs.some((p) => p.relevanceReason.includes('()')),
    'No personalized law paragraph contains a literal empty "()"'
  );

  console.log(`\n  Greeting regression tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}

/**
 * Regression test for a real bug found via screenshot review: the K-1
 * checklist item in the organizer always cited "Schedule E, Part II" as its
 * grounding source, even for clients (like a Schedule C sole-proprietor)
 * who never actually filed Schedule E. That's a false grounding claim --
 * exactly the kind of thing the task's own "never bluffs" / "every claim
 * traces to the exact place in the sources it came from" requirement exists
 * to prevent.
 */
export async function runCitationGroundingTests() {
  console.log('\n--- Citation Grounding Tests (Schedule E false-citation regression) ---');
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

  const { buildClientSpecificOrganizer } = await import('../services/organizerGenerator');

  // Case A: Schedule C sole-proprietor (no Schedule E on file) with an
  // entity involved -- exactly the Priya Sharma scenario from the screenshot.
  // Should NOT cite Schedule E, since that schedule was never filed.
  const scheduleCClient: TaxReturnData = {
    clientId: 'citation-test-1',
    clientName: 'Schedule C Test Client',
    ssnEinLast4: '0000',
    segment: 'business',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { businessNetProfit: 245000 },
    schedulesApplied: ['Schedule C', 'Schedule SE', 'Form 4562', 'Form 8995'],
    deductionsClaimed: { standardOrItemized: 'standard', section179Depreciation: 38000 },
    entitiesInvolved: ['Test Consulting LLC'],
    priorYearFormSources: []
  };

  const organizerC = buildClientSpecificOrganizer(scheduleCClient);
  const k1DocC = organizerC
    .flatMap((sec) => sec.requiredDocuments)
    .find((d) => d.docName.includes('K-1'));

  assert(!!k1DocC, 'Organizer includes a K-1 checklist item when entitiesInvolved is non-empty');
  assert(
    (k1DocC?.sourceCitation ?? '') !== 'Schedule E, Part II',
    `K-1 item does NOT falsely cite "Schedule E, Part II" for a Schedule-C-only client (got: "${k1DocC?.sourceCitation}")`
  );
  assert(
    (k1DocC?.sourceCitation ?? '').toLowerCase().includes('confirm') || (k1DocC?.sourceCitation ?? '').toLowerCase().includes('no schedule e'),
    'K-1 citation is honest about the missing Schedule E rather than silently substituting something else'
  );

  // Case B: a genuine pass-through client who DOES have Schedule E on file --
  // citing Schedule E here is correct and should still happen.
  const scheduleEClient: TaxReturnData = {
    ...scheduleCClient,
    clientId: 'citation-test-2',
    schedulesApplied: ['Schedule E', 'Form 1120-S', 'Form 4562']
  };
  const organizerE = buildClientSpecificOrganizer(scheduleEClient);
  const k1DocE = organizerE
    .flatMap((sec) => sec.requiredDocuments)
    .find((d) => d.docName.includes('K-1'));

  assert(
    k1DocE?.sourceCitation === 'Schedule E, Part II',
    `K-1 item correctly cites "Schedule E, Part II" when the client actually has Schedule E on file (got: "${k1DocE?.sourceCitation}")`
  );

  // Case C: no entities at all -- the K-1 line shouldn't appear at all
  // (previously it always appeared, even with a fabricated "(LLC/S-Corp)"
  // placeholder when entitiesInvolved was empty).
  const noEntityClient: TaxReturnData = {
    ...scheduleCClient,
    clientId: 'citation-test-3',
    entitiesInvolved: []
  };
  const organizerNoEntity = buildClientSpecificOrganizer(noEntityClient);
  const k1DocNone = organizerNoEntity
    .flatMap((sec) => sec.requiredDocuments)
    .find((d) => d.docName.includes('K-1'));

  assert(!k1DocNone, 'Organizer does NOT include a K-1 checklist item when the client has no entities at all');

  // --- Second instance of the same bug class, found in the Diff Gate ---
  // (visible in a screenshot: the "Organizer - Pre-filled Income & Deduction
  // Checklist" modification diff cited "Prior Year Form 1040, Schedule C / E
  // / 2555" for EVERY client, even one who only ever filed Schedule C -- a
  // false claim that Schedule E and Form 2555 were on file.
  const { generateInitialSuperDocsDiffs } = await import('../data/sampleClients');
  const { buildClientSpecificOrganizer: buildOrg2 } = await import('../services/organizerGenerator');
  const { generateClientLawAnalysis: genLetter2 } = await import('../services/taxLawAnalyzer');

  const scheduleCOnlyClient: TaxReturnData = {
    clientId: 'citation-test-4',
    clientName: 'Priya Sharma',
    ssnEinLast4: '3220',
    segment: 'business',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { businessNetProfit: 245000 },
    schedulesApplied: ['Schedule C', 'Schedule SE', 'Form 4562', 'Form 8995'],
    deductionsClaimed: { standardOrItemized: 'standard', section179Depreciation: 38000, qbiDeduction: 49000 },
    entitiesInvolved: ['Sharma Consulting Group LLC'],
    priorYearFormSources: [{ field: 'Net Profit', value: '$245,000', sourceLine: 'Schedule C, Line 31' }]
  };

  const org = buildOrg2(scheduleCOnlyClient);
  const letter = genLetter2(scheduleCOnlyClient);
  const diffs = generateInitialSuperDocsDiffs(scheduleCOnlyClient, org, letter);
  const organizerDiff = diffs.find((d) => d.locationLabel.includes('Pre-filled Income & Deduction Checklist'));

  assert(!!organizerDiff, 'Diff Gate includes the organizer pre-fill modification diff');
  assert(
    !(organizerDiff?.citation.includes('Schedule E') ?? false),
    `Diff Gate citation does NOT falsely claim Schedule E for a Schedule-C-only client (got: "${organizerDiff?.citation}")`
  );
  assert(
    !(organizerDiff?.citation.includes('2555') ?? false),
    `Diff Gate citation does NOT falsely claim Form 2555 for a client who never filed it (got: "${organizerDiff?.citation}")`
  );
  assert(
    (organizerDiff?.citation.includes('Schedule C') ?? false),
    `Diff Gate citation correctly reflects the client's actual filed schedule (got: "${organizerDiff?.citation}")`
  );

  // --- Fabricated-number bugs: rental mortgage interest & expatriate figures ---
  // Verified against a real test file (sample-2-rental-property.txt, mortgage
  // interest $22,300) that the app showed a hardcoded "$18,400" regardless.
  // Similarly "348 Days Abroad" and a specific-sounding FBAR balance claim
  // were hardcoded for every expatriate client with no underlying data field.
  const rentalClientWithRealMortgage: TaxReturnData = {
    clientId: 'fabrication-test-1',
    clientName: 'Elena Rostova',
    ssnEinLast4: '0000',
    segment: 'rental',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { rentalNetIncome: 87500 },
    schedulesApplied: ['Schedule E', 'Form 4562', 'Schedule A'],
    deductionsClaimed: { standardOrItemized: 'itemized', mortgageInterest: 22300 },
    entitiesInvolved: ['Oakridge Properties LLC'],
    priorYearFormSources: []
  };
  const rentalOrg = buildOrg2(rentalClientWithRealMortgage);
  const mortgageDoc = rentalOrg.flatMap((s) => s.requiredDocuments).find((d) => d.docName.includes('Mortgage Interest'));
  assert(!!mortgageDoc, 'Organizer includes the rental mortgage interest checklist item');
  assert(
    (mortgageDoc?.priorYearValue.includes('22,300') ?? false),
    `Rental mortgage interest shows the client's REAL extracted figure ($22,300), not a hardcoded placeholder (got: "${mortgageDoc?.priorYearValue}")`
  );
  assert(
    !(mortgageDoc?.priorYearValue.includes('18,400') ?? false),
    'Rental mortgage interest does NOT show the old hardcoded "$18,400" fabricated value'
  );

  // A rental client where mortgage interest genuinely wasn't extracted should
  // say so honestly, not invent a number.
  const rentalClientNoMortgageData: TaxReturnData = {
    ...rentalClientWithRealMortgage,
    clientId: 'fabrication-test-2',
    deductionsClaimed: { standardOrItemized: 'itemized' }
  };
  const rentalOrgNoData = buildOrg2(rentalClientNoMortgageData);
  const mortgageDocNoData = rentalOrgNoData.flatMap((s) => s.requiredDocuments).find((d) => d.docName.includes('Mortgage Interest'));
  assert(
    !(mortgageDocNoData?.priorYearValue.includes('18,400') ?? false) && !(/^\$[\d,]+/.test(mortgageDocNoData?.priorYearValue ?? '')),
    `Rental mortgage interest is honest about missing data rather than inventing a dollar figure (got: "${mortgageDocNoData?.priorYearValue}")`
  );

  const expatClient: TaxReturnData = {
    clientId: 'fabrication-test-3',
    clientName: 'David Chen',
    ssnEinLast4: '0000',
    segment: 'expatriate',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { foreignEarnedIncome: 118000 },
    schedulesApplied: ['Form 2555', 'FinCEN Form 114'],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: [],
    priorYearFormSources: []
  };
  const expatOrg = buildOrg2(expatClient);
  const travelDoc = expatOrg.flatMap((s) => s.requiredDocuments).find((d) => d.docName.includes('Physical Presence'));
  assert(
    !(travelDoc?.priorYearValue.includes('348') ?? false),
    `Expatriate physical-presence item does NOT show the old fabricated "348 Days Abroad" (got: "${travelDoc?.priorYearValue}")`
  );

  // --- Fourth instance of the same bug class: a static per-letter footer in
  // YearEndLetterView.tsx claimed "Verified against 2024 Form 1040 &
  // Schedule C/E/2555 filings" on EVERY client's letter, regardless of
  // which schedules that specific client actually filed. Found via a live
  // screenshot after the earlier citation fixes were already verified
  // working. This project has no React component-test harness, so this is a
  // source-scan guard (same pattern as the currency-formatting regression
  // test) rather than a rendered-output test.
  const letterViewPath = path.join(__dirname, '..', 'components', 'YearEndLetterView.tsx');
  if (fs.existsSync(letterViewPath)) {
    const letterViewSource = fs.readFileSync(letterViewPath, 'utf-8');
    assert(
      !letterViewSource.includes('Schedule C/E/2555'),
      'YearEndLetterView.tsx footer no longer hardcodes "Schedule C/E/2555" for every client'
    );
    assert(
      letterViewSource.includes('schedulesApplied'),
      'YearEndLetterView.tsx footer is derived from the client\'s actual schedulesApplied'
    );
  }

  // --- Random SSN/EIN bug: the same uploaded file produced a DIFFERENT
  // fake SSN/EIN every time, verified directly across multiple screenshots
  // of the identical sample-1-business-scorp.txt file ("**-3220" vs
  // "**-9572" vs "**-2412"). Source-scan guard since this lives in
  // server.ts's upload handler, not a directly-importable pure function.
  const serverPath = path.join(__dirname, '..', '..', 'server.ts');
  if (fs.existsSync(serverPath)) {
    const serverSource = fs.readFileSync(serverPath, 'utf-8');
    assert(
      !serverSource.includes('ssnEinLast4: String(Math.floor'),
      'server.ts no longer generates a random, changes-every-upload fake SSN/EIN'
    );
  }

  // --- Fabricated "received" compliance documents: Photo ID and Direct
  // Deposit previously claimed status: 'received' with fake filenames and a
  // fake date for EVERY client, even one who uploaded nothing but their
  // prior return. The direct deposit item also reused the (also-fabricated)
  // random ssnEinLast4 as if it were a real bank account number.
  const complianceTestClient: TaxReturnData = {
    clientId: 'compliance-fabrication-test',
    clientName: 'Compliance Test Client',
    ssnEinLast4: 'N/A',
    segment: 'individual' as any,
    taxYear: 2024,
    filingStatus: 'Single',
    income: { w2Wages: 80000 },
    schedulesApplied: ['Form 1040'],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: [],
    priorYearFormSources: []
  };
  const complianceOrg = buildOrg2(complianceTestClient);
  const complianceSection = complianceOrg.find((s) => s.sectionTitle.includes('General Compliance'));
  const photoIdDoc = complianceSection?.requiredDocuments.find((d) => d.docName.includes('Photo ID'));
  const directDepositDoc = complianceSection?.requiredDocuments.find((d) => d.docName.includes('Direct Deposit'));

  assert(
    photoIdDoc?.status === 'outstanding',
    `Photo ID is NOT falsely marked "received" for a client who never uploaded one (got status: "${photoIdDoc?.status}")`
  );
  assert(
    !photoIdDoc?.receivedFileName,
    'Photo ID does NOT have a fabricated received filename when nothing was actually received'
  );
  assert(
    directDepositDoc?.status === 'outstanding',
    `Direct deposit info is NOT falsely marked "received" for a client who never provided it (got status: "${directDepositDoc?.status}")`
  );
  assert(
    !(directDepositDoc?.priorYearValue.includes('N/A') && directDepositDoc?.priorYearValue.includes('Ending in')),
    'Direct deposit value does NOT reuse the fabricated SSN/EIN placeholder as a fake bank account number'
  );

  const newEntityQuestion = complianceOrg
    .find((s) => s.sectionTitle.includes('Income'))
    ?.questions?.find((q) => q.id === 'q-income-changes');
  assert(
    newEntityQuestion?.priorYearAnswer !== 'No new entities reported in 2024',
    `New-entities question is honest that it's unverified rather than asserting a specific answer (got: "${newEntityQuestion?.priorYearAnswer}")`
  );

  // --- QBI "Estimated Impact" text bug: found via a live screenshot of a
  // rental-only client (Elena Rostova, zero Schedule C/S-Corp income). The
  // QBI law targets business, rental, AND hnw segments, but its impact text
  // unconditionally said "Your Schedule C / S-Corp pass-through profit
  // qualifies..." -- factually wrong for a client whose only income is
  // Schedule E rental profit, which qualifies for QBI through a completely
  // different mechanism (the rental real estate safe harbor).
  const rentalOnlyClient: TaxReturnData = {
    clientId: 'qbi-impact-test',
    clientName: 'Elena Rostova',
    ssnEinLast4: 'N/A',
    segment: 'rental',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { rentalNetIncome: 87500 }, // no businessNetProfit at all
    schedulesApplied: ['Schedule E', 'Form 4562', 'Schedule A'],
    deductionsClaimed: { standardOrItemized: 'itemized', section179Depreciation: 12000, mortgageInterest: 22300 },
    entitiesInvolved: ['Oakridge Properties LLC'],
    priorYearFormSources: []
  };
  const rentalLetter = genLetter2(rentalOnlyClient);
  const qbiParagraph = rentalLetter.personalizedLawParagraphs.find((p) => p.lawTitle.includes('§199A'));
  assert(!!qbiParagraph, 'A rental-only client still gets the QBI paragraph (rental is a valid targetSegment)');
  assert(
    !(qbiParagraph?.estimatedImpact.includes('Your Schedule C / S-Corp pass-through profit qualifies') ?? false),
    `QBI impact text does NOT falsely claim "Your Schedule C / S-Corp pass-through profit qualifies" for a rental-only client with zero Schedule C income (got: "${qbiParagraph?.estimatedImpact}")`
  );
  assert(
    (qbiParagraph?.estimatedImpact.toLowerCase().includes('rental') ?? false),
    `QBI impact text correctly describes the rental real estate qualifying path instead (got: "${qbiParagraph?.estimatedImpact}")`
  );

  // A genuine business client (Schedule C profit) should still get the
  // original Schedule C / S-Corp framing -- this fix must not break the
  // case that was already correct.
  const businessOnlyClient: TaxReturnData = {
    ...rentalOnlyClient,
    clientId: 'qbi-impact-test-2',
    segment: 'business',
    income: { businessNetProfit: 245000 },
    schedulesApplied: ['Schedule C', 'Schedule SE', 'Form 4562', 'Form 8995']
  };
  const businessLetter = genLetter2(businessOnlyClient);
  const qbiParagraphBiz = businessLetter.personalizedLawParagraphs.find((p) => p.lawTitle.includes('§199A'));
  assert(
    (qbiParagraphBiz?.estimatedImpact.includes('Schedule C / S-Corp') ?? false),
    `QBI impact text still correctly shows "Schedule C / S-Corp" framing for a genuine business client (got: "${qbiParagraphBiz?.estimatedImpact}")`
  );

  // --- FBAR overclaim: static text said "We pre-list your known foreign
  // bank account numbers" -- a capability the app never actually has
  // anywhere (no bank account number field exists in the data model at all).
  const { CURRENT_TAX_LAW_UPDATES } = await import('../data/taxLawUpdates');
  const fbarLaw = CURRENT_TAX_LAW_UPDATES.find((l) => l.id === 'law-fbar-fatca');
  assert(
    !(fbarLaw?.impactExplanation.includes('pre-list your known') ?? false),
    'FBAR law text no longer claims to pre-list account numbers the app never actually collects'
  );

  // --- Segment-only law matching bug: laws were shown to EVERY client in a
  // targeted segment, even a broad catch-all segment like 'hnw', regardless
  // of whether that client's actual data supported the law's claim. This
  // was CONFIRMED LIVE in the app's own built-in demo data: 'Dr. Robert &
  // Sarah Chen' (hnw, zero rental income, zero foreign income) was shown
  // both the rental passive-activity-loss law (falsely asserting "Because
  // you report rental income on Schedule E...") and the FBAR law, purely
  // because 'hnw' is in both laws' targetSegments. Reconstructed with the
  // client's exact real data below.
  const { INITIAL_SAMPLE_TAX_RETURNS } = await import('../data/sampleClients');
  const hnwDemoClient = INITIAL_SAMPLE_TAX_RETURNS.find((c) => c.clientName?.includes('Chen'));

  // Fall back to a hand-built reconstruction if the demo client ever gets
  // renamed/removed -- this keeps the test resilient while still covering
  // the real scenario (hnw, business income only, no rental/foreign income).
  const drChenLikeClient: TaxReturnData = hnwDemoClient || {
    clientId: 'hnw-segment-test',
    clientName: 'Dr. Robert & Sarah Chen',
    ssnEinLast4: '7729',
    segment: 'hnw',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { w2Wages: 320000, businessNetProfit: 180000, interestDividends: 45000, capitalGains: 92000 },
    schedulesApplied: ['Form 1040', 'Schedule B', 'Schedule D', 'Schedule E (K-1 Pass-through)', 'Schedule A', 'Form 8995-A'],
    deductionsClaimed: { standardOrItemized: 'itemized', saltDeduction: 10000, mortgageInterest: 29500, charitableContributions: 25000, qbiDeduction: 36000 },
    entitiesInvolved: ['Chen Medical LLC (K-1)', 'Biotech Growth Fund LP (K-1)'],
    priorYearFormSources: []
  };

  const hnwLetter = genLetter2(drChenLikeClient);
  const hasRentalParagraph = hnwLetter.personalizedLawParagraphs.some((p) => p.lawTitle.includes('§469'));
  const hasFbarParagraph = hnwLetter.personalizedLawParagraphs.some((p) => p.lawTitle.includes('FinCEN') || p.lawTitle.includes('8938') || p.relevanceReason.toLowerCase().includes('fbar'));
  const hasQbiParagraph = hnwLetter.personalizedLawParagraphs.some((p) => p.lawTitle.includes('§199A'));

  assert(
    !hasRentalParagraph,
    'HNW client with ZERO rental income does NOT get the rental passive-activity-loss law (previously shown via segment alone)'
  );
  assert(
    !hasFbarParagraph,
    'HNW client with ZERO foreign income does NOT get the FBAR law (previously shown via segment alone)'
  );
  assert(
    hasQbiParagraph,
    'HNW client WITH real business income still correctly gets the QBI law (data-based gate does not remove genuinely-applicable laws)'
  );

  // Sanity check the inverse: an HNW client who DOES have rental/foreign
  // income should still get those paragraphs -- the fix must not become
  // overly restrictive.
  const hnwWithRentalAndForeign: TaxReturnData = {
    ...drChenLikeClient,
    clientId: 'hnw-segment-test-2',
    income: { ...drChenLikeClient.income, rentalNetIncome: 40000, foreignEarnedIncome: 60000 }
  };
  const hnwLetter2 = genLetter2(hnwWithRentalAndForeign);
  assert(
    hnwLetter2.personalizedLawParagraphs.some((p) => p.lawTitle.includes('§469')),
    'HNW client who DOES have real rental income still correctly gets the rental law'
  );
  assert(
    hnwLetter2.personalizedLawParagraphs.some((p) => p.lawTitle.includes('FinCEN') || p.lawTitle.includes('8938')),
    'HNW client who DOES have real foreign income still correctly gets the FBAR law'
  );

  // --- Inconsistent "received" status: the rental income checklist item was
  // the only income document in its section marked 'received' with a
  // fabricated filename/date, while every sibling item (W-2, business,
  // foreign, interest/dividends, capital gains) correctly said 'outstanding'.
  const rentalIncomeCheck: TaxReturnData = {
    clientId: 'rental-income-status-test',
    clientName: 'Elena Rostova',
    ssnEinLast4: 'N/A',
    segment: 'rental',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { rentalNetIncome: 87500 },
    schedulesApplied: ['Schedule E', 'Form 4562', 'Schedule A'],
    deductionsClaimed: { standardOrItemized: 'itemized', mortgageInterest: 22300 },
    entitiesInvolved: ['Oakridge Properties LLC'],
    priorYearFormSources: []
  };
  const rentalIncomeOrg = buildOrg2(rentalIncomeCheck);
  const rentalIncomeDoc = rentalIncomeOrg
    .find((s) => s.sectionTitle.includes('Income'))
    ?.requiredDocuments.find((d) => d.docName.includes('Rental Income'));
  assert(
    rentalIncomeDoc?.status === 'outstanding',
    `Rental income statement is NOT falsely marked "received" (got status: "${rentalIncomeDoc?.status}")`
  );
  assert(
    !rentalIncomeDoc?.receivedFileName,
    'Rental income statement has no fabricated received filename'
  );

  // --- Form 1116 fabricated answer: same bug class, found in the same
  // expatriate section as the day-count/FBAR-balance fixes, but missed on
  // that earlier pass because it lives in the section's `questions` array
  // rather than `requiredDocuments`. Presented "Form 1116 Foreign Tax
  // Credit Claimed" as a confirmed prior-year fact for every expatriate
  // client, with no underlying data field to ground it in.
  const expatClientForm1116Check: TaxReturnData = {
    clientId: 'form1116-test',
    clientName: 'David Chen',
    ssnEinLast4: 'N/A',
    segment: 'expatriate',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { foreignEarnedIncome: 118000 },
    schedulesApplied: ['Form 2555', 'FinCEN Form 114 (FBAR)', 'Form 8938'],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: [],
    priorYearFormSources: []
  };
  const expatOrgForm1116 = buildOrg2(expatClientForm1116Check);
  const foreignTaxQuestion = expatOrgForm1116
    .find((s) => s.sectionTitle.includes('Foreign Earned Income'))
    ?.questions?.find((q) => q.id === 'q-foreign-tax-paid');
  assert(
    foreignTaxQuestion?.priorYearAnswer !== 'Form 1116 Foreign Tax Credit Claimed',
    `Foreign tax credit question is honest that it's unverified rather than asserting a specific claimed answer (got: "${foreignTaxQuestion?.priorYearAnswer}")`
  );

  // --- Itemized deductions gap: found via a synthetic end-to-end test of
  // the individual/W-2 segment (not a screenshot). The "Standard Deduction
  // vs. Itemized SALT Limit" law paragraph's Required Action Item explicitly
  // asks for "Form 1098 Mortgage Interest, property tax statements, and
  // charitable donation receipts" -- but the organizer checklist had no
  // corresponding line items for a non-rental client, meaning the letter
  // promised to collect documents the checklist never actually tracked.
  const individualItemizedClient: TaxReturnData = {
    clientId: 'itemized-gap-test',
    clientName: 'Marcus Webb',
    ssnEinLast4: 'N/A',
    segment: 'individual',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { w2Wages: 142000 },
    schedulesApplied: ['Schedule A', 'Form 1040'],
    deductionsClaimed: { standardOrItemized: 'itemized', mortgageInterest: 18500, saltDeduction: 10000 },
    entitiesInvolved: [],
    priorYearFormSources: []
  };
  const itemizedOrg = buildOrg2(individualItemizedClient);
  const itemizedSection = itemizedOrg.find((s) => s.sectionTitle.includes('Itemized Deductions'));
  const mortgageDoc2 = itemizedSection?.requiredDocuments.find((d) => d.docName.includes('Mortgage Interest'));
  const saltDoc = itemizedSection?.requiredDocuments.find((d) => d.docName.includes('SALT'));

  assert(!!itemizedSection, 'An individual client with itemized deductions gets an Itemized Deductions section');
  assert(
    (mortgageDoc2?.priorYearValue.includes('18,500') ?? false),
    `Itemized mortgage interest shows the client's real figure (got: "${mortgageDoc2?.priorYearValue}")`
  );
  assert(
    (saltDoc?.priorYearValue.includes('10,000') ?? false),
    `Itemized SALT shows the client's real figure (got: "${saltDoc?.priorYearValue}")`
  );

  // --- Fallback: Gemini sometimes puts mortgage/SALT only in the loose
  // priorYearFormSources list, NOT the structured deductionsClaimed fields.
  // The itemized section must still render in that case (observed live: the
  // section silently vanished for Marcus Webb on a run where the model chose
  // the loose list).
  const itemizedFromSourcesClient: TaxReturnData = {
    clientId: 'itemized-fallback-test',
    clientName: 'Marcus Webb',
    ssnEinLast4: 'N/A',
    segment: 'individual',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { w2Wages: 142000 },
    schedulesApplied: ['Schedule A', 'Form 1040'],
    // structured deduction fields are EMPTY -- data only lives in sources:
    deductionsClaimed: { standardOrItemized: 'itemized' },
    entitiesInvolved: [],
    priorYearFormSources: [
      { field: 'Mortgage Interest Deduction', value: '$18,500', sourceLine: 'Schedule A, Line 8a' },
      { field: 'SALT / Property Tax', value: '$10,000', sourceLine: 'Schedule A, Line 5e' }
    ]
  };
  const fallbackOrg = buildOrg2(itemizedFromSourcesClient);
  const fallbackSection = fallbackOrg.find((s) => s.sectionTitle.includes('Itemized Deductions'));
  assert(
    !!fallbackSection,
    'Itemized Deductions section still renders when the data is only in priorYearFormSources, not the structured fields'
  );
  const fallbackMortgage = fallbackSection?.requiredDocuments.find((d) => d.docName.includes('Mortgage Interest'));
  assert(
    (fallbackMortgage?.priorYearValue.includes('18,500') ?? false),
    `Fallback picks up the real mortgage figure from priorYearFormSources (got: "${fallbackMortgage?.priorYearValue}")`
  );

  // --- Itemized but NO figures captured anywhere: still surface a generic
  // itemized-support prompt so the section never silently disappears.
  const itemizedNoFiguresClient: TaxReturnData = {
    clientId: 'itemized-nofigures-test',
    clientName: 'Test Client',
    ssnEinLast4: 'N/A',
    segment: 'individual',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { w2Wages: 90000 },
    schedulesApplied: ['Schedule A', 'Form 1040'],
    deductionsClaimed: { standardOrItemized: 'itemized' },
    entitiesInvolved: [],
    priorYearFormSources: [] // nothing captured anywhere
  };
  const noFiguresOrg = buildOrg2(itemizedNoFiguresClient);
  const noFiguresSection = noFiguresOrg.find((s) => s.sectionTitle.includes('Itemized Deductions'));
  assert(
    !!noFiguresSection,
    'Itemized client with no captured figures still gets an Itemized Deductions section (generic prompt), not a silent gap'
  );
  assert(
    (noFiguresSection?.requiredDocuments[0]?.priorYearValue.toLowerCase().includes('not extracted') ?? false),
    'Generic itemized prompt is honest that specific figures were not extracted'
  );

  // --- Schedule A filer whose deduction fields Gemini left entirely empty:
  // observed live with Marcus Webb, who clearly filed Schedule A but got NO
  // Itemized Deductions section because the trigger only checked
  // standardOrItemized/figures, both empty that run. Filing Schedule A is
  // definitionally itemizing, so the section must render regardless.
  const scheduleAFilerNoData: TaxReturnData = {
    clientId: 'schedule-a-trigger-test',
    clientName: 'Marcus Webb',
    ssnEinLast4: 'N/A',
    segment: 'individual',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { w2Wages: 142000 },
    schedulesApplied: ['Schedule A', 'Form 1040'],
    deductionsClaimed: {} as any, // Gemini populated nothing this run
    entitiesInvolved: [],
    priorYearFormSources: []
  };
  const scheduleAOrg = buildOrg2(scheduleAFilerNoData);
  const scheduleASection = scheduleAOrg.find((s) => s.sectionTitle.includes('Itemized Deductions'));
  assert(
    !!scheduleASection,
    'A Schedule A filer ALWAYS gets an Itemized Deductions section, even when Gemini populated no deduction fields (definitional: Schedule A = itemized)'
  );

  // Case-variant of standardOrItemized ("Itemized" capitalized) should also trigger.
  const capitalizedItemized: TaxReturnData = {
    ...scheduleAFilerNoData,
    clientId: 'capitalized-itemized-test',
    schedulesApplied: ['Form 1040'], // no Schedule A, rely on the flag
    deductionsClaimed: { standardOrItemized: 'Itemized' } as any
  };
  const capOrg = buildOrg2(capitalizedItemized);
  assert(
    !!capOrg.find((s) => s.sectionTitle.includes('Itemized Deductions')),
    'A capitalized "Itemized" standardOrItemized value still triggers the section (case-tolerant)'
  );

  // A rental client's personal mortgage interest should NOT be duplicated
  // between the rental section and the itemized-deductions section -- both
  // read from the same deductionsClaimed.mortgageInterest field.
  const rentalDedupClient: TaxReturnData = {
    clientId: 'rental-dedup-test',
    clientName: 'Elena Rostova',
    ssnEinLast4: 'N/A',
    segment: 'rental',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: { rentalNetIncome: 87500 },
    schedulesApplied: ['Schedule E', 'Form 4562', 'Schedule A'],
    deductionsClaimed: { standardOrItemized: 'itemized', mortgageInterest: 22300 },
    entitiesInvolved: ['Oakridge Properties LLC'],
    priorYearFormSources: []
  };
  const rentalDedupOrg = buildOrg2(rentalDedupClient);
  const allMortgageDocs = rentalDedupOrg.flatMap((s) => s.requiredDocuments).filter((d) => d.docName.toLowerCase().includes('mortgage'));
  assert(
    allMortgageDocs.length === 1,
    `Rental client's mortgage interest appears exactly once, not duplicated across sections (found ${allMortgageDocs.length})`
  );

  // --- Empty-parens cosmetic bug: found via an expatriate screenshot where
  // the diff read "Includes prior year benchmark totals ()." because the
  // model returned no priorYearFormSources that run. The bare "()" looks
  // unfinished; when there are no benchmarks, the clause should be omitted.
  const { generateInitialSuperDocsDiffs: genDiffs2 } = await import('../data/sampleClients');
  const noBenchmarksClient: TaxReturnData = {
    clientId: 'empty-parens-test',
    clientName: 'David Chen',
    ssnEinLast4: 'N/A',
    segment: 'expatriate',
    taxYear: 2024,
    filingStatus: 'Single',
    income: { foreignEarnedIncome: 118000 },
    schedulesApplied: ['Form 2555', 'FinCEN Form 114 (FBAR)', 'Form 8938'],
    deductionsClaimed: { standardOrItemized: 'standard' },
    entitiesInvolved: [],
    priorYearFormSources: [] // empty -- reproduces the exact bug scenario
  };
  const noBenchOrg = buildOrg2(noBenchmarksClient);
  const noBenchLetter = genLetter2(noBenchmarksClient);
  const noBenchDiffs = genDiffs2(noBenchmarksClient, noBenchOrg, noBenchLetter);
  const prefillDiff = noBenchDiffs.find((d) => d.locationLabel.includes('Pre-filled Income & Deduction Checklist'));
  assert(
    !(prefillDiff?.proposedText.includes('()') ?? false),
    `Diff proposed text has no bare empty "()" when there are no benchmark totals (got: "${prefillDiff?.proposedText}")`
  );
  assert(
    !(prefillDiff?.proposedText.includes('benchmark totals .') ?? false),
    'Diff proposed text does not leave a dangling "benchmark totals ." fragment'
  );

  // And confirm the clause IS present when benchmarks exist.
  const withBenchmarksClient: TaxReturnData = {
    ...noBenchmarksClient,
    clientId: 'with-benchmarks-test',
    priorYearFormSources: [{ field: 'Foreign Earned Income', value: '$118,000', sourceLine: 'Form 2555, Line 19' }]
  };
  const withBenchOrg = buildOrg2(withBenchmarksClient);
  const withBenchLetter = genLetter2(withBenchmarksClient);
  const withBenchDiffs = genDiffs2(withBenchmarksClient, withBenchOrg, withBenchLetter);
  const withBenchDiff = withBenchDiffs.find((d) => d.locationLabel.includes('Pre-filled Income & Deduction Checklist'));
  assert(
    (withBenchDiff?.proposedText.includes('118,000') ?? false),
    'Diff proposed text still includes real benchmark totals when they exist'
  );

  // --- Model reasoning leaking into identity fields: found via a screenshot
  // where the letter header rendered the model's own internal validation
  // notes verbatim into the segment field ("Segment: EXPATRIATE VERA STATUS
  // LINE CHECK: EXPATRIATE/SINGLE STATUS DETECTED... NO CONTROL TOKENS.
  // PARSING CLEAN STRUCTURE. SCHEMA VALIDATED..."). The sanitizer must strip
  // this so a contaminated field falls back to a safe default instead.
  const { sanitizeShortField, sanitizeSegment } = await import('../services/geminiService');

  const leakedText = 'EXPATRIATE VERA STATUS LINE CHECK: EXPATRIATE/SINGLE STATUS DETECTED. EXPATRIATE SEGMENT SET BASED ON PHYSICAL PRESENCE TEST AND FORM 2555 USAGE. NO CONTROL TOKENS. PARSING CLEAN STRUCTURE. SINGLE OUTPUT LINE JSON. SCHEMA VALIDATED.';

  assert(
    sanitizeShortField(leakedText) === undefined,
    'sanitizeShortField rejects a long block of leaked model reasoning notes'
  );
  assert(
    sanitizeSegment(leakedText) === undefined,
    'sanitizeSegment rejects a contaminated segment value containing reasoning notes'
  );
  assert(
    sanitizeSegment('expatriate') === 'expatriate',
    'sanitizeSegment still accepts a clean valid segment value'
  );
  assert(
    sanitizeSegment('EXPATRIATE') === 'expatriate',
    'sanitizeSegment normalizes case for a clean segment value'
  );
  assert(
    sanitizeShortField('David Chen') === 'David Chen',
    'sanitizeShortField still accepts a normal short client name'
  );
  assert(
    sanitizeShortField('Sharma Consulting Group LLC', 10) === 'Sharma Consulting Group LLC',
    'sanitizeShortField accepts a normal multi-word entity name within the word limit'
  );
  assert(
    sanitizeSegment('business') === 'business' &&
    sanitizeSegment('rental') === 'rental' &&
    sanitizeSegment('individual') === 'individual' &&
    sanitizeSegment('hnw') === 'hnw',
    'sanitizeSegment accepts all valid segment values'
  );
  assert(
    sanitizeSegment('spaceship') === undefined,
    'sanitizeSegment rejects an unrecognized segment value'
  );

  console.log(`\n  Citation grounding tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}
