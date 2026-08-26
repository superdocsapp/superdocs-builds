'use strict';
/**
 * Northstar Systems demo corpus — fictional, self-contained fixture data.
 * No network calls, no external services: every value here is static.
 *
 * Section bodies use {TERM} / {NET} placeholders where the Payment Term
 * value is substituted. Evidence is expressed the same way (evidenceTemplate)
 * so it can be resolved against the *same* rendered text a reader would
 * actually see, instead of asserted as a fact independent of it.
 */

const ENTITIES = [
  { id: 'ent-northstar', name: 'Northstar Systems, Inc.', kind: 'Organization' },
  { id: 'ent-meridian', name: 'Meridian Retail Group LLC', kind: 'Organization' },
];

const DOC_TEXT = {
  agreement: {
    id: 'agreement',
    title: 'Northstar Customer Agreement',
    subtitle: 'Northstar Systems, Inc. — Meridian Retail Group LLC',
    sections: [
      { id: 'pre', heading: null, body: 'This Customer Agreement ("Agreement") is entered into between Northstar Systems, Inc. ("Northstar") and Meridian Retail Group LLC ("Customer"), effective as of January 1, 2026.' },
      { id: 's1', heading: '1. Services', body: 'Northstar shall provide Customer with access to the Northstar platform and related services as described in the applicable Order Form(s).' },
      { id: 's4', heading: '4. Fees and Payment', body: null, sub: [
        { id: 's4-1', label: '4.1 Fees.', body: 'Customer shall pay the fees set forth in each Order Form in accordance with the invoicing schedule specified therein.' },
        { id: 's4-2', label: '4.2 Payment Terms.', body: 'Customer shall pay all undisputed invoiced amounts within {TERM} of the invoice date (the "Payment Term"). Amounts not paid when due shall accrue interest at a rate of 1.5% per month or the maximum rate permitted by law, whichever is lower.', objectId: 'obl-payment' },
      ] },
      { id: 's7', heading: '7. Renewal', body: 'This Agreement shall automatically renew for successive one (1) year terms unless either party provides written notice of non-renewal at least sixty (60) days prior to the end of the then-current term. Renewal pricing and invoicing shall be governed by the Pricing Policy and Renewal Policy then in effect.', refs: ['pricing', 'renewal'] },
      { id: 's8', heading: '8. General', body: 'This Agreement is governed by the laws of the State of Delaware. Section headings are for convenience only.' },
    ],
  },
  invoice: {
    id: 'invoice', title: 'Northstar Invoice Template', subtitle: 'Standard billing document',
    sections: [
      { id: 'i1', heading: 'Payment Instructions', body: 'Payment is due within {TERM} of the invoice date ({NET}). Remit payment to Northstar Systems, Inc., Attn: Accounts Receivable.', objectId: 'clm-invoice-net30' },
    ],
  },
  sales: {
    id: 'sales', title: 'Northstar Sales Terms', subtitle: 'Internal commercial policy',
    sections: [
      { id: 'sa3', heading: '3. Standard Commercial Terms', body: 'Except as otherwise specified in a signed Customer Agreement, standard payment terms for all Northstar Systems invoices are net forty-five (45) days from the invoice date. Sales representatives are not authorized to modify payment terms without Legal approval.', objectId: 'req-sales-45' },
    ],
  },
  renewal: {
    id: 'renewal', title: 'Northstar Renewal Policy', subtitle: 'Governs renewal pricing and terms',
    sections: [
      { id: 'r1', heading: '1. Renewal Pricing and Terms', body: 'Upon renewal, invoicing and payment cadence shall follow the Payment Term specified in the governing Customer Agreement. Where no Customer Agreement term applies, the Standard Commercial Terms set forth in the Sales Terms shall govern.', objectId: 'dep-renewal' },
      { id: 'r2', heading: '2. Pricing Adjustment', body: 'Renewal pricing shall reflect the annual adjustment specified in the Pricing Policy, applied as of the renewal effective date.' },
    ],
  },
  pricing: {
    id: 'pricing', title: 'Northstar Pricing Policy', subtitle: 'Standard pricing and adjustment terms',
    sections: [
      { id: 'p2', heading: '2. Standard Pricing Tiers', body: 'Starter, Growth, and Enterprise tiers as defined in the current Order Form catalog.' },
      { id: 'p5', heading: '5. Annual Adjustment', body: 'List prices are subject to an annual adjustment of up to five percent (5%), effective each contract anniversary, applied automatically absent a superseding negotiated agreement.', objectId: 'obl-adjustment' },
    ],
  },
  enterprise: {
    id: 'enterprise', title: 'Northstar Enterprise Terms Addendum', subtitle: 'Applies to Enterprise-tier accounts',
    sections: [
      { id: 'e1', heading: '1. Payment Term Cap', body: 'For Enterprise-tier accounts, the Payment Term may not exceed {CAP} without prior written approval from VP Finance.', objectId: 'con-enterprise-cap' },
    ],
  },
};

const DOC_META = {
  agreement: { label: 'Customer Agreement' },
  invoice: { label: 'Invoice Template' },
  sales: { label: 'Sales Terms' },
  renewal: { label: 'Renewal Policy' },
  pricing: { label: 'Pricing Policy' },
  enterprise: { label: 'Enterprise Terms Addendum' },
};

