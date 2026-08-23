import { TaxReturnData, ClientBatchRecord, SuperDocsDiff } from '../types';
import { CURRENT_TAX_LAW_UPDATES } from './taxLawUpdates';

export const INITIAL_SAMPLE_TAX_RETURNS: TaxReturnData[] = [
  {
    clientId: 'cli-101',
    clientName: 'Apex Innovations LLC (Marcus Vance)',
    ssnEinLast4: '8831',
    segment: 'business',
    taxYear: 2024,
    filingStatus: 'Single / S-Corp Owner',
    income: {
      businessNetProfit: 245000,
      w2Wages: 85000,
      interestDividends: 3200
    },
    schedulesApplied: ['Form 1040', 'Schedule C', 'Schedule SE', 'Form 4562 (Depreciation)', 'Form 8995 (QBI)'],
    deductionsClaimed: {
      standardOrItemized: 'standard',
      section179Depreciation: 42000,
      qbiDeduction: 49000,
      homeOfficeDeduction: true
    },
    entitiesInvolved: ['Apex Innovations LLC (EIN xx-xxx8831)'],
    priorYearFormSources: [
      { field: 'Gross Business Receipts', value: '$420,000', sourceLine: 'Schedule C, Line 1' },
      { field: 'Net Business Profit', value: '$245,000', sourceLine: 'Schedule C, Line 31' },
      { field: 'Section 179 Expense Deduction', value: '$42,000', sourceLine: 'Form 4562, Line 12' },
      { field: 'QBI Deduction', value: '$49,000', sourceLine: 'Form 1040, Line 13' },
      { field: 'Officer W-2 Salary', value: '$85,000', sourceLine: 'Form 1040, Line 1a' }
    ]
  },
  {
    clientId: 'cli-102',
    clientName: 'Oakridge Properties (Elena Rostova)',
    ssnEinLast4: '4192',
    segment: 'rental',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: {
      w2Wages: 140000,
      rentalNetIncome: 68000,
      interestDividends: 1500
    },
    schedulesApplied: ['Form 1040', 'Schedule E (Part I - Rentals)', 'Form 4562 (Rental Depreciation)', 'Schedule A'],
    deductionsClaimed: {
      standardOrItemized: 'itemized',
      saltDeduction: 10000,
      mortgageInterest: 18400,
      charitableContributions: 4500
    },
    entitiesInvolved: ['142 Oakridge Dr Rental', '88 Pine St Duplex'],
    priorYearFormSources: [
      { field: 'Rents Received - Oakridge Dr', value: '$48,000', sourceLine: 'Schedule E, Line 3a' },
      { field: 'Rents Received - Pine St Duplex', value: '$52,000', sourceLine: 'Schedule E, Line 3b' },
      { field: 'Total Rental Expenses & Depreciation', value: '$32,000', sourceLine: 'Schedule E, Line 20' },
      { field: 'Net Rental Income', value: '$68,000', sourceLine: 'Schedule E, Line 21' }
    ]
  },
  {
    clientId: 'cli-103',
    clientName: 'David Sterling (Overseas Executive)',
    ssnEinLast4: '6014',
    segment: 'expatriate',
    taxYear: 2024,
    filingStatus: 'Single',
    income: {
      foreignEarnedIncome: 135000,
      interestDividends: 8900,
      capitalGains: 14200
    },
    schedulesApplied: ['Form 1040', 'Form 2555 (Foreign Earned Income)', 'Form 1116 (Foreign Tax Credit)', 'FBAR (FinCEN 114)'],
    deductionsClaimed: {
      standardOrItemized: 'standard',
      foreignTaxCredit: 8200
    },
    entitiesInvolved: ['Barclays UK Account (Ending 4402)', 'HSBC London Premier (Ending 9101)'],
    priorYearFormSources: [
      { field: 'Foreign Earned Income Excluded', value: '$120,000', sourceLine: 'Form 2555, Line 45' },
      { field: 'Foreign Housing Deduction', value: '$15,000', sourceLine: 'Form 2555, Line 50' },
      { field: 'Physical Presence Days Abroad', value: '348 Days', sourceLine: 'Form 2555, Line 18' },
      { field: 'FBAR Max Balance Aggregate', value: '$240,000 USD', sourceLine: 'FinCEN Form 114' }
    ]
  },
  {
    clientId: 'cli-104',
    clientName: 'Dr. Robert & Sarah Chen',
    ssnEinLast4: '7729',
    segment: 'hnw',
    taxYear: 2024,
    filingStatus: 'Married Filing Jointly',
    income: {
      w2Wages: 320000,
      businessNetProfit: 180000,
      interestDividends: 45000,
      capitalGains: 92000
    },
    schedulesApplied: ['Form 1040', 'Schedule B', 'Schedule D', 'Schedule E (K-1 Pass-through)', 'Schedule A', 'Form 8995-A'],
    deductionsClaimed: {
      standardOrItemized: 'itemized',
      saltDeduction: 10000,
      mortgageInterest: 29500,
      charitableContributions: 25000,
      qbiDeduction: 36000
    },
    entitiesInvolved: ['Chen Medical LLC (K-1)', 'Biotech Growth Fund LP (K-1)', 'Primary Residence Solar Upgrade'],
    priorYearFormSources: [
      { field: 'W2 Salaries Combined', value: '$320,000', sourceLine: 'Form 1040, Line 1a' },
      { field: 'Schedule D Net Capital Gain', value: '$92,000', sourceLine: 'Schedule D, Line 16' },
      { field: 'Partnership K-1 Income', value: '$180,000', sourceLine: 'Schedule E, Part II' },
      { field: 'Charitable Cash Contributions', value: '$25,000', sourceLine: 'Schedule A, Line 11' }
    ]
  },
  {
    clientId: 'cli-105',
    clientName: 'Karen Miller (Consultant & Homeowner)',
    ssnEinLast4: '1903',
    segment: 'individual',
    taxYear: 2024,
    filingStatus: 'Single',
    income: {
      w2Wages: 98000,
      interestDividends: 1200
    },
    schedulesApplied: ['Form 1040', 'Schedule A', 'Form 8863 (Education / Clean Energy)'],
    deductionsClaimed: {
      standardOrItemized: 'standard',
      energyCredits: 1200
    },
    entitiesInvolved: ['Primary Residence - Electric Vehicle Charger & Heat Pump'],
    priorYearFormSources: [
      { field: 'W2 Wage Income', value: '$98,000', sourceLine: 'Form 1040, Line 1a' },
      { field: 'Form 25C Energy Efficiency Credit', value: '$1,200', sourceLine: 'Form 5695, Line 15' }
    ]
  }
];

