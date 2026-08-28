"""Paraphrased synthetic document generator.

Generates documents that express the SAME underlying facts (same rate,
same tenure, same parties, same conflicts) as a SyntheticPile, but
with meaningfully different sentence structure and phrasing.

Purpose: expose gaps in regex-based extraction. If the extractor only
works because documents happen to use a specific template's wording,
it will fail on these paraphrased versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from tests.synthetic.generator import (
    ConflictEntry,
    ConflictManifest,
    GroundTruthFact,
    SyntheticDocument,
    SyntheticPile,
    _format_ext,
)


@dataclass
class ParaphrasedPile:
    """A pile with same facts as a reference pile but different wording."""

    documents: list[SyntheticDocument] = field(default_factory=list)
    manifest: ConflictManifest = field(default_factory=ConflictManifest)
    # Map from field_name → (original_text_snippet, paraphrased_text_snippet)
    phrasing_changes: dict[str, tuple[str, str]] = field(default_factory=dict)


class ParaphrasedDocumentGenerator:
    """Generates documents that express facts with non-template wording.

    Same values, same structure, different sentence patterns. These
    documents are written the way a real human might draft them —
    not following the rigid "Field Label: Value" template that the
    regex extractors expect.
    """

    def generate(
        self,
        *,
        loan_id: str = "MFL-777888",
        borrower_name: str = "Priya Sharma",
        lender_name: str = "MicroFinance Partners Ltd.",
        principal: int = 150000,
        interest_rate: float = 18.50,
        tenure_months: int = 24,
        processing_fee: float = 3000.0,
        penal_rate: float = 24.50,
        loan_date: date = date(2023, 3, 15),
        new_rate: float = 14.00,
        moratorium_months: int = 3,
        mod_date: date = date(2023, 8, 1),
    ) -> ParaphrasedPile:
        """Generate a paraphrased pile with the same values as would be
        produced by SyntheticDocumentGenerator with these parameters."""

        repayment_start = mod_date + timedelta(days=45)
        documents: list[SyntheticDocument] = []

        # --- Document 1: Loan Agreement (narrative style) ---
        loan_doc = self._generate_narrative_loan(
            loan_id=loan_id,
            borrower_name=borrower_name,
            lender_name=lender_name,
            principal=principal,
            interest_rate=interest_rate,
            tenure_months=tenure_months,
            processing_fee=processing_fee,
            penal_rate=penal_rate,
            loan_date=loan_date,
        )
        documents.append(loan_doc)

        # --- Document 2: Loan Agreement (legal paragraph style) ---
        loan_doc_2 = self._generate_legal_paragraph_loan(
            loan_id=loan_id,
            borrower_name=borrower_name,
            lender_name=lender_name,
            principal=principal,
            interest_rate=interest_rate,
            tenure_months=tenure_months,
            processing_fee=processing_fee,
            penal_rate=penal_rate,
            loan_date=loan_date,
        )
        documents.append(loan_doc_2)

        # --- Document 3: Modification Agreement (letter style) ---
        mod_filename = f"mod_letter_{loan_id}.txt"
        mod_doc = self._generate_letter_style_modification(
            loan_id=loan_id,
            borrower_name=borrower_name,
            lender_name=lender_name,
            original_rate=interest_rate,
            new_rate=new_rate,
            moratorium_months=moratorium_months,
            effective_date=mod_date,
            filename=mod_filename,
        )
        documents.append(mod_doc)

        # --- Document 4: Repayment Statement (prose + table) ---
        repay_filename_1 = f"payment_summary_{loan_id}.txt"
        repay_doc_1 = self._generate_prose_repayment(
            loan_id=loan_id,
            borrower_name=borrower_name,
            principal=principal,
            interest_rate=interest_rate,  # Original rate (conflict)
            start_date=repayment_start,
            filename=repay_filename_1,
        )
        documents.append(repay_doc_1)

        # --- Document 5: Repayment Statement (second period, different layout) ---
        repay_start_2 = repayment_start + timedelta(days=90)
        repay_filename_2 = f"payment_record_{loan_id}.txt"
        repay_doc_2 = self._generate_narrative_repayment(
            loan_id=loan_id,
            borrower_name=borrower_name,
            principal=principal,
            interest_rate=interest_rate,
            start_date=repay_start_2,
            filename=repay_filename_2,
        )
        documents.append(repay_doc_2)

        # Conflicts are the same as the template pile
        conflicts = [
            ConflictEntry(
                field_name="interest_rate",
                expected_value=f"{new_rate:.2f}%",
                contradicting_value=f"{interest_rate:.2f}%",
                modification_filename=mod_filename,
                repayment_filename=repay_filename_1,
            ),
            ConflictEntry(
                field_name="moratorium_period_months",
                expected_value=str(moratorium_months),
                contradicting_value="0",
                modification_filename=mod_filename,
                repayment_filename=repay_filename_1,
            ),
        ]

        phrasing_changes = {
            "borrower_name": (
                "Borrower Name: Priya Sharma",
                "This agreement is entered into by Priya Sharma (hereinafter 'the Client')",
            ),
            "interest_rate": (
                "Interest Rate: 18.50% per annum",
                "The applicable rate of interest shall be eighteen point five percent (18.50%) on an annual basis",
            ),
            "principal_amount": (
                "Principal Amount: ₹1,50,000",
                "a sum of one lakh fifty thousand rupees (INR 150,000.00) as the loan corpus",
            ),
            "tenure_months": (
                "Tenure: 24 months",
                "repayable over a duration of twenty-four (24) calendar months",
            ),
            "processing_fee": (
                "Processing Fee: ₹3,000",
                "an administrative charge amounting to INR 3,000",
            ),
            "moratorium": (
                "Moratorium of 3 months granted",
                "a payment holiday spanning three months is hereby extended to the client",
            ),
        }

        return ParaphrasedPile(
            documents=documents,
            manifest=ConflictManifest(conflicts=conflicts),
            phrasing_changes=phrasing_changes,
        )

    def _generate_narrative_loan(
        self,
        loan_id: str,
        borrower_name: str,
        lender_name: str,
        principal: int,
        interest_rate: float,
        tenure_months: int,
        processing_fee: float,
        penal_rate: float,
        loan_date: date,
    ) -> SyntheticDocument:
        """Loan agreement written in flowing narrative paragraphs.

        Avoids the "Field: Value" format entirely. Uses natural language
        sentences, embedded values, and varied phrasing.
        """
        filename = f"loan_narrative_{loan_id}_1.txt"

        text = (
            f"CREDIT FACILITY AGREEMENT\n"
            f"Reference Number: {loan_id}\n"
            f"Dated: {loan_date.strftime('%d %B %Y')}\n\n"
            f"This agreement is entered into by {borrower_name} (hereinafter "
            f"'the Client') and {lender_name} (hereinafter 'the Institution').\n\n"
            f"The Institution agrees to extend a credit facility to the Client "
            f"in the form of a term loan. The total amount sanctioned under this "
            f"facility shall be a sum of one lakh fifty thousand rupees "
            f"(INR {principal:,.2f}) as the loan corpus, disbursed in a single "
            f"tranche upon execution of this agreement.\n\n"
            f"The applicable rate of interest shall be eighteen point five percent "
            f"({interest_rate:.2f}%) on an annual basis, computed using the "
            f"diminishing balance method. This rate is fixed for the entire duration "
            f"of the agreement unless modified by a subsequent written amendment.\n\n"
            f"The Client undertakes to repay the entire outstanding amount, inclusive "
            f"of accrued interest, over a duration of twenty-four ({tenure_months}) "
            f"calendar months from the date of first disbursement. Installments are "
            f"due on a monthly cycle.\n\n"
            f"Upon execution of this agreement, an administrative charge amounting "
            f"to INR {processing_fee:,.2f} shall be deducted from the disbursement "
            f"proceeds as a one-time service fee for processing the application.\n\n"
            f"Should the Client fail to remit any installment by its due date, "
            f"an additional interest charge of {penal_rate:.2f}% per annum shall "
            f"be levied on the overdue amount for the period of default.\n\n"
            f"Both parties affix their signatures below in acknowledgment.\n"
            f"Client: _____________  Institution: _____________\n"
            f"Witness: _____________\n"
        )

        facts = self._find_facts(text, {
            "borrower_name": borrower_name,
            "lender_name": lender_name,
            "principal_amount": f"{principal:,.2f}",
            "interest_rate": f"{interest_rate:.2f}%",
            "tenure_months": str(tenure_months),
            "processing_fee": f"{processing_fee:,.2f}",
            "penal_rate": f"{penal_rate:.2f}%",
        })

        return SyntheticDocument(
            filename=filename,
            document_type="loan_agreement",
            format="text",
            content=text.encode("utf-8"),
            text_content=text,
            ground_truth_facts=facts,
        )

    def _generate_legal_paragraph_loan(
        self,
        loan_id: str,
        borrower_name: str,
        lender_name: str,
        principal: int,
        interest_rate: float,
        tenure_months: int,
        processing_fee: float,
        penal_rate: float,
        loan_date: date,
    ) -> SyntheticDocument:
        """Loan agreement in dense legal paragraph style.

        Values appear mid-sentence with different surrounding phrases.
        """
        filename = f"loan_legal_{loan_id}_2.txt"

        text = (
            f"TERM LOAN AGREEMENT (Ref: {loan_id})\n\n"
            f"Executed on the {loan_date.strftime('%d')} day of "
            f"{loan_date.strftime('%B, %Y')} between the parties described below.\n\n"
            f"WHEREAS {lender_name}, a non-banking financial company registered "
            f"under the laws of India, agrees to advance funds to {borrower_name}, "
            f"an individual residing at the address on file.\n\n"
            f"NOW THEREFORE, in consideration of the mutual covenants herein, the "
            f"parties agree as follows:\n\n"
            f"1. DISBURSEMENT: The total loan amount to be disbursed is "
            f"Rs. {principal:,}/- (Rupees {self._amount_in_words(principal)} only), "
            f"less applicable deductions.\n\n"
            f"2. COST OF FUNDS: Interest accrues at {interest_rate:.2f} percent "
            f"per annum on the reducing outstanding principal. The annual "
            f"percentage rate inclusive of all charges is also {interest_rate:.2f}%.\n\n"
            f"3. REPAYMENT SCHEDULE: The entire facility must be liquidated within "
            f"a period not exceeding {tenure_months} months. The borrower shall "
            f"tender equal monthly installments.\n\n"
            f"4. UPFRONT CHARGES: A non-refundable fee of Rs. {processing_fee:,.2f}/- "
            f"is payable towards administrative and documentation expenses prior to "
            f"first disbursement.\n\n"
            f"5. DEFAULT CONSEQUENCES: Upon default in payment of any two consecutive "
            f"installments, punitive interest at the rate of {penal_rate:.2f}% p.a. "
            f"shall be charged on the entire arrears from the date of first default.\n\n"
            f"IN WITNESS WHEREOF the parties have set their hands.\n"
        )

        facts = self._find_facts(text, {
            "borrower_name": borrower_name,
            "lender_name": lender_name,
            "principal_amount": f"{principal:,}",
            "interest_rate": f"{interest_rate:.2f}%",
            "tenure_months": str(tenure_months),
            "processing_fee": f"{processing_fee:,.2f}",
            "penal_rate": f"{penal_rate:.2f}%",
        })

        return SyntheticDocument(
            filename=filename,
            document_type="loan_agreement",
            format="text",
            content=text.encode("utf-8"),
            text_content=text,
            ground_truth_facts=facts,
        )

    def _generate_letter_style_modification(
        self,
        loan_id: str,
        borrower_name: str,
        lender_name: str,
        original_rate: float,
        new_rate: float,
        moratorium_months: int,
        effective_date: date,
        filename: str,
    ) -> SyntheticDocument:
        """Modification agreement written as a formal business letter.

        Uses natural language descriptions of the changes rather than
        "changed from X to Y" template patterns.
        """
        text = (
            f"{lender_name}\n"
            f"Corporate Office\n"
            f"Mumbai, India\n\n"
            f"Date: {effective_date.strftime('%d %B %Y')}\n\n"
            f"To,\n"
            f"{borrower_name}\n"
            f"[Address on file]\n\n"
            f"Subject: Revision of Terms — Loan Account {loan_id}\n\n"
            f"Dear {borrower_name.split()[0]},\n\n"
            f"Further to your request dated "
            f"{(effective_date - timedelta(days=30)).strftime('%d %B %Y')} "
            f"and subsequent discussions with our relationship manager, we are "
            f"pleased to inform you of the following revisions to the terms "
            f"governing your loan facility bearing reference {loan_id}.\n\n"
            f"Firstly, considering the prevailing market conditions and your "
            f"satisfactory repayment track record, the annual interest applicable "
            f"to your account will be brought down to {new_rate:.2f}% with "
            f"immediate effect. The earlier rate of {original_rate:.2f}% stands "
            f"superseded as of {effective_date.isoformat()}.\n\n"
            f"Secondly, in recognition of the temporary financial hardship you "
            f"have communicated, a payment holiday spanning {moratorium_months} "
            f"months is hereby extended to you. During this window, commencing "
            f"{effective_date.isoformat()}, no installment — whether towards "
            f"principal or interest — shall be required of you.\n\n"
            f"All other covenants of the original agreement continue to remain "
            f"in full force and effect.\n\n"
            f"Please sign and return the enclosed duplicate copy as your "
            f"acceptance of these revised terms.\n\n"
            f"Yours faithfully,\n"
            f"Authorized Signatory\n"
            f"{lender_name}\n"
        )

        facts = self._find_facts(text, {
            "original_loan_reference": loan_id,
            "new_interest_rate": f"{new_rate:.2f}%",
            "original_interest_rate": f"{original_rate:.2f}%",
            "moratorium_period_months": str(moratorium_months),
            "effective_date": effective_date.isoformat(),
        })

        return SyntheticDocument(
            filename=filename,
            document_type="modification_agreement",
            format="text",
            content=text.encode("utf-8"),
            text_content=text,
            ground_truth_facts=facts,
        )

    def _generate_prose_repayment(
        self,
        loan_id: str,
        borrower_name: str,
        principal: int,
        interest_rate: float,
        start_date: date,
        filename: str,
    ) -> SyntheticDocument:
        """Repayment statement with a prose summary and non-standard table.

        Uses tab-separated columns with different header names than expected.
        """
        monthly_rate = interest_rate / 100 / 12
        outstanding = float(principal)

        # Generate 3 payment rows
        rows_data = []
        payment_date = start_date
        for i in range(3):
            interest_component = outstanding * monthly_rate
            principal_component = outstanding / 12
            amount = round(interest_component + principal_component, 2)
            outstanding = max(0.0, outstanding - amount)
            rows_data.append({
                "date": payment_date.isoformat(),
                "amount": f"{amount:.2f}",
                "penalty": "0.00",
                "remaining": f"{outstanding:.2f}",
            })
            payment_date = payment_date + timedelta(days=30)

        # Build prose header + table
        text = (
            f"PAYMENT HISTORY — Account {loan_id}\n"
            f"Account Holder: {borrower_name}\n"
            f"Period covered: {start_date.isoformat()} through {payment_date.isoformat()}\n"
            f"Rate applied for this period: {interest_rate:.2f}% annually\n\n"
            f"Below is a summary of payments received during the statement period.\n\n"
            f"Due Date\tRemitted Amount\tPenalty Charged\tBalance Remaining\n"
        )

        for row in rows_data:
            text += f"{row['date']}\t{row['amount']}\t{row['penalty']}\t{row['remaining']}\n"

        text += (
            f"\nEnd of statement. For queries, contact your branch.\n"
        )

        facts = self._find_facts(text, {
            "loan_reference": loan_id,
            "borrower_name": borrower_name,
            "interest_rate_applied": f"{interest_rate:.2f}%",
        })

        return SyntheticDocument(
            filename=filename,
            document_type="repayment_statement",
            format="text",
            content=text.encode("utf-8"),
            text_content=text,
            ground_truth_facts=facts,
        )

    def _generate_narrative_repayment(
        self,
        loan_id: str,
        borrower_name: str,
        principal: int,
        interest_rate: float,
        start_date: date,
        filename: str,
    ) -> SyntheticDocument:
        """Repayment statement as a narrative paragraph with embedded data.

        No table at all — facts are stated in prose form.
        """
        monthly_rate = interest_rate / 100 / 12
        outstanding = float(principal)

        rows_data = []
        payment_date = start_date
        for i in range(3):
            interest_component = outstanding * monthly_rate
            principal_component = outstanding / 12
            amount = round(interest_component + principal_component, 2)
            outstanding = max(0.0, outstanding - amount)
            rows_data.append({
                "date": payment_date,
                "amount": amount,
                "remaining": outstanding,
            })
            payment_date = payment_date + timedelta(days=30)

        # Build a fully narrative statement
        text = (
            f"To: {borrower_name}\n"
            f"Re: Loan Account {loan_id} — Repayment Record\n\n"
            f"This letter serves as a record of payments received against "
            f"your loan account during the quarter commencing "
            f"{start_date.strftime('%B %Y')}. The interest is calculated at "
            f"a rate of {interest_rate:.2f}% per annum.\n\n"
        )

        for i, row in enumerate(rows_data, 1):
            text += (
                f"On {row['date'].strftime('%d %B %Y')}, a payment of "
                f"INR {row['amount']:,.2f} was received and credited to your "
                f"account. After application of this payment, the outstanding "
                f"principal stands at INR {row['remaining']:,.2f}.\n\n"
            )

        text += (
            f"We thank you for your continued prompt servicing of this facility.\n"
            f"Regards,\n"
            f"Collections Department\n"
        )

        facts = self._find_facts(text, {
            "loan_reference": loan_id,
            "borrower_name": borrower_name,
            "interest_rate_applied": f"{interest_rate:.2f}%",
        })

        return SyntheticDocument(
            filename=filename,
            document_type="repayment_statement",
            format="text",
            content=text.encode("utf-8"),
            text_content=text,
            ground_truth_facts=facts,
        )

    def _find_facts(
        self, text: str, field_values: dict[str, str]
    ) -> list[GroundTruthFact]:
        """Find positions of known values in text."""
        facts: list[GroundTruthFact] = []
        for field_name, value in field_values.items():
            start = text.find(value)
            if start != -1:
                facts.append(GroundTruthFact(
                    field_name=field_name,
                    value=value,
                    start_offset=start,
                    end_offset=start + len(value),
                ))
        return facts

    def _amount_in_words(self, amount: int) -> str:
        """Simple conversion for common loan amounts."""
        if amount >= 100000:
            lakhs = amount // 100000
            remainder = amount % 100000
            if remainder == 0:
                return f"{lakhs} lakh"
            elif remainder >= 1000:
                thousands = remainder // 1000
                return f"{lakhs} lakh {thousands} thousand"
            return f"{lakhs} lakh {remainder}"
        elif amount >= 1000:
            thousands = amount // 1000
            return f"{thousands} thousand"
        return str(amount)
