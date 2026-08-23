import { TaxReturnData, TaxLawUpdate, YearEndLetterContent } from '../types';
import { CURRENT_TAX_LAW_UPDATES } from '../data/taxLawUpdates';
import { getGreetingName, formatScheduleList } from '../utils/greeting';

/**
 * Some laws target a broad catch-all segment (e.g. 'hnw') alongside a
 * specific one (e.g. 'rental', 'expatriate'). Segment membership alone is a
 * reliable applicability signal for the specific segment, but NOT for the
 * broad one -- an HNW client doesn't necessarily have rental or foreign
 * income just because they're HNW. Confirmed as a live bug in this app's own
 * built-in demo data: 'Dr. Robert & Sarah Chen' (hnw, zero rental income,
 * zero foreign income) was still shown the rental passive-activity-loss
 * paragraph (falsely asserting "Because you report rental income on
 * Schedule E...") and the FBAR paragraph, purely because 'hnw' is in both
 * laws' targetSegments. This maps law id -> an additional data-presence
 * check that must also pass, on top of the segment match, before that law's
 * paragraph is included for that specific client.
 */
const REQUIRES_UNDERLYING_DATA: Record<string, (ret: TaxReturnData) => boolean> = {
  'law-qbi-199a': (ret) => Boolean(ret.income.businessNetProfit || ret.income.rentalNetIncome),
  'law-fbar-fatca': (ret) => ret.segment === 'expatriate' || Boolean(ret.income.foreignEarnedIncome),
  'law-schedule-e-rental': (ret) => ret.segment === 'rental' || Boolean(ret.income.rentalNetIncome)
};

/**
 * Analyzes prior year return against 2025 IRC tax laws and generates
 * client-grounded, non-generic law analysis paragraphs.
 */
export function generateClientLawAnalysis(ret: TaxReturnData): YearEndLetterContent {
  const applicableLaws = CURRENT_TAX_LAW_UPDATES.filter((law) => {
    if (!law.targetSegments.includes(ret.segment)) return false;
    const extraCheck = REQUIRES_UNDERLYING_DATA[law.id];
    return extraCheck ? extraCheck(ret) : true;
  });

  const personalizedParagraphs = applicableLaws.map((law) => {
    const scheduleList = formatScheduleList(ret.schedulesApplied);
    const scheduleClause = scheduleList
      ? ` and prior return schedules (${scheduleList})`
      : ' (no prior return schedules were identified for this client)';
    let groundedReason = `Based on your ${ret.segment.toUpperCase()} filing profile${scheduleClause}, this law change directly impacts your 2025 tax liability.`;

    if (law.codeSection === 'IRC §199A' && ret.income.businessNetProfit) {
      groundedReason = `Your 2024 Schedule C net profit of $${ret.income.businessNetProfit.toLocaleString('en-US')} qualified for $${(ret.deductionsClaimed.qbiDeduction || 0).toLocaleString('en-US')} in QBI savings. For 2025, the updated $191,950 threshold determines whether W-2 wage testing applies to your entity.`;
    } else if (law.codeSection.includes('§179') && ret.deductionsClaimed.section179Depreciation) {
      groundedReason = `You claimed $${ret.deductionsClaimed.section179Depreciation.toLocaleString('en-US')} in Section 179 depreciation on Form 4562 last year. The 2025 $1,220,000 expensing limit allows full immediate write-off of new equipment purchases placed in service this year.`;
    } else if (law.codeSection === 'IRC §911' && ret.income.foreignEarnedIncome) {
      groundedReason = `You excluded $${ret.income.foreignEarnedIncome.toLocaleString('en-US')} of foreign earned income on Form 2555 last year. The 2025 FEIE cap increase to $126,500 ($253,000 joint) expands your tax-free foreign wage threshold.`;
    } else if (law.codeSection === 'IRC §469(c)(7)' && ret.income.rentalNetIncome) {
      groundedReason = `Your Schedule E rental profit of $${ret.income.rentalNetIncome.toLocaleString('en-US')} is subject to passive activity loss limitations under IRC §469 unless you satisfy the Real Estate Professional 750-hour participation requirement.`;
    }

    // QBI (§199A) targets business, rental, AND hnw segments (see
    // taxLawUpdates.ts), but its static impactExplanation only described the
    // Schedule C / S-Corp qualifying path. A rental-only client (no Schedule
    // C or S-Corp income at all) was shown "Your Schedule C / S-Corp
    // pass-through profit qualifies..." verbatim -- factually wrong for
    // them, since rental real estate qualifies for QBI through a different
    // mechanism (the §199A rental real estate safe harbor), not a Schedule C
    // profit. This mirrors the relevanceReason override above but for
    // estimatedImpact, which was previously always static regardless of
    // which path actually applies to this client.
    let estimatedImpact = law.impactExplanation;
    if (law.codeSection === 'IRC §199A' && !ret.income.businessNetProfit && ret.income.rentalNetIncome) {
      estimatedImpact = 'Your rental real estate activity may qualify for the QBI deduction under the §199A rental real estate safe harbor (Rev. Proc. 2019-38), not the Schedule C / S-Corp pass-through path. We need your 250-hour rental services log and property-level income/expense detail to confirm eligibility.';
    }

    return {
      lawTitle: `${law.title} (${law.codeSection})`,
      relevanceReason: groundedReason,
      estimatedImpact,
      actionItem: law.actionRequired
    };
  });

  const firstName = getGreetingName(ret.clientName);

  // Determine filing deadline based on segment
  let deadlineStr = 'March 20, 2026';
  if (ret.segment === 'business') {
    deadlineStr = 'March 15, 2026 (S-Corporation & Partnership Filing Deadline)';
  } else if (ret.segment === 'expatriate') {
    deadlineStr = 'June 15, 2026 (Expatriate Automatic Overseas Extension Deadline)';
  } else {
    deadlineStr = 'April 15, 2026 (Individual Form 1040 Deadline)';
  }

  const overviewScheduleList = formatScheduleList(ret.schedulesApplied);
  const overviewScheduleClause = overviewScheduleList
    ? ` (${overviewScheduleList})`
    : '';

  return {
    clientName: ret.clientName,
    greeting: `Dear ${firstName},`,
    overview: `As we approach the 2025 tax filing season, our advisory practice has conducted a thorough review of your 2024 tax return${overviewScheduleClause} alongside the latest 2025 Internal Revenue Code updates. Below is your tailored summary of legislative tax updates and your pre-filled 2025 Tax Organizer.`,
    personalizedLawParagraphs: personalizedParagraphs,
    filingDeadlineNotice: `Notice: Please submit your pre-filled Tax Organizer and required supporting documents by ${deadlineStr} to guarantee timely filing without extension penalties.`,
    closing: 'Sincerely,\nYour Tax Advisory & CPA Team\nPremier CPA & Tax Advisory Group'
  };
}