export function buildInitialRecord(ret: TaxReturnData): ClientBatchRecord {
  // Pre-fill organizer based strictly on prior year return
  const organizer = generatePreFilledOrganizer(ret);
  // Draft letter tailored with law updates
  const yearEndLetter = generatePersonalizedLetter(ret);
  // Create sample SuperDocs proposed diffs for human gate review
  const diffs = generateInitialSuperDocsDiffs(ret, organizer, yearEndLetter);

  const missingCount = organizer.reduce(
    (acc, sec) => acc + sec.requiredDocuments.filter((d) => d.status === 'outstanding').length,
    0
  );
  const receivedCount = organizer.reduce(
    (acc, sec) => acc + sec.requiredDocuments.filter((d) => d.status === 'received').length,
    0
  );

  return {
    id: `batch-${ret.clientId}`,
    clientId: ret.clientId,
    clientName: ret.clientName,
    segment: ret.segment,
    priorReturn: ret,
    organizer,
    yearEndLetter,
    diffs,
    missingItemsCount: missingCount,
    receivedItemsCount: receivedCount,
    status: 'diff_review',
    lastUpdated: new Date().toISOString()
  };
}

export function generatePreFilledOrganizer(ret: TaxReturnData) {
  const sections = [];

  // Section 1: Income Records Pre-fill
  sections.push({
    id: 'sec-income',
    sectionTitle: 'Income & Tax Statement Verification',
    category: 'income' as const,
    requiredDocuments: [
      ...(ret.income.w2Wages
        ? [{
            id: 'doc-w2',
            docName: 'Form W-2 (Wage and Tax Statement)',
            priorYearValue: `$${ret.income.w2Wages.toLocaleString('en-US')} (Prior Year)`,
            sourceCitation: 'Form 1040, Line 1a',
            status: 'outstanding' as const
          }]
        : []),
      ...(ret.income.businessNetProfit
        ? [{
            id: 'doc-1099nec',
            docName: 'Forms 1099-NEC / 1099-K (Self-Employment / Business Income)',
            priorYearValue: `$${ret.income.businessNetProfit.toLocaleString('en-US')} Net Profit`,
            sourceCitation: 'Schedule C, Line 31',
            status: 'outstanding' as const
          }]
        : []),
      ...(ret.income.rentalNetIncome
        ? [{
            id: 'doc-1099misc-rental',
            docName: 'Schedule E Rental Property Statements & Form 1099-MISC',
            priorYearValue: `$${ret.income.rentalNetIncome.toLocaleString('en-US')} Net Rental Profit`,
            sourceCitation: 'Schedule E, Line 21',
            status: 'received' as const,
            receivedFileName: '2025_Oakridge_Rental_Summary.pdf',
            receivedDate: '2026-01-15'
          }]
        : []),
      ...(ret.income.foreignEarnedIncome
        ? [{
            id: 'doc-foreign-income',
            docName: 'Foreign Wage Payslips & Employer Income Statements',
            priorYearValue: `$${ret.income.foreignEarnedIncome.toLocaleString('en-US')} Foreign Income`,
            sourceCitation: 'Form 2555, Line 19',
            status: 'outstanding' as const
          }]
        : []),
      ...(ret.income.interestDividends
        ? [{
            id: 'doc-1099int-div',
            docName: 'Form 1099-INT / 1099-DIV Bank & Brokerage Statements',
            priorYearValue: `$${ret.income.interestDividends.toLocaleString('en-US')} Interest/Dividends`,
            sourceCitation: 'Schedule B, Line 4',
            status: 'outstanding' as const
          }]
        : [])
    ],
    questions: [
      {
        id: 'q-bank-change',
        questionText: 'Did you open or close any bank accounts during the tax year?',
        priorYearAnswer: 'No changes reported in 2024',
        sourceCitation: 'Form 1040 Direct Deposit Line'
      }
    ]
  });

  // Section 2: Deductions & Entity Specifics
  if (ret.segment === 'business') {
    sections.push({
      id: 'sec-business-deductions',
      sectionTitle: 'Business Assets, Section 179 & Expenses',
      category: 'deductions' as const,
      requiredDocuments: [
        {
          id: 'doc-sec179-invoices',
          docName: 'Invoices for Machinery, Computer Hardware, or Equipment Purchased',
          priorYearValue: `$${ret.deductionsClaimed.section179Depreciation?.toLocaleString('en-US')} Claimed in 2024`,
          sourceCitation: 'Form 4562, Line 12',
          status: 'outstanding' as const
        },
        {
          id: 'doc-home-office',
          docName: 'Home Office Expenses (Square Footage & Utility Logs)',
          priorYearValue: ret.deductionsClaimed.homeOfficeDeduction ? 'Claimed in 2024' : 'Not Claimed',
          sourceCitation: 'Form 8829',
          status: 'outstanding' as const
        }
      ],
      questions: [
        {
          id: 'q-w2-wages-paid',
          questionText: 'Total W-2 Wages paid to employees by Apex Innovations LLC during 2025?',
          priorYearAnswer: '$85,000 W-2 Wages',
          sourceCitation: 'Form 8995 QBI Calculation'
        }
      ]
    });
  } else if (ret.segment === 'rental') {
    sections.push({
      id: 'sec-rental-details',
      sectionTitle: 'Rental Property Expenses & Capital Improvements',
      category: 'deductions' as const,
      requiredDocuments: [
        {
          id: 'doc-rental-repairs',
          docName: 'Itemized Receipts for Property Repairs vs. Capital Assets (Roof, HVAC)',
          priorYearValue: 'Claimed on Schedule E (Lines 6-18)',
          sourceCitation: 'Schedule E, Line 19',
          status: 'outstanding' as const
        },
        {
          id: 'doc-property-tax',
          docName: 'Form 1098 Mortgage Interest & County Property Tax Bills',
          priorYearValue: '$18,400 Mortgage Interest in 2024',
          sourceCitation: 'Schedule E, Line 12',
          status: 'received' as const,
          receivedFileName: '1098_Oakridge_Mortgage_2025.pdf',
          receivedDate: '2026-01-20'
        }
      ],
      questions: [
        {
          id: 'q-rental-days',
          questionText: 'Were any rental units used for personal purposes for more than 14 days?',
          priorYearAnswer: '0 Personal Days (100% Rental)',
          sourceCitation: 'Schedule E Property Questionnaire'
        }
      ]
    });
  } else if (ret.segment === 'expatriate') {
    sections.push({
      id: 'sec-expat-details',
      sectionTitle: 'Foreign Earned Income, Travel Log & FBAR Assets',
      category: 'foreign' as const,
      requiredDocuments: [
        {
          id: 'doc-travel-log',
          docName: 'Physical Presence Travel Log (Dates Entered/Exited United States)',
          priorYearValue: '348 Days Physical Presence in UK (2024)',
          sourceCitation: 'Form 2555, Line 18',
          status: 'outstanding' as const
        },
        {
          id: 'doc-fbar-statements',
          docName: 'Year-End Bank Statements showing Highest Balance for Foreign Accounts',
          priorYearValue: 'Barclays & HSBC Accounts Reported ($240k Peak)',
          sourceCitation: 'FinCEN Form 114 (FBAR)',
          status: 'outstanding' as const
        }
      ],
      questions: [
        {
          id: 'q-foreign-housing',
          questionText: 'Total foreign rent and utilities paid in foreign currency during 2025?',
          priorYearAnswer: '$15,000 USD Foreign Housing',
          sourceCitation: 'Form 2555, Part IV'
        }
      ]
    });
  }

  // General Checklist Section
  sections.push({
    id: 'sec-docs-needed',
    sectionTitle: 'General Required Client Checklist & Disclosures',
    category: 'documents_needed' as const,
    requiredDocuments: [
      {
        id: 'doc-driver-license',
        docName: 'Government Issued Photo ID / Driver License (Copy for E-Filing Security)',
        priorYearValue: 'On File',
        sourceCitation: 'IRS E-file Security Verification',
        status: 'received' as const,
        receivedFileName: 'Driver_License_Front_Back.pdf',
        receivedDate: '2025-11-02'
      },
      {
        id: 'doc-direct-deposit',
        docName: 'Voided Check or Bank Direct Deposit Account Number',
        priorYearValue: 'Ending in x8812',
        sourceCitation: 'Form 1040 Direct Deposit Line',
        status: 'received' as const,
        receivedFileName: 'Bank_Voided_Check.pdf',
        receivedDate: '2025-11-02'
      }
    ],
    questions: [
      {
        id: 'q-crypto',
        questionText: 'At any time during 2025, did you receive, sell, exchange, or transfer digital assets (cryptocurrency, NFTs)?',
        priorYearAnswer: 'Answered NO in 2024',
        sourceCitation: 'Form 1040 Front Page Digital Asset Question'
      }
    ]
  });

  return sections;
}

