"""Locks in the two-signal classification rule and the load-bearing design
property: classification never gates whether transcript is forwarded, only
how it's framed."""

from app.drafting.classifier import ADDITION, CORRECTION, build_instruction, classify

DRAFT = "<h1>Statement of Work</h1><p>Fees: USD 48,000. Start date: 3 September 2026.</p>"


def test_new_information_with_no_cue_is_addition():
    assert classify("The client is Acme Corp.", DRAFT) == ADDITION


def test_correction_cue_alone_is_not_enough():
    # Signal A only — "actually" with nothing overlapping the current draft.
    assert classify("Actually, let's add a warranty clause too.", DRAFT) == ADDITION


def test_value_overlap_alone_is_not_enough():
    # Signal B only — mentions a value already in the draft, but no cue phrase.
    assert classify("USD 48,000 covers the first phase.", DRAFT) == ADDITION


def test_both_signals_together_is_correction():
    assert classify("No, the fee should be USD 60,000.", DRAFT) == CORRECTION


def test_first_utterance_against_an_empty_draft_is_never_a_correction():
    # Nothing to overlap with yet — Signal B can't fire against "".
    assert classify("No, actually let's change the start date.", "") == ADDITION


def test_build_instruction_addition_preserves_and_scopes():
    message = build_instruction(ADDITION, "The client is Acme Corp.")
    assert "Acme Corp" in message
    assert "preserving everything already present" in message
    assert "do not touch unrelated sections" in message.lower()


def test_build_instruction_correction_targets_and_scopes():
    message = build_instruction(CORRECTION, "The fee should be USD 60,000.")
    assert "USD 60,000" in message
    assert "do not duplicate" in message.lower()
    assert "do not touch unrelated sections" in message.lower()


# ---------------------------------------------------------------------------
# Structured instruction layer — section targeting, negation routing,
# correction targeting, structural constraints.
# ---------------------------------------------------------------------------

from app.drafting.classifier import build_structured_instruction

SOW_DRAFT = """<h1>Statement of Work</h1>
<h2>Project Details</h2><table><tr><td><strong>Client</strong></td><td></td></tr></table>
<h2>Executive Summary</h2><p></p>
<h2>Objectives</h2><p></p>
<h2>Scope of Work</h2><p></p>
<h2>Deliverables</h2><p></p>
<h2>Timeline &amp; Milestones</h2><p></p>
<h2>Budget / Commercial Terms</h2><p></p>
<h2>Assumptions &amp; Dependencies</h2><p></p>
<h2>Out of Scope</h2><p></p>
<h2>Next Steps</h2><p></p>"""


def test_section_target_timeline_date():
    msg = build_structured_instruction(
        ADDITION, "The project starts September 15th.", SOW_DRAFT, "statement_of_work"
    )
    assert "[Target: Timeline & Milestones]" in msg


def test_section_target_budget_amount():
    msg = build_structured_instruction(
        ADDITION, "Our total budget is $45,000.", SOW_DRAFT, "statement_of_work"
    )
    assert "[Target: Budget / Commercial Terms]" in msg


def test_section_target_deliverables():
    msg = build_structured_instruction(
        ADDITION, "The deliverables include the website and basic analytics.", SOW_DRAFT, "statement_of_work"
    )
    assert "[Target: Deliverables]" in msg


def test_negation_routes_to_out_of_scope():
    msg = build_structured_instruction(
        ADDITION, "Payment integration is not part of the scope.", SOW_DRAFT, "statement_of_work"
    )
    assert "[Target: Out of Scope]" in msg
    assert "Payment integration" in msg
    assert "[Target: Scope of Work]" not in msg


def test_does_not_include_routes_to_out_of_scope():
    msg = build_structured_instruction(
        ADDITION,
        "The project does not include ongoing marketing, SEO, or content creation after launch.",
        SOW_DRAFT, "statement_of_work",
    )
    assert "[Target: Out of Scope]" in msg
    assert "ongoing marketing, SEO, or content creation" in msg


def test_correction_targets_section_and_explicit_old_value():
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>Project starts September 15th.</p>",
    )
    msg = build_structured_instruction(
        CORRECTION,
        "Actually, the start date is September 20th, not September 15th.",
        draft, "statement_of_work",
    )
    assert 'FIND: "September 15th"' in msg
    assert "September 20th" in msg
    assert "Timeline & Milestones" in msg


def test_correction_without_explicit_old_value_still_targets_section():
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>Project starts September 15th.</p>",
    )
    msg = build_structured_instruction(
        CORRECTION, "Actually, the start date is September 20th.", draft, "statement_of_work"
    )
    assert "REPLACE WITH" in msg


def test_structural_constraints_present():
    msg = build_structured_instruction(
        ADDITION, "The project starts September 15th.", SOW_DRAFT, "statement_of_work"
    )
    assert "NEVER modify" in msg
    assert "section headings" in msg
    assert "NEVER add new rows" in msg
    assert "NEVER add raw transcript sentences verbatim" in msg
    assert "NEVER invent facts" in msg