const REQUIRED_SECTIONS = {
  agreement: ['pre', 's1', 's4-1', 's4-2', 's7', 's8'],
  invoice: ['i1'],
  sales: ['sa3'],
  renewal: ['r1', 'r2'],
  pricing: ['p2', 'p5'],
  enterprise: ['e1'],
};

const OBJECTS = {
  'obl-payment': {
    id: 'obl-payment', type: 'Obligation', doc: 'agreement', section: '4.2', sectionRef: 's4-2',
    statement: 'Customer must pay undisputed invoiced amounts within the Payment Term.',
    evidenceTemplate: 'Customer shall pay all undisputed invoiced amounts within {TERM} of the invoice date',
    confidence: 98, status: 'CONFIDENT',
  },
  'clm-invoice-net30': {
    id: 'clm-invoice-net30', type: 'Claim', doc: 'invoice', section: 'Payment Instructions', sectionRef: 'i1',
    statement: 'Invoice Template states the current Payment Term.',
    evidenceTemplate: 'Payment is due within {TERM} of the invoice date ({NET})',
    confidence: 95, status: 'CONFIDENT',
  },
  'req-sales-45': {
    id: 'req-sales-45', type: 'Requirement', doc: 'sales', section: '3', sectionRef: 'sa3',
    statement: 'Standard Commercial Terms default to net 45 days absent a signed Customer Agreement term.',
    evidenceTemplate: 'standard payment terms for all Northstar Systems invoices are net forty-five (45) days from the invoice date',
    confidence: 97, status: 'CONFIDENT', value: 45,
  },
  'dep-renewal': {
    id: 'dep-renewal', type: 'Dependency', doc: 'renewal', section: '1', sectionRef: 'r1',
    statement: 'Renewal invoicing cadence depends on the Payment Term in the Customer Agreement, falling back to the Sales Terms default.',
    evidenceTemplate: 'invoicing and payment cadence shall follow the Payment Term specified in the governing Customer Agreement',
    confidence: 90, status: 'LIKELY',
  },
  'obl-adjustment': {
    id: 'obl-adjustment', type: 'Obligation', doc: 'pricing', section: '5', sectionRef: 'p5',
    statement: 'Renewal pricing is subject to an annual adjustment of up to 5%.',
    evidenceTemplate: 'subject to an annual adjustment of up to five percent (5%)',
    confidence: 93, status: 'CONFIDENT',
  },
  'con-enterprise-cap': {
    id: 'con-enterprise-cap', type: 'Constraint', doc: 'enterprise', section: '1', sectionRef: 'e1',
    statement: 'Enterprise Payment Term may not exceed the approved cap without VP Finance sign-off.',
    evidenceTemplate: 'the Payment Term may not exceed {CAP} without prior written approval from VP Finance',
    confidence: 96, status: 'CONFIDENT', comparator: 'max', capValue: 90,
  },
};

// Directed edges. Doc ids and object ids share one namespace.
// `class` marks how the edge participates in impact traversal vs. conflict
// forecasting — see engine.js PROPAGATION for what each class means.
const EDGES = [
  { from: 'agreement', to: 'obl-payment', type: 'CONTAINS', class: 'structural' },
  { from: 'invoice', to: 'clm-invoice-net30', type: 'CONTAINS', class: 'structural' },
  { from: 'clm-invoice-net30', to: 'obl-payment', type: 'DERIVED_FROM', class: 'strong' },
  { from: 'sales', to: 'req-sales-45', type: 'CONTAINS', class: 'structural' },
  { from: 'obl-payment', to: 'req-sales-45', type: 'CONTRADICTS', class: 'conflict' },
  { from: 'renewal', to: 'dep-renewal', type: 'CONTAINS', class: 'structural' },
  { from: 'dep-renewal', to: 'obl-payment', type: 'DEPENDS_ON', class: 'strong' },
  { from: 'dep-renewal', to: 'req-sales-45', type: 'DEPENDS_ON', class: 'strong' },
  { from: 'pricing', to: 'obl-adjustment', type: 'CONTAINS', class: 'structural' },
  { from: 'agreement', to: 'pricing', type: 'REFERENCES', class: 'weak' },
  { from: 'agreement', to: 'renewal', type: 'REFERENCES', class: 'weak' },
  { from: 'enterprise', to: 'con-enterprise-cap', type: 'CONTAINS', class: 'structural' },
  { from: 'obl-payment', to: 'con-enterprise-cap', type: 'CONSTRAINED_BY', class: 'conflict' },
];

const POS = {
  agreement: [200, 110], pricing: [55, 110], 'obl-adjustment': [55, 230],
  'obl-payment': [430, 275], 'clm-invoice-net30': [640, 130], invoice: [820, 75],
  'req-sales-45': [640, 400], sales: [820, 455], 'dep-renewal': [200, 400], renewal: [55, 460],
  enterprise: [430, 495], 'con-enterprise-cap': [430, 400],
};

module.exports = { ENTITIES, DOC_TEXT, DOC_META, REQUIRED_SECTIONS, OBJECTS, EDGES, POS };
