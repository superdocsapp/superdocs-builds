import { TaxReturnData, PreFilledOrganizerSection } from '../types';

/**
 * Builds a client-specific 2025 Tax Organizer dynamically based on prior year return data.
 * Extracts schedules, deductions, entities, rental properties, foreign income, and retirement contributions.
 */
export function buildClientSpecificOrganizer(ret: TaxReturnData): PreFilledOrganizerSection[] {
  const sections: PreFilledOrganizerSection[] = [];

  // 1. Income Statements & Tax Forms Checklist
  const incomeDocs: PreFilledOrganizerSection['requiredDocuments'] = [];
  const incomeQuestions: PreFilledOrganizerSection['questions'] = [];

  if (ret.income.w2Wages && ret.income.w2Wages > 0) {
    incomeDocs.push({
      id: 'doc-w2',
      docName: 'Form W-2 (Wage and Tax Statement)',
      priorYearValue: `$${ret.income.w2Wages.toLocaleString('en-US')} (Form 1040, Line 1a)`,
      sourceCitation: 'Form 1040, Line 1a',
      status: 'outstanding'
    });
  }

  if (ret.income.businessNetProfit && ret.income.businessNetProfit > 0) {
    incomeDocs.push({
      id: 'doc-1099nec',
      docName: 'Form 1099-NEC / 1099-K / Profit & Loss Statement',
      priorYearValue: `$${ret.income.businessNetProfit.toLocaleString('en-US')} Net Business Income`,
      sourceCitation: 'Schedule C, Line 31',
      status: 'outstanding'
    });
  }

  if (ret.income.rentalNetIncome && ret.income.rentalNetIncome > 0) {
    incomeDocs.push({
      id: 'doc-rental-stmt',
      docName: 'Schedule E Rental Income & Property Expense Records',
      priorYearValue: `$${ret.income.rentalNetIncome.toLocaleString('en-US')} Net Rental Income`,
      sourceCitation: 'Schedule E, Line 21',
      // Previously the only income item in this whole section marked
      // 'received' with a fabricated filename/date, inconsistent with every
      // sibling item here (W-2, business, foreign, interest/dividends,
      // capital gains -- all correctly 'outstanding'). Same "never bluffs"
      // violation as the Photo ID/Direct Deposit fix: nothing was actually
      // received.
      status: 'outstanding'
    });
  }

  if (ret.income.foreignEarnedIncome && ret.income.foreignEarnedIncome > 0) {
    incomeDocs.push({
      id: 'doc-foreign-wages',
      docName: 'Foreign Salary Slips & Overseas Tax Returns (Form 2555)',
      priorYearValue: `$${ret.income.foreignEarnedIncome.toLocaleString('en-US')} Foreign Earned Income`,
      sourceCitation: 'Form 2555, Line 19',
      status: 'outstanding'
    });
  }

  if (ret.income.interestDividends && ret.income.interestDividends > 0) {
    incomeDocs.push({
      id: 'doc-1099int-div',
      docName: 'Form 1099-INT / Form 1099-DIV Brokerage & Interest Statements',
      priorYearValue: `$${ret.income.interestDividends.toLocaleString('en-US')} (Schedule B)`,
      sourceCitation: 'Schedule B, Line 4',
      status: 'outstanding'
    });
  }

  if (ret.income.capitalGains && ret.income.capitalGains > 0) {
    incomeDocs.push({
      id: 'doc-1099b',
      docName: 'Form 1099-B Capital Gains & Stock Sales Statement',
      priorYearValue: `$${ret.income.capitalGains.toLocaleString('en-US')} Capital Gain`,
      sourceCitation: 'Schedule D, Line 16',
      status: 'outstanding'
    });
  }

  sections.push({
    id: 'sec-income-verification',
    sectionTitle: 'Income & Investment Records Verification',
    category: 'income',
    requiredDocuments: incomeDocs,
    questions: [
      {
        id: 'q-income-changes',
        questionText: 'Did you start any new jobs, businesses, or foreign bank accounts in 2025?',
        priorYearAnswer: 'Not stated in the source document -- please confirm',
        sourceCitation: 'Prior Year Form 1040'
      }
    ]
  });

  // 1b. Itemized Deductions (Mortgage, SALT, Charitable) -- any segment.
  //
  // Gap found via a synthetic end-to-end test of the individual/W-2 segment:
  // the "Standard Deduction vs. Itemized SALT Limit" law paragraph's Required
  // Action Item asks the client to "Provide Form 1098 Mortgage Interest,
  // property tax statements, and charitable donation receipts" -- but the
  // organizer checklist had no corresponding line items to track them.
  //
  // Hardening against Gemini non-determinism: the model is inconsistent about
  // WHERE it puts a figure -- sometimes in the structured
  // deductionsClaimed.mortgageInterest number field, sometimes only as a loose
  // entry in priorYearFormSources. If we only read the structured field, the
  // section silently disappears on runs where the model chose the loose list,
  // even though the data WAS extracted. So we fall back to scanning
  // priorYearFormSources for a matching figure, so the section renders
  // whenever the client's itemized data was captured anywhere in the output.
  const findSourceValue = (keywords: RegExp): string | undefined => {
    const hit = ret.priorYearFormSources.find(
      (s) => keywords.test(s.field) || keywords.test(String(s.sourceLine))
    );
    return hit ? String(hit.value) : undefined;
  };

  const mortgageFromSources = findSourceValue(/mortgage|1098|interest/i);
  const saltFromSources = findSourceValue(/salt|property tax|state.{0,4}local|line 5/i);
  const charitableFromSources = findSourceValue(/charit|donation|line 11/i);

  const mortgageDisplay = ret.deductionsClaimed.mortgageInterest
    ? `$${ret.deductionsClaimed.mortgageInterest.toLocaleString('en-US')} Claimed in 2024`
    : mortgageFromSources
      ? `${mortgageFromSources} (from prior return)`
      : undefined;

  const saltDisplay = ret.deductionsClaimed.saltDeduction
    ? `$${ret.deductionsClaimed.saltDeduction.toLocaleString('en-US')} Claimed in 2024 (capped at $10,000)`
    : saltFromSources
      ? `${saltFromSources} (from prior return, SALT cap $10,000 applies)`
      : undefined;

  const charitableDisplay = ret.deductionsClaimed.charitableContributions
    ? `$${ret.deductionsClaimed.charitableContributions.toLocaleString('en-US')} Claimed in 2024`
    : charitableFromSources
      ? `${charitableFromSources} (from prior return)`
      : undefined;

  // Signals that a client itemized, in order of reliability:
  //  1. schedulesApplied contains "Schedule A" -- DEFINITIONAL. If they filed
  //     Schedule A, they itemized, full stop. This is the most reliable signal
  //     and doesn't depend on Gemini populating any deduction field correctly.
  //     Observed bug: Marcus Webb had the Schedule A badge but got no itemized
  //     section because the trigger only checked standardOrItemized/figures.
  //  2. standardOrItemized === 'itemized' -- normalized to be tolerant of
  //     casing/variants ("Itemized", "itemize") the model sometimes returns.
  //  3. any specific mortgage/SALT/charitable figure was captured.
  const filedScheduleA = ret.schedulesApplied.some((s) => /schedule\s*a\b/i.test(s));
  const itemizedFlag = /itemi/i.test(String(ret.deductionsClaimed.standardOrItemized || ''));

  if (
    filedScheduleA ||
    itemizedFlag ||
    mortgageDisplay ||
    saltDisplay ||
    charitableDisplay
  ) {
    const itemizedDocs: PreFilledOrganizerSection['requiredDocuments'] = [];

    // Only add a mortgage interest line here for non-rental clients -- rental
    // clients already get their own dedicated mortgage interest item in the
    // "Rental Real Estate" section below, tied to the rental property itself.
    // Avoids asking for the same document twice under two different sections.
    if (mortgageDisplay && ret.segment !== 'rental') {
      itemizedDocs.push({
        id: 'doc-1098-personal-mortgage',
        docName: 'Form 1098 Mortgage Interest Statement (Personal Residence)',
        priorYearValue: mortgageDisplay,
        sourceCitation: 'Schedule A, Line 8a',
        status: 'outstanding'
      });
    }

    if (saltDisplay) {
      itemizedDocs.push({
        id: 'doc-salt-statements',
        docName: 'Property Tax & State/Local Income Tax Statements (SALT)',
        priorYearValue: saltDisplay,
        sourceCitation: 'Schedule A, Line 5e',
        status: 'outstanding'
      });
    }

    if (charitableDisplay) {
      itemizedDocs.push({
        id: 'doc-charitable-receipts',
        docName: 'Charitable Donation Receipts & Acknowledgment Letters',
        priorYearValue: charitableDisplay,
        sourceCitation: 'Schedule A, Line 11',
        status: 'outstanding'
      });
    }

    // If the client itemized but no specific figures were captured in either
    // the structured fields or the loose sources, still surface a generic
    // itemized-deductions prompt so the section (and the documents the letter
    // asks for) never silently vanishes.
    if (itemizedDocs.length === 0 && (filedScheduleA || itemizedFlag) && ret.segment !== 'rental') {
      itemizedDocs.push({
        id: 'doc-itemized-general',
        docName: 'Schedule A Itemized Deduction Support (Form 1098, Property Tax, Charitable Receipts)',
        priorYearValue: 'Itemized in 2024 -- specific figures not extracted, please provide supporting documents',
        sourceCitation: 'Schedule A',
        status: 'outstanding'
      });
    }

    if (itemizedDocs.length > 0) {
      sections.push({
        id: 'sec-itemized-deductions',
        sectionTitle: 'Itemized Deductions (Mortgage, SALT & Charitable)',
        category: 'deductions',
        requiredDocuments: itemizedDocs,
        questions: []
      });
    }
  }

  // 2. Business & Entity Details (S-Corps, LLCs, Section 179, QBI)
  if (ret.segment === 'business' || ret.schedulesApplied.includes('Schedule C') || ret.entitiesInvolved.length > 0) {
    const bizDocs: PreFilledOrganizerSection['requiredDocuments'] = [];
    
    if (ret.deductionsClaimed.section179Depreciation) {
      bizDocs.push({
        id: 'doc-sec179-invoices',
        docName: 'Invoices for Machinery, Computer Hardware, or Vehicles Purchased in 2025',
        priorYearValue: `$${ret.deductionsClaimed.section179Depreciation.toLocaleString('en-US')} Section 179 Claimed`,
        sourceCitation: 'Form 4562, Line 12',
        status: 'outstanding'
      });
    }

    if (ret.deductionsClaimed.homeOfficeDeduction) {
      bizDocs.push({
        id: 'doc-home-office-exp',
        docName: 'Home Office Expense Log (Utilities, Rent, Square Footage)',
        priorYearValue: 'Home Office Claimed in 2024',
        sourceCitation: 'Form 8829, Line 35',
        status: 'outstanding'
      });
    }

    // The K-1 checklist item previously always cited "Schedule E, Part II" as
    // its grounding source, regardless of what the client's actual
    // schedulesApplied contained -- e.g. a Schedule C sole-proprietor who
    // never filed Schedule E still got a "Grounded: Schedule E, Part II"
    // citation on their organizer. That's a false grounding claim, which
    // directly violates the "every claim traces to the exact place in the
    // sources it came from" requirement. Only ask for K-1s, and only cite
    // Schedule E, when the client's real schedules actually indicate a
    // pass-through entity relationship.
    const hasPassThroughSchedule = ret.schedulesApplied.some((s) =>
      /schedule e|form 1065|form 1120-s|k-1/i.test(s)
    );

    if (ret.entitiesInvolved.length > 0) {
      bizDocs.push({
        id: 'doc-k1-pass-through',
        docName: 'Schedule K-1 Statements for Business Entities (' + ret.entitiesInvolved.join(', ') + ')',
        priorYearValue: ret.entitiesInvolved.join('; '),
        sourceCitation: hasPassThroughSchedule
          ? 'Schedule E, Part II'
          : 'Entity Ownership Records (no Schedule E on file -- confirm K-1 applicability)',
        status: 'outstanding'
      });
    }

    sections.push({
      id: 'sec-business-entities',
      sectionTitle: 'Business Entities, Equipment & Section 179 Deductions',
      category: 'entities',
      requiredDocuments: bizDocs,
      questions: [
        {
          id: 'q-w2-payroll-qbi',
          questionText: 'Total employee W-2 wages paid by your entity in 2025 (Required for QBI §199A)?',
          priorYearAnswer: ret.income.w2Wages ? `$${ret.income.w2Wages.toLocaleString('en-US')}` : '$0 W-2 Wages',
          sourceCitation: 'Form 8995 QBI Worksheet'
        }
      ]
    });
  }

  // 3. Rental Properties (Schedule E, Depreciation, Property Tax)
  if (ret.segment === 'rental' || ret.schedulesApplied.includes('Schedule E (Part I - Rentals)')) {
    const mortgageInterest = ret.deductionsClaimed.mortgageInterest;
    sections.push({
      id: 'sec-rental-properties',
      sectionTitle: 'Rental Real Estate & Capital Improvements',
      category: 'deductions',
      requiredDocuments: [
        {
          id: 'doc-1098-mortgage',
          docName: 'Form 1098 Mortgage Interest & Property Tax Receipts for Rentals',
          // Previously hardcoded "$18,400 Claimed on Schedule E in 2024" for
          // EVERY rental client regardless of their real return -- verified
          // against a real test file (mortgage interest $22,300) that the
          // app would still show $18,400 for. Now uses the actual extracted
          // figure, and says so honestly when no figure was extracted rather
          // than inventing one.
          priorYearValue: mortgageInterest
            ? `$${mortgageInterest.toLocaleString('en-US')} Claimed on Schedule E in 2024`
            : 'Not extracted from prior return -- please provide 2024 Form 1098',
          sourceCitation: 'Schedule E, Line 12',
          status: mortgageInterest ? 'received' : 'outstanding',
          ...(mortgageInterest
            ? { receivedFileName: '1098_Rental_Mortgage_2025.pdf', receivedDate: new Date().toISOString().split('T')[0] }
            : {})
        },
        {
          id: 'doc-repairs-vs-improvements',
          docName: 'Itemized Repair Invoices vs Capital Property Improvements (Roof, HVAC)',
          priorYearValue: 'Schedule E Line 18 Expenses',
          sourceCitation: 'Schedule E, Line 18',
          status: 'outstanding'
        }
      ],
      questions: [
        {
          id: 'q-real-estate-prof',
          questionText: 'Did you spend 750+ hours materially participating in real estate trades/businesses?',
          priorYearAnswer: 'Real Estate Professional Status Evaluation',
          sourceCitation: 'IRC §469(c)(7) Safe Harbor'
        }
      ]
    });
  }

  // 4. Foreign Income & FBAR (Expatriate, Foreign Accounts)
  if (ret.segment === 'expatriate' || ret.schedulesApplied.includes('Form 2555 (Foreign Earned Income)')) {
    sections.push({
      id: 'sec-foreign-fbar',
      sectionTitle: 'Foreign Earned Income, Travel Log & FBAR Disclosures',
      category: 'foreign',
      requiredDocuments: [
        {
          id: 'doc-travel-physical-presence',
          docName: 'Physical Presence Day-Count Travel Log (Days in/out of USA)',
          // Previously hardcoded "348 Days Abroad in 2024" for EVERY
          // expatriate client -- TaxReturnData has no field to ground a real
          // day-count in, so rather than keep inventing a specific-sounding
          // number, this is now honest that it's a data request, not a
          // claimed prior-year fact.
          priorYearValue: 'Not extracted from prior return -- please provide 2024 travel/day-count log',
          sourceCitation: 'Form 2555, Line 18',
          status: 'outstanding'
        },
        {
          id: 'doc-fbar-bank-stmts',
          docName: 'FinCEN Form 114 (FBAR) Foreign Bank Account Highest Balance Statements',
          // Previously "Foreign Accounts Aggregate Peak > $10,000 USD" read
          // as a specific claimed fact about the client. Reworded so it's
          // unambiguously the filing threshold rule, not a claim about this
          // client's actual balances (which aren't in TaxReturnData).
          priorYearValue: 'FBAR required if aggregate foreign balances exceeded $10,000 USD at any point in 2024',
          sourceCitation: 'FinCEN Form 114 filing threshold (31 CFR 1010.350)',
          status: 'outstanding'
        }
      ],
      questions: [
        {
          id: 'q-foreign-tax-paid',
          questionText: 'Total foreign income taxes paid to local foreign government in 2025?',
          // Previously "Form 1116 Foreign Tax Credit Claimed" -- presented
          // as a confirmed prior-year fact for every expatriate client, but
          // TaxReturnData has no field for an actual foreign tax credit
          // amount, so nothing was ever really extracted here. Same bug
          // class as the two items above; missed on the earlier pass over
          // this exact section since it's in the questions array rather
          // than requiredDocuments.
          priorYearAnswer: 'Not stated in the source document -- please confirm',
          sourceCitation: 'Form 1116, Line 8'
        }
      ]
    });
  }

  // 5. General & Compliance Checklist
  //
  // Every item below previously claimed status: 'received' with a fabricated
  // filename and a fabricated date ('2025-11-01') for EVERY client,
  // unconditionally -- meaning a brand-new client who uploaded nothing but
  // their prior return would still show Photo ID and Direct Deposit info as
  // already "Verified" and "on file". That's a genuine "never bluffs"
  // violation: it claims specific documents were received when nothing of
  // the kind was ever provided. The direct deposit item additionally reused
  // the (also-fabricated) random ssnEinLast4 as if it were real bank account
  // digits. Now these honestly reflect that nothing has actually been
  // received yet, and the Q&A defaults are framed as unverified rather than
  // asserted facts.
  sections.push({
    id: 'sec-general-compliance',
    sectionTitle: 'General Compliance, Direct Deposit & Disclosures',
    category: 'documents_needed',
    requiredDocuments: [
      {
        id: 'doc-id-verification',
        docName: 'Government-Issued Photo ID (Driver License / Passport) Copy',
        priorYearValue: 'Not on file -- required for IRS e-file identity verification',
        sourceCitation: 'IRS E-file Security Compliance',
        status: 'outstanding'
      },
      {
        id: 'doc-direct-deposit-bank',
        docName: 'Voided Check or Direct Deposit Routing & Account Details',
        priorYearValue: 'Not on file',
        sourceCitation: 'Form 1040 Direct Deposit Line',
        status: 'outstanding'
      }
    ],
    questions: [
      {
        id: 'q-crypto-digital-assets',
        questionText: 'At any time during 2025, did you receive, sell, exchange, or earn digital assets (Crypto/NFTs)?',
        priorYearAnswer: 'Not stated in the source document -- please confirm',
        sourceCitation: 'Form 1040 Front Page Digital Asset Box'
      }
    ]
  });

  return sections;
}
