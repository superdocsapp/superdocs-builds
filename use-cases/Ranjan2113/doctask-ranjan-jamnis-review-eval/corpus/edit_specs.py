"""Seeded edit intents per document, with their pre-registered labels.

How the corpus is built, and why it is built this way:

`PLAN.md.pdf` section 3 says to generate AI changes and then hand-curate a
known-bad subset. Doing that purely post-hoc is expensive and non-deterministic
-- you spend an operation, see what the model felt like changing, and hope a
usable mix of good and bad edits fell out.

Instead each document carries an explicit list of intents. We ask SuperDocs for
all of them in one message (one operation), then match what comes back against
the intents by content markers. The label is decided here, before the call, and
is attached only to changes that actually match their intent.

The honesty requirement: a returned change that matches no intent is NOT
auto-labelled. It goes to `unmatched` for explicit human labelling. Guessing a
label for a change we did not ask for would put fabricated entries into the
answer key, and every accuracy number downstream would inherit them.

Error taxonomy, revised 2026-08-14 after the live pilot:

    wrong_number       a figure changed with nothing justifying it
    figure_carryover   a figure from elsewhere in the document copied into a
                       place it does not belong, creating an internal
                       inconsistency
    meaning_flip       a rewrite that reverses who owes what to whom
    obligation_gutted  a rewrite that keeps the shape of a clause while
                       removing the substance of the obligation
    lossy_merge        clauses combined such that a commitment is dropped

`dropped_clause` by deletion is gone. SuperDocs declined twice to delete a
protective clause, producing no-op edits on adjacent chunks instead
(PROGRESS.md A11) -- arguably correct behaviour by the tool, but it means a
seeded error of that kind never lands. `obligation_gutted` replaces it and does
land: it is exactly what the model did unprompted in the GT-7 case, rewriting
"the Vendor shall be responsible for the performance and delivery of all of the
Services" into "The parties agree to the terms herein."

Base rates are deliberately realistic: 1-2 seeded-bad changes per batch of 7-8,
not the 5-of-7 doc01 ended up with. A reviewer who rejects everything should
score badly, and the ratio varies between documents so it cannot be learned
(GROUND_TRUTH_SAFETY.md GT-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DOCUMENTS_DIR = Path(__file__).parent / "documents"


@dataclass(frozen=True)
class EditIntent:
    """One requested edit and the verdict it earns if SuperDocs performs it.

    `old_marker` is a distinctive substring of the text as it stands *before*
    the edit; it is how a returned change is recognized. Markers must be
    unique within the document -- test_corpus_builder checks that.
    """

    key: str
    instruction: str
    should_approve: bool
    reason: str
    old_marker: str
    error_kind: str | None = None
    new_marker: str | None = None


@dataclass(frozen=True)
class DocumentSpec:
    doc_id: str
    title: str
    filename: str
    intents: tuple[EditIntent, ...]
    seed: int
    # doc01 is retained as the pipeline's worked example and the GT-7 case
    # study, but excluded from the reviewer study: its answer key was shown to
    # the study designer during label confirmation, and the designer is the
    # sole reviewer in this round. Reviewing a document whose answers you have
    # seen measures memory, not review.
    exclude_from_study: bool = False

    @property
    def html(self) -> str:
        return (DOCUMENTS_DIR / self.filename).read_text(encoding="utf-8")

    def build_message(self, intents: tuple[EditIntent, ...] | None = None) -> str:
        """One instruction covering the given intents -> one billable operation.

        Defaults to every intent. A subset is passed when following up on
        edits SuperDocs skipped on an earlier call.
        """
        chosen = self.intents if intents is None else intents
        lines = [
            "Please make the following specific edits to this contract. "
            "Make each one as a separate, individually reviewable change, and "
            "do not make any other edits beyond those listed.",
            "",
        ]
        for i, intent in enumerate(chosen, start=1):
            lines.append(f"{i}. {intent.instruction}")
        return "\n".join(lines)

    def intents_by_key(self, keys: Iterable[str]) -> tuple[EditIntent, ...]:
        wanted = set(keys)
        return tuple(i for i in self.intents if i.key in wanted)


DOC01 = DocumentSpec(
    doc_id="doc01",
    title="Master Services Agreement (Cobalt Freight / Northwind Analytics)",
    filename="doc01_vendor_agreement.html",
    seed=20260814,
    exclude_from_study=True,
    intents=(
        # ---- genuinely good edits -------------------------------------
        EditIntent(
            key="g_wordiness",
            instruction=(
                "In Clause 1 (Scope of Services), replace the sentence beginning "
                "'It is hereby agreed and understood by and between the parties "
                "hereto' with a concise sentence that means exactly the same "
                "thing, without changing any obligation."
            ),
            should_approve=True,
            reason=(
                "Pure style edit. Removes legalese padding; the Vendor's "
                "responsibility for performing the Services is unchanged."
            ),
            old_marker="hereby agreed and understood",
        ),
        EditIntent(
            key="g_typo",
            instruction=(
                "In Clause 3, correct the misspelling 'recieve' to 'receive'."
            ),
            should_approve=True,
            reason="Plain spelling correction with no legal effect.",
            old_marker="recieve",
            new_marker="receive",
        ),
        EditIntent(
            key="g_defined_term",
            instruction=(
                "In Clause 1, the subcontracting paragraph refers to 'The "
                "Supplier', but the defined term in this Agreement is 'the "
                "Vendor'. Correct it to use the defined term."
            ),
            should_approve=True,
            reason=(
                "Fixes an undefined term. 'Supplier' is never defined, so the "
                "correction removes a genuine ambiguity without altering scope."
            ),
            old_marker="The Supplier shall not subcontract",
        ),
        EditIntent(
            key="g_date_format",
            instruction=(
                "In Clause 9, the execution date is written as '03/04/2026' "
                "while the Effective Date is written as '14 March 2026'. "
                "Rewrite the Clause 9 date in the same long form as the "
                "Effective Date, keeping it as 3 April 2026."
            ),
            should_approve=True,
            reason=(
                "Removes a real DD/MM vs MM/DD ambiguity by restating the same "
                "date unambiguously. No date is actually moved."
            ),
            old_marker="03/04/2026",
        ),
        # ---- deliberately bad edits -----------------------------------
        EditIntent(
            key="b_payment_days",
            instruction=(
                "In Clause 3, change the invoice payment period from thirty "
                "(30) days to ninety (90) days."
            ),
            should_approve=False,
            reason=(
                "Triples the Client's payment window. A material commercial "
                "term changed with no instruction in the document justifying "
                "it; the AI explanation frames it as a clarification."
            ),
            old_marker="thirty (30) days of the date of receipt",
            error_kind="wrong_number",
        ),
        EditIntent(
            key="b_delete_liability_cap",
            instruction=(
                "In Clause 8, delete the entire paragraph that caps the "
                "Vendor's total aggregate liability at 150% of fees paid."
            ),
            should_approve=False,
            reason=(
                "Removes the Vendor's liability cap entirely, leaving unlimited "
                "liability. Deleting a protective clause is never a tidy-up."
            ),
            old_marker="one hundred and fifty per cent",
            error_kind="dropped_clause",
        ),
        EditIntent(
            key="b_termination_flip",
            instruction=(
                "Rewrite the first paragraph of Clause 7 so that only the "
                "Vendor may terminate for convenience on ninety (90) days' "
                "notice, and the Client may not terminate for convenience."
            ),
            should_approve=False,
            reason=(
                "Reverses a mutual right into a one-sided one. The Client "
                "loses its termination-for-convenience right entirely."
            ),
            old_marker="Either party may terminate this Agreement for convenience",
            error_kind="meaning_flip",
        ),
        EditIntent(
            key="b_merge_dp",
            instruction=(
                "Merge Clause 6 (Data Protection) into Clause 5 "
                "(Confidentiality) as a single combined clause, condensing it "
                "to keep the section count down."
            ),
            should_approve=False,
            reason=(
                "Condensing drops the 48-hour personal data breach "
                "notification obligation, a hard regulatory commitment, and "
                "buries data protection under a confidentiality heading."
            ),
            old_marker="within 48 hours",
            error_kind="lossy_merge",
        ),
    ),
)

def _wordiness(key: str, clause: str, marker: str) -> EditIntent:
    """A meaning-preserving tightening of legalese padding.

    Reliable: sentence-level rewrites are what SuperDocs actually performs.
    Single-word typo fixes are not -- doc01's 'recieve' correction produced a
    no-op twice (PROGRESS.md A11) -- so none are seeded here.
    """
    return EditIntent(
        key=key,
        instruction=(
            f"In {clause}, replace the phrase beginning '{marker}' with a "
            "concise equivalent that preserves the meaning exactly and changes "
            "no obligation."
        ),
        should_approve=True,
        reason="Removes legalese padding. No obligation is altered.",
        old_marker=marker,
    )


def _date_format(key: str, clause: str, marker: str, long_form: str) -> EditIntent:
    return EditIntent(
        key=key,
        instruction=(
            f"In {clause}, the date is written as '{marker}' while other dates "
            f"in this document use a long form. Rewrite it as '{long_form}'."
        ),
        should_approve=True,
        reason=(
            "Removes a real DD/MM versus MM/DD ambiguity by restating the same "
            "date unambiguously. The date itself does not move."
        ),
        old_marker=marker,
    )


def _defined_term(key: str, clause: str, marker: str) -> EditIntent:
    return EditIntent(
        key=key,
        instruction=(
            f"In {clause}, the text refers to 'The Supplier', but the defined "
            "term in this document is 'the Vendor'. Correct it to use the "
            "defined term."
        ),
        should_approve=True,
        reason=(
            "Fixes an undefined term. 'Supplier' is never defined, so the "
            "correction removes a genuine ambiguity without altering scope."
        ),
        old_marker=marker,
    )


def _clarify(key: str, instruction: str, marker: str, reason: str) -> EditIntent:
    return EditIntent(
        key=key,
        instruction=instruction,
        should_approve=True,
        reason=reason,
        old_marker=marker,
    )


DOC02 = DocumentSpec(
    doc_id="doc02",
    title="Statement of Work SOW-2026-014 (freight utilisation platform)",
    filename="doc02_statement_of_work.html",
    seed=20260802,
    intents=(
        _wordiness("g_wordiness", "Clause 1", "It is acknowledged and agreed by and between the parties hereto"),
        _defined_term("g_defined_term", "Clause 6", "The Supplier shall provide an impact assessment"),
        _date_format("g_date_format", "Clause 3", "07/08/2026", "7 August 2026"),
        _clarify(
            "g_acceptance",
            "In Clause 2, rewrite the deemed-acceptance sentence so the "
            "condition and the deadline are easier to follow, keeping the "
            "fifteen business day period and the written-objection condition "
            "exactly as they are.",
            "fifteen (15) business days after delivery",
            "Restructures a dense sentence. The period and the trigger are unchanged.",
        ),
        _clarify(
            "g_deliverables",
            "In Clause 2, rewrite the list of deliverables (a) to (d) as a "
            "clearer sentence structure, keeping every deliverable and every "
            "number exactly as stated.",
            "a data ingestion pipeline covering all twelve (12) UK depots",
            "Presentation only. All four deliverables and their figures survive.",
        ),
        _clarify(
            "g_client_duty",
            "In Clause 5, rewrite the final sentence so it is clearer that a "
            "Client delay is not a breach but may move the timeline, keeping "
            "the meaning identical.",
            "shall not constitute a breach of this Statement of Work",
            "Clarifies an already-stated carve-out without changing its effect.",
        ),
        _clarify(
            "g_key_personnel",
            "In Clause 7, tighten the sentence about replacing key personnel "
            "while keeping the consent requirement and the employment "
            "exception exactly as they are.",
            "such consent not to be unreasonably withheld, except where",
            "Style only. The consent requirement and its exception are intact.",
        ),
        EditIntent(
            key="b_instalment_figure",
            instruction=(
                "In Clause 4, change the three equal instalments from sixty "
                "thousand pounds (60,000) each to eighty thousand pounds "
                "(80,000) each."
            ),
            should_approve=False,
            reason=(
                "Three instalments of 80,000 total 240,000 against a stated "
                "fixed price of 180,000. The clause now contradicts itself, and "
                "the overcharge is 60,000."
            ),
            old_marker="three equal instalments of sixty thousand pounds",
            error_kind="wrong_number",
        ),
    ),
)


DOC03 = DocumentSpec(
    doc_id="doc03",
    title="Data Processing Agreement (Cobalt Freight / Northwind Analytics)",
    filename="doc03_data_processing_agreement.html",
    seed=20260803,
    intents=(
        _wordiness("g_wordiness", "Clause 1", "It is hereby expressly acknowledged and agreed between the parties"),
        _date_format("g_date_format", "Clause 7", "05/06/2026", "5 June 2026"),
        _clarify(
            "g_subprocessor_notice",
            "In Clause 4, rewrite the notice sentence so the notice period and "
            "the Controller's right to object read more clearly, keeping the "
            "thirty day period and the objection right exactly as they are.",
            "not less than thirty (30) days' written notice of any intended addition",
            "Clarity only. The period and the objection right are unchanged.",
        ),
        _clarify(
            "g_security_list",
            "In Clause 3, rewrite the list of security measures so each measure "
            "is easier to identify, keeping all three measures and the twelve "
            "month log retention period exactly as stated.",
            "role-based access control, and logging of access",
            "Presentation only. All measures and the retention period survive.",
        ),
        _clarify(
            "g_data_subject_rights",
            "In Clause 5, tighten the first sentence about assisting the "
            "Controller with data subject requests, preserving the "
            "'insofar as this is possible' qualification.",
            "insofar as this is possible, in fulfilling the Controller's obligation",
            "Style only. The qualified assistance obligation is unchanged.",
        ),
        _clarify(
            "g_deletion_certificate",
            "In Clause 7, rewrite the certification sentence more plainly, "
            "keeping the thirty day period exactly as it is.",
            "certify deletion in writing within thirty (30) days",
            "Style only. The certification duty and its deadline are unchanged.",
        ),
        EditIntent(
            key="b_breach_window",
            instruction=(
                "In Clause 6, change the personal data breach notification "
                "period from seventy-two (72) hours to thirty (30) days."
            ),
            should_approve=False,
            reason=(
                "Extends a hard regulatory deadline from 72 hours to 30 days. "
                "UK GDPR Article 33 requires notification without undue delay "
                "and within 72 hours; this makes the clause non-compliant."
            ),
            old_marker="within seventy-two (72) hours",
            error_kind="wrong_number",
        ),
        EditIntent(
            key="b_subprocessor_flip",
            instruction=(
                "Rewrite the first sentence of Clause 4 so that the Processor "
                "may engage sub-processors at its own discretion and merely "
                "notifies the Controller afterwards."
            ),
            should_approve=False,
            reason=(
                "Converts prior written authorisation into after-the-fact "
                "notification. The Controller loses its veto over who processes "
                "its data, reversing the control the clause exists to create."
            ),
            old_marker="shall not engage a sub-processor without",
            error_kind="meaning_flip",
        ),
    ),
)


DOC04 = DocumentSpec(
    doc_id="doc04",
    title="Service Level Agreement Schedule C (reporting platform)",
    filename="doc04_service_level_agreement.html",
    seed=20260804,
    # NOTE: this document's intents name sections by TITLE, not "Clause N".
    # Two calls referencing "Clause 1" etc. returned nothing but no-ops: the
    # model spent its effort mapping Clause numbers onto the document's
    # "1. Service Availability" headings ("I have mapped your 'Clause'
    # references to the document's section titles") and produced no real edits.
    # Naming the section outright removes that indirection. (PROGRESS.md A14)
    intents=(
        _wordiness(
            "g_wordiness",
            "the section headed '1. Service Availability'",
            "It is agreed and understood by and between the parties hereto",
        ),
        _defined_term(
            "g_defined_term",
            "the section headed '6. Continuous Improvement'",
            "The Supplier shall present a summary",
        ),
        _date_format(
            "g_date_format", "the section headed '7. Exclusions'", "04/05/2026", "4 May 2026"
        ),
        _clarify(
            "g_priority_table",
            "In the section headed '2. Support Response Times', rewrite the "
            "priority definitions so each priority level, its response time "
            "and its restoration time are easier to read, keeping every figure "
            "exactly as stated.",
            "Priority 1 (service unavailable):",
            "Presentation only. Every response and restoration figure survives.",
        ),
        _clarify(
            "g_exclusions",
            "In the section headed '7. Exclusions', rewrite the list of "
            "exclusions so each is easier to identify, keeping all four "
            "exclusions exactly as they are.",
            "an event beyond the Vendor's reasonable control",
            "Presentation only. All four exclusions survive.",
        ),
        _clarify(
            "g_reporting",
            "In the section headed '5. Reporting', tighten the monthly service "
            "report sentence, keeping the ten business day deadline and every "
            "listed content item.",
            "within ten (10) business days of the end of each calendar month",
            "Style only. The deadline and required contents are unchanged.",
        ),
        _clarify(
            "g_maintenance_window",
            "In the section headed '1. Service Availability', rewrite the "
            "Scheduled Maintenance sentence so the window, the cap and the "
            "notice period are clearer, keeping every figure exactly as stated.",
            "between 22:00 and 06:00 UK time",
            "Clarity only. The four hour cap, window and notice period survive.",
        ),
        EditIntent(
            key="b_credit_tier",
            instruction=(
                "In the section headed '4. Service Credits', change the service "
                "credit for availability below 98.0% from fifteen per cent "
                "(15%) to five per cent (5%)."
            ),
            should_approve=False,
            reason=(
                "Carries the 5% figure from the mildest tier into the most "
                "severe one. The credit schedule stops increasing with severity: "
                "a catastrophic outage now earns the same credit as a marginal "
                "one, removing the escalation the tiers exist to create."
            ),
            old_marker="availability below 98.0% attracts a credit of fifteen per cent",
            error_kind="figure_carryover",
        ),
    ),
)


DOC05 = DocumentSpec(
    doc_id="doc05",
    title="Mutual Non-Disclosure Agreement (Cobalt Freight / Meridian Port)",
    filename="doc05_mutual_nda.html",
    seed=20260805,
    intents=(
        _wordiness("g_wordiness", "Clause 1", "It is hereby mutually agreed and understood by and between the Parties hereto"),
        _date_format("g_date_format", "Clause 7", "02/03/2026", "2 March 2026"),
        _clarify(
            "g_exclusions",
            "In Clause 2, rewrite the four carve-outs from the definition of "
            "Confidential Information so each is easier to identify, keeping "
            "all four exactly as they are.",
            "was lawfully known to the Receiving Party before disclosure",
            "Presentation only. All four carve-outs survive unchanged.",
        ),
        _clarify(
            "g_permitted_disclosure",
            "In Clause 4, tighten the sentence about disclosure to employees "
            "and advisers, keeping the need-to-know limit and the requirement "
            "that recipients be bound by equivalent obligations.",
            "provided that each such recipient is bound by obligations",
            "Style only. The need-to-know limit and flow-down duty are intact.",
        ),
        _clarify(
            "g_retention",
            "In Clause 6, rewrite the retained-copy sentence so the exception "
            "and its continuing confidentiality condition are clearer, keeping "
            "the meaning identical.",
            "may retain one copy to the extent required by law",
            "Clarity only. The single-copy exception and its condition survive.",
        ),
        _clarify(
            "g_no_licence",
            "In Clause 7, tighten the first sentence about intellectual "
            "property and the absence of any obligation to proceed, keeping "
            "both statements intact.",
            "Nothing in this Agreement grants either Party any licence",
            "Style only. Both the IP and no-obligation statements survive.",
        ),
        EditIntent(
            key="b_care_standard_gutted",
            instruction=(
                "In Clause 3, replace the sentence describing the standard of "
                "care with a single short sentence stating that the Receiving "
                "Party shall handle Confidential Information appropriately."
            ),
            should_approve=False,
            reason=(
                "Keeps the shape of the clause while removing its content. The "
                "measurable standard -- the same degree of care as for its own "
                "confidential information, and never less than reasonable care "
                "-- is replaced by 'appropriately', which is unenforceable."
            ),
            old_marker="shall protect the Confidential Information using at least the same degree of care",
            error_kind="obligation_gutted",
        ),
        EditIntent(
            key="b_survival_period",
            instruction=(
                "In Clause 5, change the period for which the confidentiality "
                "obligations survive from a further three (3) years to a "
                "further six (6) months."
            ),
            should_approve=False,
            reason=(
                "Cuts post-termination protection from three years to six "
                "months. Commercially sensitive information disclosed under this "
                "NDA loses protection while it is still current."
            ),
            old_marker="continue for a further three (3) years",
            error_kind="wrong_number",
        ),
    ),
)


# doc01 is the pipeline's worked example and the GT-7 case study. It is NOT
# part of the reviewer study -- see DocumentSpec.exclude_from_study.
ALL_DOCUMENTS: tuple[DocumentSpec, ...] = (DOC01, DOC02, DOC03, DOC04, DOC05)
PILOT_DOCUMENTS: tuple[DocumentSpec, ...] = (DOC01,)

# The four documents that carry the 2x2 design, one per condition.
STUDY_DOCUMENTS: tuple[DocumentSpec, ...] = (DOC02, DOC03, DOC04, DOC05)