export function generatePersonalizedLetter(ret: TaxReturnData) {
  // Filter tax law changes relevant to this client's segment
  const applicableLaws = CURRENT_TAX_LAW_UPDATES.filter((law) =>
    law.targetSegments.includes(ret.segment)
  );

  const personalizedParagraphs = applicableLaws.map((law) => ({
    lawTitle: `${law.title} (${law.codeSection})`,
    relevanceReason: `Based on your ${ret.segment.toUpperCase()} profile and prior year return (${ret.priorYearFormSources[0]?.sourceLine || 'Form 1040'}), this update directly impacts your tax position.`,
    estimatedImpact: law.impactExplanation,
    actionItem: law.actionRequired
  }));

  return {
    clientName: ret.clientName,
    greeting: `Dear ${ret.clientName.split(' ')[0]},`,
    overview: `As we prepare for the upcoming tax filing season, our practice has conducted a preliminary analysis of your 2024 return alongside the latest tax law modifications effective for the 2025 tax year. Below is your personalized summary of key legislative changes and our pre-filled 2025 Tax Organizer.`,
    personalizedLawParagraphs: personalizedParagraphs,
    filingDeadlineNotice: 'Please review and return the attached fillable Tax Organizer along with your supporting tax documents by March 20, 2026 to ensure timely filing.',
    closing: 'Warm regards,\nYour Tax & Financial Planning Advisory Team'
  };
}