def test_multiple_sections_targeted_in_one_batch():
    msg = build_structured_instruction(
        ADDITION,
        "The project starts September 15th. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    assert "[Target: Timeline & Milestones]" in msg
    assert "[Target: Budget / Commercial Terms]" in msg


def test_ambiguous_fact_gets_most_appropriate_section():
    msg = build_structured_instruction(
        ADDITION, "We should probably align on the branding approach.", SOW_DRAFT, "statement_of_work"
    )
    assert "most appropriate section" in msg


def test_filler_phrases_stripped_from_facts():
    # The fact bullet is cleaned of conversational openers; the source
    # transcript line keeps the raw text for the LLM's reference.
    msg = build_structured_instruction(
        ADDITION, "Hi, I'd like to discuss a website development project.", SOW_DRAFT, "statement_of_work"
    )
    assert "- Hi, I'd like to discuss" not in msg
    assert "website development project" in msg
    assert 'Source transcript: "Hi, I' in msg


def test_existing_classify_unchanged():
    assert classify("The client is Acme Corp.", DRAFT) == ADDITION
    assert classify("No, the fee should be USD 60,000.", DRAFT) == CORRECTION


def test_build_instruction_unchanged():
    message = build_instruction(ADDITION, "The client is Acme Corp.")
    assert "Acme Corp" in message
    assert "preserving everything already present" in message


# ---------------------------------------------------------------------------
# Section-by-section orchestration — one bounded instruction per target
# section, in live-draft heading order, unmatched facts never dropped.
# ---------------------------------------------------------------------------

from app.drafting.classifier import build_section_instructions


def test_single_section_returns_one_instruction():
    ins = build_section_instructions(
        ADDITION, "The project starts September 15th.", SOW_DRAFT, "statement_of_work"
    )
    assert isinstance(ins, list) and len(ins) == 1
    assert "[Target: Timeline & Milestones]" in ins[0]


def test_two_sections_return_two_instructions_in_draft_order():
    # Budget sentence comes first in the transcript, but the Timeline
    # heading precedes Budget in the live draft — ordering must follow the
    # draft, not the transcript.
    ins = build_section_instructions(
        ADDITION,
        "Our total budget is $45,000. The project starts September 15th.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ins) == 2
    assert "[Target: Timeline & Milestones]" in ins[0]
    assert "[Target: Budget / Commercial Terms]" in ins[1]


def test_three_sections_return_three_instructions():
    ins = build_section_instructions(
        ADDITION,
        "The project starts September 15th. Our total budget is $45,000. "
        "Payment integration is not part of the scope.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ins) == 3
    assert "[Target: Timeline & Milestones]" in ins[0]
    assert "[Target: Budget / Commercial Terms]" in ins[1]
    assert "[Target: Out of Scope]" in ins[2]


def test_unmatched_facts_appended_as_last_instruction():
    ins = build_section_instructions(
        ADDITION,
        "The project starts September 15th. We should align on the branding approach.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ins) == 2
    assert "most appropriate section" in ins[1]
    assert "align on the branding approach" in ins[1]


def test_each_instruction_has_structural_constraints():
    ins = build_section_instructions(
        ADDITION,
        "The project starts September 15th. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    for instruction in ins:
        assert "NEVER modify" in instruction
        assert "section headings" in instruction


def test_each_instruction_has_exactly_one_target():
    ins = build_section_instructions(
        ADDITION,
        "The project starts September 15th. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    for instruction in ins:
        assert instruction.count("[Target:") == 1


def test_correction_always_single_instruction():
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>Project starts September 15th.</p>",
    )
    ins = build_section_instructions(
        CORRECTION, "Actually, the project starts September 20th.", draft, "statement_of_work"
    )
    assert len(ins) == 1
    assert "REPLACE WITH" in ins[0]


def test_zero_targets_returns_single_unmatched_instruction():
    ins = build_section_instructions(
        ADDITION, "We should probably align on the branding approach.", SOW_DRAFT, "statement_of_work"
    )
    assert len(ins) == 1
    assert "most appropriate section" in ins[0]


def test_facts_appear_in_exactly_one_instruction():
    ins = build_section_instructions(
        ADDITION,
        "The project starts September 15th. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    blob = "\n\n".join(ins)
    assert blob.count("- The project starts September 15th.") == 1
    assert blob.count("- Our total budget is $45,000.") == 1


# ---------------------------------------------------------------------------
# Phase 2 routing generalization (70s benchmark defects):
# ambiguous-word routing, fragment filtering, negation variants, templates.
# ---------------------------------------------------------------------------

LEGAL_NOTE = """<h1>Advice Note</h1>
<h2>Matter</h2><p></p>
<h2>Background</h2><p></p>
<h2>Issues</h2><p></p>
<h2>Advice</h2><p></p>
<h2>Risks</h2><p></p>
<h2>Next Actions</h2><p></p>"""


def test_kickoff_routes_to_next_steps_not_timeline():
    # 70s benchmark: "kickoff" was in DATE patterns → hijacked to Timeline.
    ops = build_section_operations(
        ADDITION,
        "We'll have a kickoff meeting next week to finalize requirements.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ops) == 1
    assert ops[0].section == "Next Steps"


def test_milestone_review_routes_to_assumptions_not_timeline():
    # "milestone" in DATE patterns pulled weekly-review content to Timeline.
    # Leaving it unmatched fixed that but handed placement to the LLM, and
    # live runs then split: Assumptions on one run, appended under the
    # Project Details table on the next. Governance content now routes
    # deterministically — still never Timeline, but no longer a coin flip.
    ops = build_section_operations(
        ADDITION,
        "Review each milestone before moving forward.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ops) == 1
    assert ops[0].section == "Assumptions & Dependencies"


def test_client_pricing_routes_to_assumptions_not_budget():
    # "pricing" in BUDGET patterns pulled client-supplied materials to Budget.
    ops = build_section_operations(
        ADDITION,
        "Product pricing will be supplied by the client.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ops) == 1
    assert ops[0].section == "Assumptions & Dependencies"


def test_deliverables_with_pricing_stay_in_deliverables():
    # 70s benchmark: deliverables sentence containing "pricing" went to Budget.
    ops = build_section_operations(
        ADDITION,
        "The deliverables should include the website, payment integration, "
        "mobile responsive design, descriptions, pricing, branding assets, "
        "and access to our existing domain.",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ops) == 1
    assert ops[0].section == "Deliverables"


def test_fragment_our_total_produces_no_operations():
    # 70s benchmark: "Our total" was committed literally to the document.
    ops = build_section_operations(ADDITION, "Our total", SOW_DRAFT, "statement_of_work")
    assert ops == []


def test_fragment_after_launch_produces_no_operations():
    ops = build_section_operations(ADDITION, "After launch.", SOW_DRAFT, "statement_of_work")
    assert ops == []


def test_short_facts_are_retained():
    for text in ["$45,000", "September 15th", "Kickoff next week"]:
        ops = build_section_operations(ADDITION, text, SOW_DRAFT, "statement_of_work")
        assert len(ops) == 1, f"{text!r} must be retained as a fact"
        assert ops[0].facts and ops[0].facts[0].strip()


def test_negation_fragment_not_include_routes_to_out_of_scope():
    # 70s benchmark: "Not include ongoing marketing..." was not recognized.
    ops = build_section_operations(
        ADDITION, "Not include ongoing marketing, SEO, or content creation",
        SOW_DRAFT, "statement_of_work",
    )
    assert len(ops) == 1
    assert ops[0].section == "Out of Scope"


def test_negation_variants_all_route_to_out_of_scope():
    variants = [
        "The project does not include ongoing marketing.",
        "Ongoing marketing doesn't include part of the scope.",
        "Not include SEO.",
        "Marketing isn't part of the scope.",
        "SEO is excluded from the scope.",
        "Ongoing marketing falls outside the scope.",
    ]
    for text in variants:
        ops = build_section_operations(ADDITION, text, SOW_DRAFT, "statement_of_work")
        assert ops and ops[0].section == "Out of Scope", f"{text!r} -> {[o.section for o in ops]}"


def test_legal_note_template_routes_without_sow_headings():
    # Template generalization: a completely non-SOW heading set must still
    # route date/amount facts via live-heading matching.
    ops = build_section_operations(
        ADDITION,
        "The limitation period expires on December 4th. We recommend filing before that date. The fee is 12000 pounds.",
        LEGAL_NOTE, "legal_advice_note",
    )
    # Date + amount facts must not be dropped and must not require SOW headings.
    assert ops, "legal-note facts must produce operations"
    for op in ops:
        assert op.section is None or op.section in LEGAL_NOTE  # only real headings, or unmatched


def test_legal_note_negation_uses_live_out_of_scope_equivalent():
    # A negation in a template with no "Out of Scope" heading must not
    # invent one — it routes to unmatched and the fact is preserved.
    ops = build_section_operations(
        ADDITION, "Legal costs are not included in the matter.", LEGAL_NOTE, "legal_advice_note"
    )
    assert ops, "negation fact must be preserved (unmatched ok)"
    assert ops[0].section is None or "Out of Scope" in LEGAL_NOTE


# ---------------------------------------------------------------------------
# Phase 3 — fact segmentation (ASR boundary recovery), negation/correction
# distinction.
# ---------------------------------------------------------------------------

from app.drafting.classifier import _recover_sentence_boundaries, classify, CORRECTION, ADDITION


def test_boundary_after_launch_we_splits():
    parts = _recover_sentence_boundaries(
        "Marketing SEO or content creation after launch We want to have a kickoff meeting next week"
    )
    assert len(parts) == 2
    assert parts[0] == "Marketing SEO or content creation after launch"
    assert parts[1].startswith("We want to have a kickoff meeting")


def test_boundary_proper_noun_not_split():
    parts = _recover_sentence_boundaries("for Northstar Goods a small company")
    assert len(parts) == 1


def test_boundary_acme_corp_not_split():
    parts = _recover_sentence_boundaries("The client is Acme Corp and the project starts next month")
    assert len(parts) == 1


def test_boundary_date_budget_splits():
    parts = _recover_sentence_boundaries(
        "The project starts September 15th Our total budget is forty-five thousand dollars"
    )
    assert len(parts) == 2
    assert "September 15th" in parts[0]
    assert "budget" in parts[1]


def test_boundary_punctuated_sentence_unchanged():
    parts = _recover_sentence_boundaries(
        "The project starts September 15th and the final website should be delivered by October 30th."
    )
    assert len(parts) == 1


def test_boundary_merged_exclusion_and_next_steps_splits_and_routes():
    # The val6 benchmark's fatal merged batch.
    ops = build_section_operations(
        ADDITION,
        "The project does not include ongoing marketing SEO or content creation after launch "
        "We want to have a kickoff meeting next week finalize the requirements and begin "
        "development immediately after approval",
        SOW_DRAFT, "statement_of_work",
    )
    sections = [o.section for o in ops]
    assert "Out of Scope" in sections
    assert "Next Steps" in sections


def test_negation_not_classified_as_correction():
    # "The project does not include X" is an exclusion, not a repair.
    assert classify("The project does not include ongoing marketing.", SOW_DRAFT) == ADDITION


def test_explicit_correction_still_correction():
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>Project starts September 15th.</p>",
    )
    assert classify("Actually, the start date is September 20th.", draft) == CORRECTION
    assert classify("No, the start date is September 20th.", draft) == CORRECTION


def test_negation_variants_still_correction_free():
    for text in [
        "Payment integration is not part of the scope.",
        "We don't include ongoing marketing.",
        "SEO is excluded from the scope.",
    ]:
        assert classify(text, SOW_DRAFT) == ADDITION, text


def test_should_be_delivered_is_not_a_correction():
    # Obligation/future language ("should be delivered", "should include")
    # must not trigger the correction classifier — even when the draft
    # contains the word "should" (benchmark run 2 false correction).
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>The website should be delivered soon.</p>",
    )
    assert classify(
        "The project should start on September 15th and the final website should be "
        "delivered by October 30th.",
        draft,
    ) == ADDITION


def test_explicit_corrections_still_work_without_should_be_cue():
    draft = SOW_DRAFT.replace(
        "<h2>Timeline &amp; Milestones</h2><p></p>",
        "<h2>Timeline &amp; Milestones</h2><p>The project starts September 15th.</p>",
    ).replace(
        "<h2>Budget / Commercial Terms</h2><p></p>",
        "<h2>Budget / Commercial Terms</h2><p>Fees: USD 48,000.</p>",
    )
    assert classify("Actually, the start date should be September 20th.", draft) == CORRECTION
    assert classify("No, the fee should be USD 60,000.", draft) == CORRECTION
    assert classify("Change the start date to September 20th.", draft) == CORRECTION


# ---------------------------------------------------------------------------
# Filler-only regression (Test 3 validator false-positive): "Hi." must not
# become a required content anchor or reach SuperDocs as a fact.
# ---------------------------------------------------------------------------

from app.drafting.classifier import build_section_operations, is_filler_only
from app.drafting.validator import _fact_anchors


def test_standalone_hi_creates_no_operations():
    ops = build_section_operations(ADDITION, "Hi.", SOW_DRAFT, "statement_of_work")
    assert ops == []


def test_filler_only_batch_skips_superdocs_entirely():
    # Session-level: a filler-only batch must not call SuperDocs or bump the
    # draft version (test_gate-style fake, minimal assertion).
    from test_session import FakeSuperDocsClient
    from app.drafting.session import MeetingSession
    from app.transcript.manual_provider import ManualTranscriptProvider
    import asyncio as _asyncio

    client = FakeSuperDocsClient()
    provider = ManualTranscriptProvider()
    session = MeetingSession(
        "filler-only-uuid", client, provider, manual_provider=provider,
        silence_gap_seconds=0.05, size_ceiling_chars=10_000,
        max_wait_seconds=10, poll_interval_seconds=0.01,
    )

    async def run():
        await session.start()
        await provider.submit("Hi.")
        await _asyncio.sleep(0.3)
        return session

    session = _asyncio.run(run())
    assert client.chat_messages == []  # no SuperDocs edit
    assert session.draft_version == 0  # no version bump
    assert session.activity == []      # no activity


def test_standalone_hello_creates_no_operations():
    ops = build_section_operations(ADDITION, "Hello.", SOW_DRAFT, "statement_of_work")
    assert ops == []


def test_hi_keeps_the_client_name_but_not_the_topic_announcement():
    """"Hi, I'd like to discuss X" announces a topic; it asserts no fact
    about X, and the substance always follows in the next breath.

    This used to produce a section-body op as well, and live runs showed why
    that is wrong: SuperDocs had to invent connective prose to make the
    announcement read as document content, writing "We will be conducting a
    website development project for Northstar Goods, a small e-commerce
    company." into Next Steps. That stray paragraph then failed placement
    validation for every genuine Next Steps edit that followed — nine
    rejections on one run. The client name, the only hard fact in the
    sentence, is still captured by the table-fill op.
    """
    ops = build_section_operations(
        ADDITION, "Hi, I'd like to discuss a website project for Northstar Goods.", SOW_DRAFT, "statement_of_work"
    )
    assert len(ops) == 1
    assert ops[0].table_field == "Client"
    assert ops[0].table_value == "Northstar Goods"


def test_topic_announcement_carrying_a_hard_value_is_still_a_fact():
    # Only the value-free announcement is dropped.
    ops = build_section_operations(
        ADDITION, "Hi, I'd like to discuss the budget of $45,000.", SOW_DRAFT, "statement_of_work"
    )
    body = [o for o in ops if o.table_field is None]
    assert body and "45,000" in " ".join(body[0].facts)


# ---------------------------------------------------------------------------
# Project Details table fill — Client cell was structurally unfillable
# before this: confirmed live (a real "for Northstar" utterance never
# reached the table), fixed by _client_fill_operation.
# ---------------------------------------------------------------------------

from app.drafting.classifier import _client_cell_is_empty, _extract_client_name

FILLED_CLIENT_DRAFT = SOW_DRAFT.replace(
    "<tr><td><strong>Client</strong></td><td></td></tr>",
    "<tr><td><strong>Client</strong></td><td>Acme Corp</td></tr>",
)


def test_extract_client_name_project_for_pattern():
    assert _extract_client_name("This is a website development project for Northstar.") == "Northstar"


def test_extract_client_name_client_is_pattern():
    assert _extract_client_name("The client is Acme Corp and they need a new site.") == "Acme Corp"


def test_extract_client_name_returns_none_without_a_naming_pattern():
    assert _extract_client_name("The project starts September 15th.") is None


def test_extract_client_name_does_not_capture_a_month():
    # "delivered for October." must never be misread as a client name.
    assert _extract_client_name("The site will be delivered for October.") is None


def test_client_cell_is_empty_true_on_starter_template():
    assert _client_cell_is_empty(SOW_DRAFT) is True


def test_client_cell_is_empty_false_once_filled():
    assert _client_cell_is_empty(FILLED_CLIENT_DRAFT) is False


def test_client_fill_op_not_added_when_cell_already_filled():
    ops = build_section_operations(
        ADDITION, "This is a project for Northstar.", FILLED_CLIENT_DRAFT, "statement_of_work"
    )
    assert not any(o.table_field is not None for o in ops)


def test_client_fill_op_not_added_for_correction_batch():
    ops = build_section_operations(
        CORRECTION, "Actually, the project is for Northstar, not Acme.", SOW_DRAFT, "statement_of_work"
    )
    assert not any(o.table_field is not None for o in ops)


def test_client_fill_op_carries_correct_instruction_shape():
    ops = build_section_operations(
        ADDITION, "This is a project for Northstar.", SOW_DRAFT, "statement_of_work"
    )
    table_ops = [o for o in ops if o.table_field is not None]
    assert len(table_ops) == 1
    op = table_ops[0]
    assert op.table_field == "Client"
    assert op.table_value == "Northstar"
    assert op.section == "Project Details"
    assert "Client" in op.instruction
    assert "Northstar" in op.instruction
    assert "Do not add, remove, or reorder any table row" in op.instruction


def test_okay_retains_date_fact():
    ops = build_section_operations(
        ADDITION, "Okay, the project starts September 15th.", SOW_DRAFT, "statement_of_work"
    )
    assert len(ops) == 1
    assert "September 15th" in " ".join(ops[0].facts)


def test_filler_only_fact_has_no_anchors():
    assert _fact_anchors("Hi.") == []
    assert _fact_anchors("Hello.") == []
    assert _fact_anchors("Okay.") == []
    assert is_filler_only("Hi.") is True
    assert is_filler_only("Hi, I'd like to discuss a website project.") is False


def test_validator_does_not_reject_for_missing_filler():
    # The failing Test 3 shape: the batch's fact list included "Hi." — the
    # validator must not require the proposal to contain "hi".
    from app.drafting.validator import validate_proposal
    from app.superdocs.schemas import PendingChange
    ops = build_section_operations(ADDITION, "Hi. The project starts September 15th.", SOW_DRAFT, "statement_of_work")
    assert len(ops) == 1  # filler dropped, date fact retained
    change = PendingChange(
        change_id="c1", operation="create", chunk_id="new",
        new_html="<p>The project starts on September 15th.</p>",
        ai_explanation="added to Timeline",
    )
    ok, fails = validate_proposal(ops[0], change, SOW_DRAFT)
    assert ok, fails


# --- cross-template routing ------------------------------------------------
#
# Routing rules were tuned against the Statement of Work benchmark, which
# left the other four templates running almost entirely on the "most
# appropriate section" fallback — Advice Note had exactly one of its seven
# headings routable, so placement there was whatever the model picked that
# run. These lock in deterministic routing per template, and the SOW cases
# guard against a new rule quietly stealing content from the tuned path.

import re as _re

from app.drafting.templates import _TEMPLATES
from app.drafting.classifier import _route_sentence


def _headings(template_key: str) -> list[str]:
    # Sections live in the template's `sections` list now, not in its
    # starter HTML — headings are created as content arrives so the live
    # document never shows an empty subheading.
    from app.drafting.templates import template_sections

    return template_sections(template_key)


def _assert_routes(template_key: str, sentence: str, expected: str) -> None:
    section, _ = _route_sentence(sentence, _headings(template_key))
    assert section == expected, f"{sentence!r} -> {section!r}, expected {expected!r}"


def test_sow_routing_is_unchanged_by_other_template_rules():
    for sentence, expected in [
        ("We need a modern responsive website where customers can browse products, "
         "add items to a cart, and complete payments online.", "Scope of Work"),
        ("The project should start on September 15 and the final website should be "
         "delivered by October 30.", "Timeline & Milestones"),
        ("Our total budget is $45,000.", "Budget / Commercial Terms"),
        ("The deliverables should include the website, payment integration, mobile "
         "responsive design, basic analytics.", "Deliverables"),
        ("We'll provide the product images, descriptions, pricing, and access to our "
         "existing domain.", "Assumptions & Dependencies"),
        ("The project does not include ongoing marketing or content creation after "
         "launch.", "Out of Scope"),
        ("We want to have a kickoff meeting next week.", "Next Steps"),
    ]:
        _assert_routes("statement_of_work", sentence, expected)


def test_meeting_minutes_routing():
    _assert_routes("meeting_minutes", "Joining us today are Sarah, Mike, and Priya.", "Attendees")
    _assert_routes("meeting_minutes", "Today we will cover the Q3 roadmap.", "Agenda")
    _assert_routes("meeting_minutes", "We decided to postpone the launch until November.",
                   "Discussion & Decisions")
    _assert_routes("meeting_minutes", "Sarah will send the revised deck by Friday.", "Action Items")


def test_advice_note_routing():
    _assert_routes("advice_note", "By way of background, the client signed the lease in 2019.",
                   "Background")
    _assert_routes("advice_note", "The question is whether the termination clause is enforceable.",
                   "Questions Raised")
    _assert_routes("advice_note", "Our advice is to serve notice before the renewal date.", "Advice")
    _assert_routes("advice_note", "A key concern is the potential liability under clause 12.",
                   "Key Considerations & Risks")
    _assert_routes("advice_note", "We recommend obtaining a formal valuation.", "Recommendations")


def test_requirements_list_routing():
    _assert_routes("requirements_list", "Users must be able to reset their password by email.",
                   "Functional Requirements")
    # Non-functional is checked first on purpose: this matches both shapes.
    _assert_routes("requirements_list", "The system must handle 10,000 concurrent users.",
                   "Non-Functional Requirements")
    _assert_routes("requirements_list", "We are limited to the existing AWS account.", "Constraints")


def test_proposal_routing():
    _assert_routes("proposal", "Our team has delivered twelve e-commerce builds.", "Why Us")
    _assert_routes("proposal", "The total investment is $80,000.", "Investment")


def test_goal_statement_no_longer_has_an_objectives_section_to_land_in():
    """Executive Summary and Objectives were removed from the SOW template.

    Nobody dictates an executive summary in a meeting, and the export-time
    cleanup that was supposed to strip an unfilled section proved
    unreliable, so both shipped as bare empty headings in real exports. A
    goal statement now falls through to the "most appropriate section"
    fallback rather than creating a section that usually stays empty.
    """
    section, fact = _route_sentence(
        "The goal is to increase online sales by 30 percent.",
        _headings("statement_of_work"),
    )
    assert section is None
    assert "30 percent" in fact  # the fact still reaches the document

    # Concrete scope language is unaffected.
    _assert_routes("statement_of_work",
                   "We need a modern responsive website where customers can browse products.",
                   "Scope of Work")


# --- details-table fills ---------------------------------------------------

from app.drafting.classifier import _extract_project_name
from app.drafting.templates import PREPARED_BY, render_template


def test_prepared_by_defaults_to_accord():
    # Not a transcript fact and never spoken, so nothing in the pipeline
    # could fill it — every exported document had a blank Prepared by.
    assert PREPARED_BY == "ACCORD"
    assert "ACCORD" in render_template("statement_of_work")
    for key in ("meeting_minutes", "proposal", "advice_note", "requirements_list"):
        assert "ACCORD" in render_template(key), key
    # An explicit value still wins.
    assert "Jane Doe" in render_template("statement_of_work", prepared_by="Jane Doe")


def test_extract_project_name():
    assert _extract_project_name("a website development project") == "Website Development"
    assert _extract_project_name("Hi, I'd like to discuss a website development project "
                                 "for Northstar Goods.") == "Website Development"
    # str.title() would render this "Crm Migration".
    assert _extract_project_name("the CRM migration project") == "CRM Migration"
    assert _extract_project_name("we talked about the weather") is None


def test_project_cell_filled_alongside_client():
    ops = build_section_operations(
        ADDITION,
        "Hi, I'd like to discuss a website development project for Northstar Goods.",
        render_template("statement_of_work"),
        "statement_of_work",
    )
    fills = {o.table_field: o.table_value for o in ops if o.table_field}
    assert fills.get("Client") == "Northstar Goods"
    assert fills.get("Project") == "Website Development"


def test_project_cell_not_refilled_once_set():
    filled = render_template("statement_of_work", topic="Website Development")
    ops = build_section_operations(
        ADDITION, "a website development project for Acme.", filled, "statement_of_work"
    )
    assert not [o for o in ops if o.table_field == "Project"]


# --- ASR hallucinations ----------------------------------------------------

from app.drafting.classifier import strip_asr_hallucinations


def test_whisper_signoff_artifacts_are_stripped():
    """Fed near-silence Whisper emits caption sign-offs rather than an empty
    string. One merged into a real sentence and reached a live exported
    document as "We expect weekly progress updates and we'll see you next
    time." — the surrounding speech is real and must survive."""
    assert strip_asr_hallucinations(
        "We expect weekly progress updates and we'll see you next time. "
        "Please review each milestone before moving forward."
    ) == "We expect weekly progress updates. Please review each milestone before moving forward."
    # A line that is nothing but an artifact yields nothing at all.
    assert strip_asr_hallucinations("we'll see you next time") == ""
    assert strip_asr_hallucinations("Thanks for watching!") == ""
    assert is_filler_only("we'll see you next time") is True


def test_real_speech_is_untouched():
    for line in [
        "The budget is $45,000 and the timeline is fixed.",
        "We expect weekly progress updates and will review each milestone before moving forward.",
    ]:
        assert strip_asr_hallucinations(line) == line


# --- section targeting off (platform chooses placement) --------------------

def test_untargeted_mode_emits_one_instruction_with_no_target_header(no_section_targeting):
    """With targeting off a batch becomes a single instruction naming no
    heading — four SuperDocs calls per batch collapse to one. Facts are
    still extracted and cleaned identically; only placement is delegated."""
    ops = build_section_operations(
        ADDITION,
        "We need a modern responsive website where customers can browse products. "
        "The project should start on September 15. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    body = [o for o in ops if o.table_field is None]
    assert len(body) == 1
    assert body[0].section is None
    assert "[Target:" not in body[0].instruction
    assert "most appropriate section" in body[0].instruction
    # Every fact still travels — delegation must not mean dropping content.
    joined = " ".join(body[0].facts)
    assert "September 15" in joined and "$45,000" in joined


def test_untargeted_mode_still_fills_the_details_table(no_section_targeting):
    """Client/Project are table cells, not prose — the platform cannot infer
    them from the transcript, so those fills survive regardless of mode."""
    ops = build_section_operations(
        ADDITION,
        "Hi, I'd like to discuss a website development project for Northstar Goods.",
        render_template("statement_of_work"), "statement_of_work",
    )
    fills = {o.table_field: o.table_value for o in ops if o.table_field}
    assert fills.get("Client") == "Northstar Goods"
    assert fills.get("Project") == "Website Development"


def test_targeting_on_still_splits_per_section():
    ops = build_section_operations(
        ADDITION,
        "The project should start on September 15. Our total budget is $45,000.",
        SOW_DRAFT, "statement_of_work",
    )
    sections = {o.section for o in ops if o.table_field is None}
    assert "Timeline & Milestones" in sections
    assert "Budget / Commercial Terms" in sections


# --- corrections that state the NEW value ----------------------------------

def test_correction_stating_only_the_new_value_is_detected():
    """The brief's headline behaviour: "no, the start date is the fifteenth".

    Signal B originally asked whether a value in the sentence was ALREADY in
    the document — exactly backwards for a repair, which states the new
    value while the old one sits in the draft. It only ever fired when the
    speaker happened to restate the old value too ("September 20th, not
    September 15th"). Live audio saying "Our total budget is $45,000.
    Actually, no make it $55,000." was classified as an addition, so both
    figures would have been written into the document.
    """
    budget = "<h2>Budget</h2><p>Our total budget is $45,000.</p>"
    timeline = "<h2>Timeline</h2><p>The project starts September 15th.</p>"
    assert classify("Actually, no make it $55,000.", budget) == CORRECTION
    assert classify("No, the start date is the 20th.", timeline) == CORRECTION


def test_a_cue_alone_still_never_makes_a_correction():
    """Two independent signals remain required — this must not degrade into
    "any sentence containing 'actually'"."""
    budget = "<h2>Budget</h2><p>Our total budget is $45,000.</p>"
    assert classify("Actually, we should also add SEO later.", budget) == ADDITION
    # A value with no cue is new information, not a repair.
    assert classify("Our total budget is $45,000.", "") == ADDITION
    # A cue and a value, but nothing of that kind in the document yet.
    assert classify("Actually, make it $55,000.", "<h2>Scope</h2><p>A website.</p>") == ADDITION


def test_a_correction_in_the_same_batch_supersedes_the_original():
    """A repair usually follows its mistake in the same breath, so both land
    in one batch. The draft does not hold the old value yet at that point,
    so the repair reads as new information and SuperDocs receives two
    competing figures — the live run left Budget empty rather than choose.
    """
    from app.drafting.classifier import resolve_intra_batch_correction as resolve

    out = resolve(
        "Our total budget is $45,000. Actually, no, make it $55,000. "
        "The deliverables should include the website."
    )
    assert "$45,000" not in out
    assert "$55,000" in out
    # Unrelated facts in the batch survive untouched.
    assert "deliverables" in out

    out = resolve("The project starts September 15th. No, the start date is September 20th.")
    assert "15th" not in out and "20th" in out


def test_a_batch_without_a_correction_is_left_alone():
    from app.drafting.classifier import resolve_intra_batch_correction as resolve

    text = "Our total budget is $45,000. The deliverables include analytics."
    assert resolve(text) == text
    # A cue with no competing value changes nothing.
    assert resolve("Actually, we should also add SEO later.") == "Actually, we should also add SEO later."


def test_details_heading_is_found_by_its_table_not_its_name():
    """A firm's uploaded template names that section whatever it likes.

    The lookup matched on the word "details" and otherwise fell back to the
    literal string "Project Details" — so against a template whose section
    is called "Client & Matter", the fill targeted a section the document
    does not contain, placement failed, the batch rolled back, and a live
    run drafted nothing at all from five utterances. The metadata table is
    the reliable landmark; its heading's wording is not.
    """
    from app.drafting.classifier import _details_heading
    from app.drafting.templates import render_template

    firm = (
        "<h1>MERIDIAN</h1><h2>Client &amp; Matter</h2>"
        "<table><tr><td><strong>Client</strong></td><td></td></tr></table>"
        "<h2>Our Approach</h2><p></p>"
    )
    assert _details_heading(firm) == "Client & Matter"
    assert _details_heading(render_template("statement_of_work")) == "Project Details"
    assert _details_heading(render_template("advice_note")) == "Matter Details"
    # No table anywhere → no fill is attempted at all, rather than one
    # aimed at a section that does not exist.
    assert _details_heading("<h1>X</h1><h2>Intro</h2><p>hi</p>") is None


def test_correction_instruction_names_what_it_replaces():
    """"Actually, make it $55,000" names only the new figure. The old one
    lives in the document, so that is where it must be found.

    Without this the instruction read "REPLACE WITH $55,000" while naming
    nothing to replace, and it carried the ADDITION constraint block, whose
    final line is "add your facts without deleting anything" — forbidding
    the one thing a correction exists to do. A live run left $45,000
    standing in the exported document.
    """
    from app.drafting.classifier import build_structured_instruction, correction_values

    draft = "<h2>Budget / Commercial Terms</h2><p>Our total budget is $45,000.</p>"
    msg = build_structured_instruction(
        CORRECTION, "Actually, no, make it $55,000.", draft, "statement_of_work"
    )
    assert 'FIND: "$45,000"' in msg
    assert "Replace it IN PLACE" in msg
    assert "$55,000" in msg
    # The addition constraints must NOT be reused here.
    assert "without deleting anything" not in msg
    assert "must NOT survive" in msg

    # Both values are derived, so the gate can actually verify the swap.
    assert correction_values("Actually, no, make it $55,000.", draft) == ("$45,000", "$55,000")


def test_correction_values_leave_an_ambiguous_document_alone():
    """Two candidate values of the same kind — rewriting the wrong sentence
    is worse than not rewriting."""
    from app.drafting.classifier import correction_values

    ambiguous = "<p>Phase one is $10,000.</p><p>Phase two is $20,000.</p>"
    old, new = correction_values("Actually, make it $55,000.", ambiguous)
    assert old is None
    assert new == "$55,000"


def test_a_mixed_batch_splits_the_repair_from_the_new_information():
    """A batch is classified a correction when ANY sentence repairs a value,
    but the rest is usually ordinary new information.

    "Actually, no, make it $55,000. The deliverables should include the
    website." produced ONE correction op carrying both — so the deliverables
    sentence was handed to a FIND/REPLACE instruction that only knows how to
    swap a value. Live result from a single batch: the budget stayed at
    $45,000 AND Deliverables came out empty.
    """
    draft = (
        "<h2>Deliverables</h2>"
        "<h2>Budget / Commercial Terms</h2><div><p>Our total budget is $45,000.</p></div>"
    )
    ops = build_section_operations(
        CORRECTION,
        "Actually, no, make it $55,000. The deliverables should include the website, "
        "payment integration, and basic analytics.",
        draft, "statement_of_work",
    )
    # Identified by is_correction, not by section being None. A correction is
    # now AIMED at the section holding the value it replaces — left unaimed,
    # the platform chose placement and put a corrected budget figure inside the
    # Project Details date cell while Budget stayed empty.
    repair = [o for o in ops if o.is_correction]
    additions = [o for o in ops if o.section == "Deliverables"]
    assert len(repair) == 1
    assert repair[0].section == "Budget / Commercial Terms", repair[0].section
    assert "$55,000" in " ".join(repair[0].facts)
    # The repair op must NOT be carrying the unrelated fact.
    assert "deliverables" not in " ".join(repair[0].facts).lower()
    assert additions, "the new information needs its own targeted operation"


def test_a_pure_correction_still_produces_one_operation():
    draft = "<h2>Budget</h2><p>Our total budget is $45,000.</p>"
    ops = build_section_operations(
        CORRECTION, "Actually, no, make it $55,000.", draft, "statement_of_work"
    )
    # section is no longer None: a correction is aimed at the section holding
    # the value being replaced, so the platform cannot choose placement and the
    # placement check has something to verify against.
    assert len(ops) == 1 and ops[0].is_correction
    assert ops[0].section == "Budget"


def test_a_repair_does_not_wait_for_a_full_stop():
    """Whisper transcribed the live audio as "Our total budget is $45,000,
    Actually, no, make it $55,000." — one sentence by punctuation, two by
    meaning. Splitting only on .!? bailed out immediately, both figures went
    through, and the document narrated the change ("the initial budget was
    discussed at $45,000...") instead of making it.
    """
    from app.drafting.classifier import resolve_intra_batch_correction as resolve

    out = resolve(
        "Our total budget is $45,000, Actually, no, make it $55,000. "
        "The deliverables should include the website."
    )
    assert "$45,000" not in out
    assert "$55,000" in out
    assert "deliverables" in out          # unrelated content survives
    assert "  " not in out                # no double spaces from the split

    # "no," has no word boundary after the comma — it needs its own branch.
    # This previously expected the bare repair, "no, make it September 20th."
    # That assertion encoded a real defect: a fragment carries the value but
    # never says what the value IS, and SuperDocs, given it as content, read
    # it as an instruction with no referent and wrote nothing — the live gate
    # log shows the Budget op rejected for missing its own anchor three times
    # running. The repair now rewrites the sentence it repairs.
    assert resolve("The project starts September 15th, no, make it September 20th.") \
        == "The project starts September 20th."


def test_mid_sentence_split_leaves_non_corrections_alone():
    from app.drafting.classifier import resolve_intra_batch_correction as resolve

    text = "Our total budget is $45,000. The deliverables include analytics."
    assert resolve(text) == text
    assert resolve("Actually, we should also add SEO later.") == "Actually, we should also add SEO later."


# --- an intra-batch repair must survive as a STATEMENT, not a fragment ------
#
# What this must never do: hand SuperDocs a bare repair like "Actually, no,
# make it $55,000." Observed live — the gate logged
#   op=Budget / Commercial Terms failures=[... missing anchors: ['$55,000']]
# because SuperDocs read the fragment as an instruction with no referent,
# answered with heading markup, and never wrote the figure. Budget stayed
# empty through three attempts.

def test_repair_rewrites_its_own_sentence_rather_than_leaving_a_fragment():
    from app.drafting.classifier import resolve_intra_batch_correction as r
    out = r("Our total budget for this is $45,000. Actually, no, make it $55,000.")
    assert out == "Our total budget for this is $55,000."
    assert "45,000" not in out
    assert "Actually" not in out


def test_repair_keeps_unrelated_facts_in_the_same_batch():
    from app.drafting.classifier import resolve_intra_batch_correction as r
    out = r("Our total budget for this is $45,000. Actually, no, make it $55,000. "
            "The deliverables should include the website and analytics.")
    assert "$55,000" in out and "$45,000" not in out
    assert "deliverables" in out.lower()


def test_repair_works_when_whisper_joins_it_with_a_comma():
    """Live audio transcribes as one sentence by punctuation, two by meaning."""
    from app.drafting.classifier import resolve_intra_batch_correction as r
    out = r("Our total budget is $45,000, Actually, no, make it $55,000.")
    assert "$55,000" in out and "$45,000" not in out


def test_repair_handles_dates_the_same_way():
    from app.drafting.classifier import resolve_intra_batch_correction as r
    out = r("The project should start on September 15th. "
            "Actually, the start date is October 1st.")
    assert "October 1st" in out and "September 15th" not in out


def test_plain_statements_are_untouched():
    from app.drafting.classifier import resolve_intra_batch_correction as r
    for text in ("Our total budget is $45,000.",
                 "We need a website. The budget is $45,000.",
                 "No, the start date is the fifteenth."):
        assert r(text) == text


# --- a kick-off sentence belongs in Next Steps ------------------------------
#
# What this must never do: leave a kick-off sentence unrouted. Unrouted facts
# are handed to the model to place, and live it chose Timeline & Milestones —
# a fair guess given "next week", but the wrong section. The rule matched only
# the bare "kickoff" spelling and only "finalize requirements" without its
# article, so the way people actually speak missed on both counts.

def test_kickoff_phrasings_all_route_to_next_steps():
    from app.drafting.classifier import build_section_operations, ADDITION
    draft = (
        "<h1>Statement of Work</h1>"
        "<h2>Timeline &amp; Milestones</h2><p>c</p>"
        "<h2>Next Steps</h2><p></p>"
    )
    for text in (
        "We want to have a kick-off meeting next week to finalize the requirements.",
        "A kick-off meeting is planned for next week to finalize requirements.",
        "We will have a kick off meeting next week.",
        "A kickoff is scheduled.",
    ):
        sections = [
            op.section
            for op in build_section_operations(ADDITION, text, draft, "statement_of_work")
        ]
        assert sections == ["Next Steps"], f"{text!r} routed to {sections}"


def test_dates_still_route_to_timeline_not_next_steps():
    """The fix must not pull ordinary scheduling into Next Steps."""
    from app.drafting.classifier import build_section_operations, ADDITION
    draft = (
        "<h1>Statement of Work</h1>"
        "<h2>Timeline &amp; Milestones</h2><p>c</p>"
        "<h2>Next Steps</h2><p></p>"
    )
    ops = build_section_operations(
        ADDITION,
        "The project should start on September 15th, and the final website "
        "should be delivered by October 30th.",
        draft, "statement_of_work",
    )
    assert [op.section for op in ops] == ["Timeline & Milestones"]


# --- cross-batch corrections: a value already written must be REPLACED -----
#
# What this must never do: delete the old value without writing the new one.
# Live, Budget was left completely empty by a correction that named both
# figures. Three separate defects combined:
#   1. "correction"/"sorry"/"X, not Y" were not correction cues at all, so
#      the utterance classified as an ADDITION
#   2. _MONEY_VALUE_RE swallowed the comma AFTER a figure ("$55,000,")
#   3. the old-value extractor excluded commas, so "not $45,000" captured
#      "$45" — and the replacement was then computed as "the value that is
#      not $45", i.e. $45,000 itself. The instruction became
#      "replace $45 with $45,000".

BUDGET_DRAFT = (
    "<h1>Statement of Work</h1>"
    "<h2>Budget / Commercial Terms</h2>"
    "<p>The total budget for this project is $45,000.</p>"
)
TIMELINE_DRAFT = (
    "<h1>Statement of Work</h1>"
    "<h2>Timeline &amp; Milestones</h2>"
    "<p>The project starts on September 15th.</p>"
)


def test_spoken_correction_forms_all_classify_as_corrections():
    for text in (
        "Sorry, correction — the total budget is $55,000, not $45,000.",
        "No, the total budget is $55,000.",
        "Actually the budget is $55,000.",          # no comma after "Actually"
        "The budget is $55,000, not $45,000.",       # contrastive, no opener
    ):
        assert classify(text, BUDGET_DRAFT) == CORRECTION, text


def test_obligation_language_is_still_an_addition():
    """The cues must not swallow ordinary future/obligation speech."""
    for text in (
        "The deliverables include the website and analytics.",
        "The project should start on September 15th.",
        "The website should be delivered by October 30th.",
    ):
        assert classify(text, BUDGET_DRAFT) == ADDITION, text


def test_correction_values_survive_the_thousands_separator():
    from app.drafting.classifier import correction_values
    assert correction_values(
        "Sorry, correction — the total budget is $55,000, not $45,000.",
        BUDGET_DRAFT,
    ) == ("$45,000", "$55,000")
    assert correction_values(
        "The budget is $55,000, not $45,000.", BUDGET_DRAFT
    ) == ("$45,000", "$55,000")


def test_correction_values_when_the_old_value_is_only_implied():
    """The speaker names only the new figure; the old one comes from the draft."""
    from app.drafting.classifier import correction_values
    assert correction_values("No, the total budget is $55,000.", BUDGET_DRAFT) \
        == ("$45,000", "$55,000")


def test_correction_values_for_dates():
    from app.drafting.classifier import correction_values
    assert correction_values(
        "The start date is October 1st, not September 15th.", TIMELINE_DRAFT
    ) == ("September 15th", "October 1st")


# --- the flush trigger must stay narrower than the classification cues -----
#
# A flush from Batcher.add() runs inline on the transcript consumer, so the
# consumer stops pulling events for as long as the batch takes to draft. Live,
# the panel froze at 9 messages and then delivered the backlog at once.
# Widening the classification cues to catch more spoken repairs made that
# stall fire far more often, so the two sets are deliberately separate.

def test_widened_cues_classify_without_forcing_a_flush():
    from app.drafting.classifier import has_flush_cue
    for text in (
        "Sorry, correction — the total budget is $55,000, not $45,000.",
        "Actually the budget is $55,000.",
        "The budget is $55,000, not $45,000.",
    ):
        assert classify(text, BUDGET_DRAFT) == CORRECTION, text
        assert not has_flush_cue(text), f"{text!r} would stall the transcript"


def test_the_original_flush_cues_still_flush():
    """Narrowing must not stop a real mid-sentence repair closing the batch."""
    from app.drafting.classifier import has_flush_cue
    assert has_flush_cue("Actually, no make it $55,000.")
    assert has_flush_cue("No, the total budget is $55,000.")
    assert has_flush_cue("Scratch that.")


def test_ordinary_speech_never_flushes():
    from app.drafting.classifier import has_flush_cue
    for text in ("Our total budget is $44,000.",
                 "The project should start on September 15th."):
        assert not has_flush_cue(text)


# --- cue detection must survive the punctuation Whisper actually emits -----
#
# Live, a spoken repair was transcribed across two audio chunks as
#   seq=9  "Our total budget is $45,000. Actually."     <- PERIOD, not comma
#   seq=10 "no make it $55,000."                        <- no comma after "no"
# Every substring cue missed both halves, so the repair read as an ADDITION
# and the document gained a SECOND budget line instead of replacing the first.
# The remote document then held two budget paragraphs while the panel showed
# one, and export pulls the remote copy.

def test_whisper_punctuation_still_reads_as_a_repair():
    from app.drafting.classifier import has_correction_cue
    assert has_correction_cue("Our total budget is $45,000. Actually.")
    assert has_correction_cue("no make it $55,000.")


def test_a_repair_split_across_batches_still_corrects():
    """Each half arrives in its own batch; the second must replace, not add."""
    draft = (
        "<h1>Statement of Work</h1>"
        "<h2>Budget / Commercial Terms</h2>"
        "<p>Our total budget is $45,000.</p>"
    )
    assert classify("no make it $55,000.", draft) == CORRECTION


def test_bare_no_only_counts_at_the_start_of_a_segment():
    """"no" is far too common to treat as a cue anywhere in a sentence."""
    from app.drafting.classifier import has_correction_cue
    assert not has_correction_cue("The deliverables include analytics and no downtime.")
    assert not has_correction_cue("The project does not include ongoing marketing.")
    assert has_correction_cue("No, the budget is $55,000.")


def test_actually_is_a_cue_with_any_punctuation():
    from app.drafting.classifier import has_correction_cue
    for text in ("Actually, make it $55,000.", "Actually the budget is $55,000.",
                 "Our budget is $45,000. Actually."):
        assert has_correction_cue(text), text


# --- a correction must be aimed at a section ------------------------------
#
# Built with section=None, the platform chose placement itself: live, a
# corrected budget figure landed inside the Project Details table cell meant
# for the document date, and the Budget section stayed empty. With no target
# section the placement check cannot run either, so nothing caught it.

BUDGET_HELD = (
    "<h1>Statement of Work</h1>"
    "<h2>Scope of Work</h2><p>A responsive website.</p>"
    "<h2>Budget / Commercial Terms</h2><p>Our total budget is $45,000.</p>"
)


def test_a_correction_targets_the_section_holding_the_old_value():
    from app.drafting.classifier import build_section_operations
    ops = build_section_operations(
        CORRECTION, "Actually, no, make it $55,000.", BUDGET_HELD, "statement_of_work"
    )
    assert ops and ops[0].is_correction
    assert ops[0].section == "Budget / Commercial Terms", ops[0].section


def test_a_correction_falls_back_to_routing_the_repair_text():
    """No old value in the draft yet — route on the repair's own vocabulary."""
    from app.drafting.classifier import build_section_operations
    draft = "<h1>Statement of Work</h1><h2>Timeline &amp; Milestones</h2><p></p>"
    ops = build_section_operations(
        CORRECTION, "No, the project starts on October 1st.", draft, "statement_of_work"
    )
    assert ops
    assert ops[0].section in ("Timeline & Milestones", None)


def test_a_correction_with_nothing_to_go_on_still_produces_an_operation():
    """Unresolvable target must not drop the repair entirely."""
    from app.drafting.classifier import build_section_operations
    ops = build_section_operations(
        CORRECTION, "Actually, no, make it $55,000.",
        "<h1>Statement of Work</h1>", "statement_of_work",
    )
    assert ops and ops[0].is_correction


def test_a_cueless_correction_batch_routes_each_sentence_to_its_own_section():
    """NEVER: let one section swallow another section's content.

    A batch is classified a correction when ANY sentence repairs a value —
    including when the repair happened in an EARLIER batch and the cue was
    already consumed. With no cue left and nothing here replacing a value
    the document holds, there is no repair in this batch at all, and
    treating the whole thing as one collapsed it onto a single section:

        BATCH ROUTED: 'the 30th. Our total budget is $55,000.'
                      -> ops=['Timeline & Milestones']

    "30th" was already in Timeline, so the budget sentence went there too.
    Budget / Commercial Terms came out empty, and since no operation ever
    targeted it, reconciliation had nothing owed and nothing in the ledger
    to notice was missing.
    """
    from app.drafting.classifier import build_section_operations
    html = (
        "<h1>Statement of Work</h1>"
        "<h2>Timeline &amp; Milestones</h2>"
        "<p>Work commences on September 15th and is delivered by October 30th.</p>"
    )
    ops = build_section_operations(
        CORRECTION, "the 30th. Our total budget is $55,000.", html, "statement_of_work",
    )
    sections = [o.section for o in ops]
    assert "Budget / Commercial Terms" in sections, sections
    budget = next(o for o in ops if o.section == "Budget / Commercial Terms")
    assert any("55,000" in f for f in budget.facts), budget.facts
    # ...and the timeline fragment must not have been dragged along with it.
    assert not any("30th" in f for f in budget.facts), budget.facts


def test_a_repair_to_the_value_already_present_is_not_a_correction():
    """Whisper mis-hears the corrected figure often enough for this to be real.

    "Our total budget $45,000. no, make it $45,000." reached the API as a
    correction. The platform answered with an insert rather than an edit —
    there being nothing to change — and the gate spent three attempts refusing
    it before surfacing "correction proposal is not an edit operation" to the
    reviewer mid-meeting.
    """
    from app.drafting.classifier import build_section_operations
    ops = build_section_operations(
        CORRECTION, "Our total budget $45,000. no, make it $45,000.",
        BUDGET_HELD, "statement_of_work",
    )
    assert not [o for o in ops if o.is_correction], \
        "a repair to the value already in the section is not a repair"


def test_a_genuine_repair_is_still_a_correction():
    from app.drafting.classifier import build_section_operations
    ops = build_section_operations(
        CORRECTION, "Our total budget $45,000. no, make it $55,000.",
        BUDGET_HELD, "statement_of_work",
    )
    repairs = [o for o in ops if o.is_correction]
    assert repairs and repairs[0].section == "Budget / Commercial Terms"
