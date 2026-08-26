export const INITIAL_DOCUMENT_HTML = `
  <h1 data-chunk-id="title">Quarterly Client Update</h1>
  <p data-chunk-id="greeting">Dear implementation partners,</p>
  <p data-chunk-id="introduction">Northstar Systems entered the third quarter with two priorities: complete the managed-platform migration and improve the reliability of client reporting. The program remains on schedule, and the joint delivery team completed each committed milestone without changing the approved scope. This update summarizes delivery progress, operational results, current risks, and the decisions required before the next steering review.</p>

  <h2 data-chunk-id="executive-summary">Executive summary</h2>
  <p data-chunk-id="casual-status">Things have been going pretty well overall, and the team knocked out most of what we wanted to do. A couple of integrations took longer than expected, but everyone jumped in and we got them over the line without making a big deal out of it.</p>
  <p data-chunk-id="summary-detail">The production migration is now <strong>82% complete</strong>, compared with 61% at the start of the quarter. Service availability improved to <strong>99.97%</strong>, while median incident-recovery time declined from 54 minutes to 31 minutes. Client teams also adopted the new reporting workspace faster than forecast, with 146 active users completing <em>more than 1,900 validated workflows</em>.</p>

  <h2 data-chunk-id="delivery-heading">Delivery progress</h2>
  <p data-chunk-id="delivery-intro">The quarter focused on stabilizing the core implementation before expanding into the remaining business units. The program delivered the following outcomes:</p>
  <ul data-chunk-id="delivery-list">
    <li data-chunk-id="delivery-list-1"><strong>Platform migration:</strong> Eleven of fourteen production services now run on the managed environment, including the reporting gateway and audit service.</li>
    <li data-chunk-id="delivery-list-2"><strong>Data quality:</strong> Automated reconciliation reduced unresolved exceptions by 38% and established a traceable owner for every critical rule.</li>
    <li data-chunk-id="delivery-list-3"><strong>Operational readiness:</strong> Support teams completed two failover exercises and published updated escalation procedures for regional incidents.</li>
    <li data-chunk-id="delivery-list-4"><strong>User enablement:</strong> Six role-based workshops were delivered, and the searchable <a href="https://example.com/northstar-implementation-guide">implementation guide</a> now covers the highest-volume workflows.</li>
  </ul>

  <h3 data-chunk-id="engineering-heading">Engineering and integration</h3>
  <p data-chunk-id="grammar-target">The migration were completed across three additional services, and each teams have confirmed their monitoring rules. No critical defects was identified during the release window however two low priority alerts remains under review.</p>
  <p data-chunk-id="engineering-detail">The identity and finance integrations required additional testing after upstream vendors changed certificate requirements. The change added four working days to those workstreams, but available schedule contingency absorbed the delay. No downstream milestone moved, and the integration team added certificate-rotation checks to the release checklist.</p>

  <h3 data-chunk-id="adoption-heading">Adoption and change management</h3>
  <p data-chunk-id="adoption-detail">Adoption remains strongest among operations and client-service teams. Finance participation improved after the team replaced a broad introductory session with shorter workflow clinics. Three departments still rely on legacy exports for month-end reporting, so the fourth-quarter plan includes targeted office hours and a documented retirement date for each export.</p>

  <h3 data-chunk-id="delivery-scorecard-heading">Delivery scorecard</h3>
  <table data-chunk-id="delivery-scorecard-table">
    <tr>
      <th data-chunk-id="delivery-scorecard-measure" scope="col">Measure</th>
      <th data-chunk-id="delivery-scorecard-result" scope="col">Quarter result</th>
    </tr>
    <tr>
      <td data-chunk-id="delivery-scorecard-migration">Production migration</td>
      <td data-chunk-id="delivery-scorecard-migration-result">82% complete</td>
    </tr>
    <tr>
      <td data-chunk-id="delivery-scorecard-availability">Service availability</td>
      <td data-chunk-id="delivery-scorecard-availability-result">99.97%</td>
    </tr>
  </table>

  <h2 data-chunk-id="risk-heading">Risks and mitigations</h2>
  <p data-chunk-id="structural-target">The principal delivery risks are the final identity cutover, incomplete ownership for twelve legacy reports, and limited availability during the year-end change freeze. The team will mitigate these risks by completing a rehearsal before the production cutover, assigning an executive owner to each remaining report, and moving all high-risk releases ahead of the freeze.</p>
  <blockquote data-chunk-id="risk-quote">“The remaining work is concentrated rather than broad. Success now depends on disciplined ownership and a controlled final cutover, not on adding more scope.” — Program Director</blockquote>

  <h2 data-chunk-id="next-steps-heading">Next steps</h2>
  <p data-chunk-id="next-steps-intro">Before the next steering meeting, the joint team will complete the following actions in order:</p>
  <ol data-chunk-id="next-steps-list">
    <li data-chunk-id="next-steps-list-1">Run the final identity cutover rehearsal and document rollback criteria.</li>
    <li data-chunk-id="next-steps-list-2">Confirm ownership and retirement dates for all remaining legacy reports.</li>
    <li data-chunk-id="next-steps-list-3">Complete regional failover validation and close the two outstanding low-priority alerts.</li>
    <li data-chunk-id="next-steps-list-4">Submit the fourth-quarter release calendar for steering approval.</li>
  </ol>
  <p data-chunk-id="closing">We appreciate the continued partnership and the direct feedback provided throughout the quarter. The program is positioned to complete the remaining migration safely while preserving service quality and client continuity.</p>
  <p data-chunk-id="signature">Sincerely,<br><strong>The Northstar Implementation Team</strong></p>
`;

