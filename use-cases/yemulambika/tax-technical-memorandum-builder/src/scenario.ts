import type { TaxCase } from "./domain";

export const scenario: TaxCase = {
  facts: [
    "Fictional Deccan Byteworks Pvt Ltd acquired a demonstration asset on 15 April 2024 for INR 4800000.00 and sold it on 30 June 2026 for INR 6500000.00.",
    "It incurred INR 200000.00 acquisition costs and INR 300000.00 selling expenses. The explicitly calculated taxable amount is INR 1200000.00 (INR 6500000.00 less INR 4800000.00, INR 200000.00 and INR 300000.00).",
  ],
  question:
    "What is the taxable amount on the fictional asset disposal under the attached synthetic authorities?",
  currency: "INR",
  rows: [
    {
      source_row_id: "COST-001",
      label: "Purchase price / cost basis",
      amount: "4800000.00",
    },
    {
      source_row_id: "PROCEEDS-001",
      label: "Sale proceeds",
      amount: "6500000.00",
    },
    {
      source_row_id: "EXP-001",
      label: "Acquisition costs",
      amount: "200000.00",
    },
    {
      source_row_id: "EXP-002",
      label: "Selling expenses",
      amount: "300000.00",
    },
    {
      source_row_id: "CALC-001",
      label: "Taxable amount",
      amount: "1200000.00",
    },
  ],
  authorities: [
    {
      authority_id: "AUTH-001",
      title: "Synthetic Basis Rule",
      authority_type: "fictional legislation",
      citation: "Synthetic Tax Code § 10(1)",
      source_document_id: "synthetic-authority-1",
      exact_quote:
        "The verified acquisition price and direct acquisition costs form the taxpayer's basis in an asset.",
      source_locator: "Section 10(1), paragraph 1",
      verification_status: "UNVERIFIED",
      proposition: "Verified acquisition price and direct costs form basis.",
      attachment_text:
        "SYNTHETIC AUTHORITY — FOR DEMONSTRATION ONLY\nSection 10(1), paragraph 1. The verified acquisition price and direct acquisition costs form the taxpayer's basis in an asset.",
    },
    {
      authority_id: "AUTH-002",
      title: "Synthetic Disposal Proceeds Rule",
      authority_type: "fictional regulation",
      citation: "Synthetic Tax Regulations 24(2)",
      source_document_id: "synthetic-authority-2",
      exact_quote:
        "Taxable disposal proceeds equal consideration received less verified basis and direct disposal expenses.",
      source_locator: "Regulation 24(2), paragraph 3",
      verification_status: "UNVERIFIED",
      proposition:
        "Verified basis and direct disposal expenses reduce proceeds.",
      attachment_text:
        "SYNTHETIC AUTHORITY — FOR DEMONSTRATION ONLY\nRegulation 24(2), paragraph 3. Taxable disposal proceeds equal consideration received less verified basis and direct disposal expenses.",
    },
    {
      authority_id: "AUTH-NEGATIVE",
      title: "Fabricated Quotation Negative Control",
      authority_type: "negative test fixture",
      citation: "Synthetic Tax Bulletin 99",
      source_document_id: "synthetic-authority-negative",
      exact_quote: "Every fictional disposal is automatically exempt from tax.",
      source_locator: "Intentionally absent",
      verification_status: "UNVERIFIED",
      proposition: "Must be rejected and excluded.",
      attachment_text:
        "SYNTHETIC AUTHORITY — FOR DEMONSTRATION ONLY\nThis attachment deliberately does not contain the claimed quotation.",
    },
  ],
};
