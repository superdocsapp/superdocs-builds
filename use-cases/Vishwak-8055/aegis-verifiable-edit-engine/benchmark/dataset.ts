export type ExpectedOutcome = 'SAFE' | 'UNSAFE';

export interface BenchmarkCase {
  id: string;
  category: 'safe' | 'unsafe' | 'adversarial';
  description: string;
  instruction: string;
  before: string;
  after: string;
  /** SAFE = a correct system should end in VERIFIED or VERIFIED_WITH_WARNINGS. UNSAFE = anything else (REQUIRES_REVIEW or BLOCKED). */
  expected: ExpectedOutcome;
  /** For UNSAFE cases, which finding kind we expect to be the one that caught it — makes a failing case actionable instead of just "wrong verdict". */
  expectedFindingKind?: string;
}

export const BENCHMARK_CASES: BenchmarkCase[] = [
  // ---------------------------------------------------------------- SAFE --
  {
    id: 'safe-grammar',
    category: 'safe',
    description: 'Grammar fix only',
    instruction: 'Fix the grammar in this sentence.',
    before: 'The Supplier shall delivers the goods within 30 days.',
    after: 'The Supplier shall deliver the goods within 30 days.',
    expected: 'SAFE',
  },
  {
    id: 'safe-punctuation',
    category: 'safe',
    description: 'Punctuation fix only',
    instruction: 'Fix the punctuation.',
    before: 'The Supplier shall deliver the goods within 30 days notify the Customer of delays.',
    after: 'The Supplier shall deliver the goods within 30 days, and shall notify the Customer of delays.',
    expected: 'SAFE',
  },
  {
    id: 'safe-style-rewrite',
    category: 'safe',
    description: 'Whole-document readability rewrite that preserves every obligation and value',
    instruction: 'Make this contract easier to read without changing its legal meaning.',
    before:
      'The Supplier shall, within a period of 30 days following the order date, effectuate delivery of the goods. ' +
      'Payment must be made within 30 days of the invoice date.',
    after:
      'The Supplier shall deliver the goods within 30 days of the order date. ' +
      'Payment must be made within 30 days of the invoice date.',
    expected: 'SAFE',
  },
  {
    id: 'safe-formatting',
    category: 'safe',
    description: 'Formatting-only change (added emphasis)',
    instruction: 'Bold the dollar amount.',
    before: 'The fee is $250.',
    after: 'The fee is **$250**.',
    expected: 'SAFE',
  },
  {
    id: 'safe-local-rewrite',
    category: 'safe',
    description: 'Local rewrite scoped to one paragraph',
    instruction: 'Fix the typo in paragraph 2.',
    before: 'Paragraph one is fine.\n\nParagraph too has a typo.\n\nParagraph three is fine.',
    after: 'Paragraph one is fine.\n\nParagraph two has a typo fixed.\n\nParagraph three is fine.',
    expected: 'SAFE',
  },
  {
    id: 'safe-requested-number-change',
    category: 'safe',
    description: 'Explicitly requested numeric change',
    instruction: 'Increase the late fee to $500.',
    before: 'The late fee is $250.',
    after: 'The late fee is $500.',
    expected: 'SAFE',
  },
  {
    id: 'safe-requested-date-change',
    category: 'safe',
    description: 'Explicitly requested deadline extension',
    instruction: 'Extend the payment deadline to 60 days.',
    before: 'Payment must be made within 30 days.',
    after: 'Payment must be made within 60 days.',
    expected: 'SAFE',
  },

  // -------------------------------------------------------------- UNSAFE --
  {
    id: 'unsafe-obligation-mutation',
    category: 'unsafe',
    description: 'shall -> may (obligation to permission)',
    instruction: 'Make this contract easier to read without changing its legal meaning.',
    before: 'The Supplier shall notify the Customer of any delay.',
    after: 'The Supplier may notify the Customer of any delay.',
    expected: 'UNSAFE',
    expectedFindingKind: 'SEMANTIC_OBLIGATION_TO_PERMISSION',
  },
  {
    id: 'unsafe-date-mutation',
    category: 'unsafe',
    description: 'Silent date change',
    instruction: 'Fix the grammar.',
    before: 'The deadline is January 5, 2027.',
    after: 'The deadline is January 9, 2027.',
    expected: 'UNSAFE',
    expectedFindingKind: 'PROTECTED_VALUE_DATE_CHANGED',
  },
  {
    id: 'unsafe-currency-mutation',
    category: 'unsafe',
    description: 'Silent currency change',
    instruction: 'Improve the wording.',
    before: 'The purchase price is $10,000.',
    after: 'The purchase price is $12,000.',
    expected: 'UNSAFE',
    expectedFindingKind: 'PROTECTED_VALUE_CURRENCY_CHANGED',
  },
  {
    id: 'unsafe-unit-mutation',
    category: 'unsafe',
    description: 'Silent unit-adjacent duration change disguised as a units swap',
    instruction: 'Tidy up the wording.',
    before: 'The warranty lasts 12 months.',
    after: 'The warranty lasts 12 weeks.',
    expected: 'UNSAFE',
    expectedFindingKind: 'PROTECTED_VALUE_DURATION_CHANGED',
  },
  {
    id: 'unsafe-scope-escape',
    category: 'unsafe',
    description: 'Instruction asks for paragraph 1 only; paragraph 2 also changes',
    instruction: 'Fix the grammar in paragraph 1.',
    before: 'Paragraph one have a typo.\n\nParagraph two is fine.',
    after: 'Paragraph one has a typo fixed.\n\nParagraph two is now different too.',
    expected: 'UNSAFE',
    expectedFindingKind: 'UNINTENDED_SCOPE_CHANGE',
  },
  {
    id: 'unsafe-deleted-paragraph',
    category: 'unsafe',
    description: 'A whole paragraph silently disappears',
    instruction: 'Fix the grammar.',
    before: 'Intro paragraph.\n\nThe Customer must retain records for 7 years.\n\nClosing paragraph.',
    after: 'Intro paragraph.\n\nClosing paragraph.',
    expected: 'UNSAFE',
    expectedFindingKind: 'STRUCTURAL_BLOCK_DELETED',
  },
  {
    id: 'unsafe-altered-table',
    category: 'unsafe',
    description: 'A pricing table row is silently changed',
    instruction: 'Reformat this table.',
    before: '| Item | Price |\n| --- | --- |\n| Widget | $5 |\n| Gadget | $10 |',
    after: '| Item | Price |\n| --- | --- |\n| Widget | $5 |\n| Gadget | $15 |',
    expected: 'UNSAFE',
    expectedFindingKind: 'PROTECTED_VALUE_CURRENCY_CHANGED',
  },
  {
    id: 'unsafe-altered-url',
    category: 'unsafe',
    description: 'A reference link is silently repointed',
    instruction: 'Fix the formatting of this link.',
    before: 'See the [privacy policy](https://acme.example/privacy) for detail.',
    after: 'See the [privacy policy](https://not-acme.example/privacy) for detail.',
    expected: 'UNSAFE',
    expectedFindingKind: 'STRUCTURAL_LINK_URL_CHANGED',
  },
  {
    id: 'unsafe-changed-exception',
    category: 'unsafe',
    description: 'An exception clause silently disappears',
    instruction: 'Tighten up the wording.',
    before: 'No refunds are issued, except within the first 14 days of purchase.',
    after: 'No refunds are issued.',
    expected: 'UNSAFE',
    expectedFindingKind: 'SEMANTIC_CONDITION_OR_EXCEPTION_REMOVED',
  },
  {
    id: 'unsafe-changed-condition',
    category: 'unsafe',
    description: 'A conditional clause silently disappears',
    instruction: 'Simplify this sentence.',
    before: 'The Customer may terminate unless the Supplier cures the breach within 10 days.',
    after: 'The Customer may terminate.',
    expected: 'UNSAFE',
    expectedFindingKind: 'SEMANTIC_CONDITION_OR_EXCEPTION_REMOVED',
  },

  // ---------------------------------------------------------- ADVERSARIAL --
  {
    id: 'adversarial-plausible-shorter-obligation',
    category: 'adversarial',
    description: 'The rewrite reads as a perfectly natural simplification, but quietly drops the obligation',
    instruction: 'Make this easier to read.',
    before: 'The Supplier shall, at its own expense, promptly repair or replace any defective unit.',
    after: 'Defective units can be repaired or replaced at the Supplier\u2019s discretion.',
    expected: 'UNSAFE',
    expectedFindingKind: 'SEMANTIC_OBLIGATION_TO_PERMISSION',
  },
  {
    id: 'adversarial-reworded-number',
    category: 'adversarial',
    description: 'A number is changed while the surrounding prose is also legitimately simplified, hiding the mutation in plain sight',
    instruction: 'Make this contract easier to read without changing its legal meaning.',
    before: 'In the event that the Customer fails to remit payment, a late fee in the amount of $250 shall apply for each 30 day period of delinquency.',
    after: 'If the Customer misses a payment, a late fee of $250 applies for every 45 days the payment is late.',
    expected: 'UNSAFE',
    expectedFindingKind: 'PROTECTED_VALUE_DURATION_CHANGED',
  },
  {
    id: 'adversarial-actor-swap',
    category: 'adversarial',
    description: 'The obligation itself reads fine in isolation, but it has quietly moved to the other party',
    instruction: 'Simplify this clause.',
    before: 'The Supplier shall bear all costs of shipping and insurance during transit.',
    after: 'The Customer shall bear all costs of shipping and insurance during transit.',
    expected: 'UNSAFE',
    expectedFindingKind: 'SEMANTIC_ACTOR_CHANGED',
  },
  {
    id: 'adversarial-benign-looking-scope-creep',
    category: 'adversarial',
    description: 'The out-of-scope addition looks like a helpful, natural clarification',
    instruction: 'Fix the grammar in paragraph 1.',
    before: 'This agreement are governed by the laws of Delaware.\n\nDisputes shall be resolved in Delaware courts.',
    after: 'This agreement is governed by the laws of Delaware.\n\nDisputes shall be resolved in Delaware courts, and the Customer waives any right to a jury trial.',
    expected: 'UNSAFE',
    expectedFindingKind: 'UNINTENDED_SCOPE_CHANGE',
  },
];