export function generateInitialSuperDocsDiffs(
  ret: TaxReturnData,
  organizer: any[],
  letter: any
): SuperDocsDiff[] {
  return [
    {
      id: `diff-1-${ret.clientId}`,
      targetSectionId: 'year-end-letter',
      locationLabel: 'Year-End Letter - Tax Law Paragraph #1',
      changeType: 'addition',
      originalText: '[Generic Tax Law Update Notice]',
      proposedText: letter.personalizedLawParagraphs[0]?.lawTitle
        ? `APPLICABLE TAX LAW UPDATE: ${letter.personalizedLawParagraphs[0].lawTitle}\nImpact: ${letter.personalizedLawParagraphs[0].estimatedImpact}\nAction Needed: ${letter.personalizedLawParagraphs[0].actionItem}`
        : 'Specific tax law updates matched to client return.',
      explanation: `Extracted from prior return (${ret.priorYearFormSources[0]?.sourceLine || 'Form 1040'}) and matched with 2025 IRC updates for ${ret.segment.toUpperCase()} segment.`,
      citation: ret.priorYearFormSources[0]?.sourceLine || 'Form 1040',
      status: 'pending'
    },
    {
      id: `diff-2-${ret.clientId}`,
      targetSectionId: 'organizer-prefill',
      locationLabel: 'Organizer - Pre-filled Income & Deduction Checklist',
      changeType: 'modification',
      originalText: 'Standard Blank Checklist (W-2, 1099, Mortgage, Student Loan, Childcare)',
      // Only append the "(benchmark totals ...)" clause when there are
      // actually benchmark figures to show. When priorYearFormSources comes
      // back empty (the model didn't populate it this run), rendering
      // "benchmark totals ()." leaves a bare empty pair of parentheses, which
      // looks unfinished. Omit the whole clause in that case.
      proposedText: (() => {
        const benchmarks = ret.priorYearFormSources.map((s) => s.field + ': ' + s.value).join('; ');
        const base = `Client-Specific Pre-filled Schedules: ${ret.schedulesApplied.join(', ')}.`;
        return benchmarks
          ? `${base} Includes prior year benchmark totals (${benchmarks}).`
          : `${base} Pre-filled directly from the client's 2024 filed schedules.`;
      })(),
      explanation: 'Replaced generic checklist with pre-filled schedules verified directly against the client\'s 2024 filed tax return.',
      // Previously hardcoded as 'Prior Year Form 1040, Schedule C / E / 2555'
      // regardless of the client's actual filed schedules -- e.g. a
      // Schedule-C-only client (no Schedule E, no Form 2555) still got that
      // exact citation, falsely implying those schedules were on file. Now
      // derived from the client's real schedulesApplied, since that's what
      // this modification is actually grounded in.
      citation: ret.schedulesApplied.length > 0
        ? `Prior Year Form 1040, ${ret.schedulesApplied.join(' / ')}`
        : 'Prior Year Form 1040',
      status: 'pending'
    }
  ];
}