export const PROMPT_PRESETS = [
  'Make concise',
  'Improve clarity',
  'Professional tone',
  'Fix grammar',
  'Turn into bullets',
  'Simplify language',
] as const;

export type BenchmarkInvariant =
  | 'headings'
  | 'bold'
  | 'italic'
  | 'links'
  | 'lists'
  | 'blockquotes'
  | 'tables';

export type BenchmarkCase = {
  id: string;
  label: string;
  purpose: string;
  scope: 'selection' | 'document';
  targetChunkId: string | null;
  instruction: string;
  expectedInvariants: BenchmarkInvariant[];
};

export const BENCHMARK_CASES: BenchmarkCase[] = [
  {
    id: 'test-01-concision',
    label: 'Concision',
    purpose:
      'Checks whether the engine can shorten one paragraph while keeping its meaning and professional tone.',
    scope: 'selection',
    targetChunkId: 'introduction',
    instruction:
      'Make this paragraph more concise while preserving its meaning and professional tone.',
    expectedInvariants: ['headings', 'links', 'lists', 'blockquotes', 'tables'],
  },
  {
    id: 'test-02-professional-tone',
    label: 'Professional tone',
    purpose:
      'Checks whether the engine can turn casual wording into language suitable for a client update.',
    scope: 'selection',
    targetChunkId: 'casual-status',
    instruction:
      'Rewrite this paragraph in a concise, professional tone suitable for a client update.',
    expectedInvariants: ['headings', 'links', 'lists', 'blockquotes', 'tables'],
  },
  {
    id: 'test-03-grammar',
    label: 'Grammar',
    purpose:
      'Checks whether the engine can fix grammar and punctuation without rewriting the message.',
    scope: 'selection',
    targetChunkId: 'grammar-target',
    instruction:
      'Correct the grammar and punctuation without changing the meaning.',
    expectedInvariants: ['headings', 'links', 'lists', 'blockquotes', 'tables'],
  },
  {
    id: 'test-04-structural',
    label: 'Structural edit',
    purpose:
      'Checks whether the engine can change one paragraph into a short bullet list while preserving its information.',
    scope: 'selection',
    targetChunkId: 'structural-target',
    instruction:
      'Convert this paragraph into a short bullet list while preserving all important information.',
    expectedInvariants: ['headings', 'links', 'blockquotes', 'tables'],
  },
  {
    id: 'test-05-insertion',
    label: 'Document-level insertion',
    purpose:
      'Checks whether the engine can add a conclusion to the full document without rewriting unrelated content.',
    scope: 'document',
    targetChunkId: null,
    instruction:
      'Add a short conclusion summarizing the key project status and next steps. Do not rewrite the rest of the document.',
    expectedInvariants: [
      'headings',
      'bold',
      'italic',
      'links',
      'lists',
      'blockquotes',
      'tables',
    ],
  },
];