import { WorkspaceState } from './types';

export const initialState: WorkspaceState = {
  documents: [
    { id: 'vendor-agreement', name: 'vendor-agreement.docx', kind: 'docx', owner: 'Legal Ops' },
    { id: 'implementation-plan', name: 'implementation-plan.docx', kind: 'docx', owner: 'Delivery' }
  ],
  changes: [
    {
      id: 'chg-1', documentId: 'vendor-agreement', agent: 'Cursor Agent', turn: 18,
      section: 'Clause 8.2 · Renewal notice',
      before: 'Either party may terminate the agreement with 30 days written notice.',
      after: 'Either party may terminate the agreement with 45 days written notice.',
      claim: 'Updated the renewal notice from 30 days to 45 days.',
      actual: 'The document now states 45 days written notice in Clause 8.2.',
      verification: 'verified', status: 'pending',
      artifactState: 'Either party may terminate the agreement with 30 days written notice.'
    },
    {
      id: 'chg-2', documentId: 'vendor-agreement', agent: 'Cursor Agent', turn: 18,
      section: 'Support escalation',
      before: 'The vendor will respond to urgent support requests and coordinate escalation through the designated account contact.',
      after: 'Urgent support requests route through the designated account contact for coordinated escalation.',
      claim: 'Made the support escalation paragraph more concise without changing meaning.',
      actual: 'Only the support escalation paragraph changed; the escalation owner remains the same.',
      verification: 'verified', status: 'pending',
      artifactState: 'The vendor will respond to urgent support requests and coordinate escalation through the designated account contact.'
    },
    {
      id: 'chg-3', documentId: 'vendor-agreement', agent: 'Cursor Agent', turn: 18,
      section: 'Payment terms',
      before: 'Invoices are payable Net 30 from receipt.',
      after: 'Invoices are payable Net 45 from receipt.',
      claim: 'No unrelated clauses were changed.',
      actual: 'Payment terms changed from Net 30 to Net 45 even though the request did not mention payments.',
      verification: 'mismatch', status: 'pending',
      artifactState: 'Invoices are payable Net 30 from receipt.'
    },
    {
      id: 'chg-4', documentId: 'implementation-plan', agent: 'Claude Code', turn: 7,
      section: 'Current status',
      before: 'Pilot deployment starts after security review.',
      after: 'Pilot deployment starts after security review.',
      claim: 'Updated the current status to note that security review is complete.',
      actual: 'No corresponding document change was found.',
      verification: 'mismatch', status: 'pending',
      artifactState: 'Pilot deployment starts after security review.'
    }
  ],
  selectedChangeId: 'chg-1'
};
