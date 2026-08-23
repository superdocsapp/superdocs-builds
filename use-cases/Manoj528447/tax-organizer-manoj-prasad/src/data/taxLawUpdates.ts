import { TaxLawUpdate } from '../types';

export const CURRENT_TAX_LAW_UPDATES: TaxLawUpdate[] = [
  {
    id: 'law-qbi-199a',
    title: 'Qualified Business Income (QBI) Deduction Threshold Indexing',
    codeSection: 'IRC §199A',
    yearEffective: 2025,
    targetSegments: ['business', 'hnw', 'rental'],
    summary: 'Threshold amounts increased to $191,950 ($383,900 married joint). Phase-outs apply above these limits for Specified Service Trades or Businesses (SSTBs).',
    impactExplanation: 'Your Schedule C / S-Corp pass-through profit qualifies for up to a 20% tax deduction. We need your accurate QBI wage allocations and unadjusted basis of qualified property.',
    actionRequired: 'Provide W-2 wages paid by the entity and asset additions list before December 31.'
  },
  {
    id: 'law-sec179-bonus',
    title: 'Section 179 Expensing Limit & Bonus Depreciation Phase-down',
    codeSection: 'IRC §179 / §168(k)',
    yearEffective: 2025,
    targetSegments: ['business', 'rental'],
    summary: 'Section 179 max expensing limit updated to $1,220,000 with a $3,050,000 investment ceiling. 100% bonus depreciation phase-down applies to equipment placed in service.',
    impactExplanation: 'As a business/rental owner purchasing capital assets or equipment, taking maximum Section 179 early in the year reduces net profit directly.',
    actionRequired: 'Send invoices and in-service dates for all business equipment, vehicles, or property improvements purchased.'
  },
  {
    id: 'law-feie-2555',
    title: 'Foreign Earned Income Exclusion (FEIE) Maximum Increase',
    codeSection: 'IRC §911',
    yearEffective: 2025,
    targetSegments: ['expatriate'],
    summary: 'The maximum FEIE limit increased to $126,500 per qualifying individual ($253,000 for qualifying married couples both working abroad).',
    impactExplanation: 'As an overseas resident, you can exclude up to $126,500 of foreign employment or self-employment income from US federal income tax.',
    actionRequired: 'Provide day-count travel log to verify 330-day physical presence or bona fide residency test details, plus foreign housing expense records.'
  },
  {
    id: 'law-fbar-fatca',
    title: 'FBAR (FinCEN 114) & Form 8938 Foreign Asset Thresholds',
    codeSection: '31 U.S.C. §5314 / IRC §6038D',
    yearEffective: 2025,
    targetSegments: ['expatriate', 'hnw'],
    summary: 'FBAR reporting remains mandatory if aggregate foreign bank account value exceeds $10,000 at any point during the calendar year.',
    impactExplanation: 'Penalties for non-willful failure to report foreign accounts remain severe. Confirm the highest balance reached in each foreign account during 2025 so we can determine your filing obligation.',
    actionRequired: 'Provide maximum highest balance during the year for all non-US bank, investment, or pension accounts.'
  },
  {
    id: 'law-clean-energy',
    title: 'Residential Clean Energy & Energy Efficient Home Improvement Credits',
    codeSection: 'IRC §25C / §25D',
    yearEffective: 2025,
    targetSegments: ['individual', 'rental', 'hnw'],
    summary: '30% tax credit for solar, battery storage, heat pumps, and energy-efficient windows/doors up to annual caps.',
    impactExplanation: 'If you made energy upgrades to your primary residence or qualifying rental properties, you may qualify for dollar-for-dollar tax credits.',
    actionRequired: 'Submit manufacturer certification statements and itemized installation receipts.'
  },
  {
    id: 'law-schedule-e-rental',
    title: 'Real Estate Professional Status & Short-Term Rental Safe Harbor',
    codeSection: 'IRC §469(c)(7)',
    yearEffective: 2025,
    targetSegments: ['rental', 'hnw'],
    summary: 'IRS audit focus intensified on passive loss deductions claimed against active income by non-licensed real estate professionals.',
    impactExplanation: 'Because you report rental income on Schedule E, passive activity loss limitations apply unless you document 750+ material participation hours.',
    actionRequired: 'Submit your contemporaneous time log if claiming Real Estate Professional Status or active participation deduction.'
  },
  {
    id: 'law-standard-salt',
    title: 'Standard Deduction vs. Itemized SALT Limit',
    codeSection: 'IRC §63 / §164(b)(6)',
    yearEffective: 2025,
    targetSegments: ['individual', 'hnw'],
    summary: 'Standard deduction indexed to $30,000 (Married Filing Joint) / $15,000 (Single). SALT deduction remains capped at $10,000.',
    impactExplanation: 'We pre-evaluated your mortgage interest and property taxes from last year to check if itemizing or standard deduction yields higher savings.',
    actionRequired: 'Provide Form 1098 Mortgage Interest, property tax statements, and charitable donation receipts.'
  }
];
