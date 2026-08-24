from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from docrelay.domain.enums import ChangeDecision, ProposalOperation, Provider
from docrelay.domain.write_plan import SealedWritePlan
from docrelay.integrations.google.canonical import sha256_json
from docrelay.mapping.production import (
    BaselineSnapshot,
    MappingFailure,
    MappingFailureCode,
    MappingProofPayload,
    ReviewedProposal,
    SealedMappingProof,
    compile_write_plan,
    map_replacement,
    normalize_reviewed_change,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64
TWO_HASH = "2" * 64


def _paragraph(
    text: str = "Payment is due within 45 days.",
    *,
    start: int = 162,
    bullet: dict[str, str] | None = None,
    runs: list[dict[str, object]] | None = None,
    paragraph_style: dict[str, object] | None = None,
) -> dict[str, object]:
    content = f"{text}\n"
    end = start + len(content.encode("utf-16-le")) // 2
    return {
        "startIndex": start,
        "endIndex": end,
        "type": "paragraph",
        "paragraphStyle": paragraph_style or {"namedStyleType": "NORMAL_TEXT"},
        "bullet": bullet,
        "positionedObjectIds": [],
        "runs": runs
        or [
            {
                "kind": "text",
                "startIndex": start,
                "endIndex": end,
                "text": content,
                "style": {},
            }
        ],
    }


def _canonical(body: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema": "docrelay.google-native-canonical.v1",
        "tabs": [
            {
                "tabProperties": {
                    "tabId": "t.0",
                    "title": "Tab 1",
                    "index": 0,
                    "nestingLevel": 0,
                    "parentTabId": None,
                },
                "body": body or [_paragraph()],
                "headers": {},
                "footers": {},
                "footnotes": {},
                "documentStyle": {},
                "namedStyles": {},
                "lists": {},
                "namedRanges": {},
                "inlineObjects": {},
                "positionedObjects": {},
                "childTabs": [],
            }
        ],
    }


def _proposal(**changes: object) -> ReviewedProposal:
    values: dict[str, object] = {
        "proposal_id": UUID("00000000-0000-0000-0000-000000000101"),
        "decision_id": UUID("00000000-0000-0000-0000-000000000102"),
        "decision": ChangeDecision.APPROVE,
        "decision_sha256": ZERO_HASH,
        "superseded": False,
        "operation": ProposalOperation.EDIT,
        "review_round": 1,
        "session_id": "session-a",
        "session_document_id": "document-a",
        "durable_document_id": "durable-a",
        "job_id": "job-a",
        "superdocs_export_id": UUID("00000000-0000-0000-0000-000000000103"),
        "approved_export_sha256": ONE_HASH,
        "final_version_id": "final-a",
        "superdocs_change_id": "change-a",
        "chunk_id": "ephemeral-chunk-a",
        "old_html": '<p data-id="same">Payment is due within 45 days.</p>',
        "new_html": '<p data-id="same">Payment is due within 30 days.</p>',
        "lineage_current": True,
    }
    values.update(changes)
    return ReviewedProposal.model_validate(values)


def _baseline(payload: dict[str, object] | None = None, **changes: object) -> BaselineSnapshot:
    canonical = payload or _canonical()
    values: dict[str, object] = {
        "snapshot_id": UUID("00000000-0000-0000-0000-000000000201"),
        "provider": Provider.GOOGLE,
        "provider_principal_subject": "principal-a",
        "provider_file_id": "google-file-a",
        "parent_ids": ("parent-a",),
        "baseline_revision_id": "revision-A",
        "run_baseline_revision_id": "revision-A",
        "capture_revision_id": "revision-A",
        "native_raw_sha256": ONE_HASH,
        "native_canonical_sha256": sha256_json(canonical),
        "exported_docx_sha256": TWO_HASH,
        "canonical_payload": canonical,
    }
    values.update(changes)
    return BaselineSnapshot.model_validate(values)


def _supported_mapping():
    change = normalize_reviewed_change(_proposal())
    return change, _baseline(), map_replacement(change, _baseline(), created_at=NOW)


def _compile(change, baseline: BaselineSnapshot):
    proof = map_replacement(change, baseline, created_at=NOW)
    return proof, compile_write_plan(
        change=change,
        baseline=baseline,
        proof=proof,
        sync_run_id=UUID("00000000-0000-0000-0000-000000000301"),
        rule_identity=UUID("00000000-0000-0000-0000-000000000302"),
        rule_version=1,
        instruction_sha256=ZERO_HASH,
        configuration_sha256=ONE_HASH,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


def test_approved_unique_supported_replacement_produces_exact_proof_and_plan() -> None:
    change, baseline, proof = _supported_mapping()
    plan = compile_write_plan(
        change=change,
        baseline=baseline,
        proof=proof,
        sync_run_id=UUID("00000000-0000-0000-0000-000000000301"),
        rule_identity=UUID("00000000-0000-0000-0000-000000000302"),
        rule_version=1,
        instruction_sha256=ZERO_HASH,
        configuration_sha256=ONE_HASH,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )

    assert proof.payload.candidate_count == 1
    assert proof.payload.location.edit_start_index == 184
    assert proof.payload.location.edit_end_index == 186
    assert proof.payload.lineage.chunk_id == "ephemeral-chunk-a"
    assert proof.payload.location.model_dump().get("chunk_id") is None
    assert plan.payload.expected_replacement.old_text == "45"
    assert plan.payload.expected_replacement.new_text == "30"
    operation = plan.payload.provider_operations[0]
    assert operation.provider_payload() == {
        "requests": [
            {
                "deleteContentRange": {
                    "range": {
                        "segmentId": "",
                        "tabId": "t.0",
                        "startIndex": 184,
                        "endIndex": 186,
                    }
                }
            },
            {
                "insertText": {
                    "location": {"segmentId": "", "tabId": "t.0", "index": 184},
                    "text": "30",
                }
            },
        ],
        "writeControl": {"requiredRevisionId": "revision-A"},
    }


def test_legacy_normal_text_mapping_proof_shape_keeps_its_integrity_round_trip() -> None:
    _, _, current = _supported_mapping()
    legacy_payload = current.payload.model_dump(mode="json")
    legacy_payload["mapper_version"] = "docrelay.google-plain-text-mapper.v3"
    legacy_eligibility = {
        key: value
        for key, value in legacy_payload["eligibility"].items()
        if key not in {"contiguous_ascii_text", "supported_named_style"}
    }
    legacy_eligibility["normal_text"] = True
    legacy_eligibility["internal_ascii_token"] = True
    legacy_payload["eligibility"] = legacy_eligibility
    legacy_payload["replacements"][0]["eligibility"] = legacy_eligibility

    sealed = SealedMappingProof.seal(MappingProofPayload.model_validate(legacy_payload))
    round_tripped = SealedMappingProof.model_validate(sealed.model_dump(mode="json"))

    assert round_tripped == sealed
    assert "supported_named_style" not in sealed.payload.eligibility.model_dump(mode="json")


def test_v4_supported_block_mapping_proof_shape_keeps_its_integrity_round_trip() -> None:
    _, _, current = _supported_mapping()
    v4_payload = current.payload.model_dump(mode="json")
    v4_payload["mapper_version"] = "docrelay.google-supported-block-mapper.v4"
    v4_eligibility = dict(v4_payload["eligibility"])
    del v4_eligibility["contiguous_ascii_text"]
    v4_eligibility["internal_ascii_token"] = True
    v4_payload["eligibility"] = v4_eligibility
    v4_payload["replacements"][0]["eligibility"] = v4_eligibility

    sealed = SealedMappingProof.seal(MappingProofPayload.model_validate(v4_payload))

    assert SealedMappingProof.model_validate(sealed.model_dump(mode="json")) == sealed
    assert sealed.payload.mapper_version == "docrelay.google-supported-block-mapper.v4"


def test_prefix_replacement_maps_from_visible_text_start() -> None:
    old_paragraph = "Vendor Agreement"
    new_paragraph = "Business Agreement"
    target = _paragraph(old_paragraph, start=10)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    proof, plan = _compile(change, baseline)

    assert (change.old_text, change.new_text) == ("Vendor", "Business")
    assert proof.payload.location.edit_start_index == 10
    assert proof.payload.location.edit_end_index == 16
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical([_paragraph(new_paragraph, start=10)])
    )


def test_suffix_replacement_maps_through_visible_text_end() -> None:
    old_paragraph = "Agreement Draft"
    new_paragraph = "Agreement Final"
    target = _paragraph(old_paragraph, start=10)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    proof, _ = _compile(change, baseline)

    assert (change.old_text, change.new_text) == ("Draft", "Final")
    assert proof.payload.location.edit_start_index == 20
    assert proof.payload.location.edit_end_index == int(target["endIndex"]) - 1


def test_vendor_boundary_insertion_becomes_terminator_safe_full_block_replacement() -> None:
    old_paragraph = "Vendor Agreement"
    new_paragraph = "Business Vendor Agreement"
    target = _paragraph(old_paragraph, start=10)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    proof, plan = _compile(change, baseline)

    assert (change.old_text, change.new_text, change.prefix, change.suffix) == (
        old_paragraph,
        new_paragraph,
        "",
        "",
    )
    assert proof.payload.old_text == old_paragraph
    assert proof.payload.new_text == new_paragraph
    assert proof.payload.location.edit_start_index == int(target["startIndex"])
    assert proof.payload.location.edit_end_index == int(target["endIndex"]) - 1
    requests = plan.payload.provider_operations[0].requests
    delete_range = requests[0]["deleteContentRange"]["range"]
    assert delete_range["endIndex"] == int(target["endIndex"]) - 1
    expected = deepcopy(baseline.canonical_payload)
    expected_paragraph = expected["tabs"][0]["body"][0]
    expected_paragraph["endIndex"] += len("Business ")
    expected_paragraph["runs"][0]["endIndex"] += len("Business ")
    expected_paragraph["runs"][0]["text"] = f"{new_paragraph}\n"
    assert expected_paragraph["runs"][0]["text"].endswith("\n")
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)


def test_internal_insertion_is_widened_to_an_exact_plain_text_replacement() -> None:
    old_paragraph = "Agreement expires after 30 days."
    new_paragraph = "Agreement expires after 30 calendar days."
    target = _paragraph(old_paragraph, start=10)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    _, plan = _compile(change, baseline)

    assert (change.old_text, change.new_text) == ("days", "calendar days")
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical([_paragraph(new_paragraph, start=10)])
    )


@pytest.mark.parametrize(
    ("old_paragraph", "new_paragraph"),
    [
        ("Alpha Block", "Replacement Content"),
        ("Short", "Much Longer Version"),
    ],
)
def test_full_normal_text_replacement_supports_variable_lengths(
    old_paragraph: str, new_paragraph: str
) -> None:
    target = _paragraph(old_paragraph, start=10)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    proof, plan = _compile(change, baseline)

    assert proof.payload.location.edit_start_index == 10
    assert proof.payload.location.edit_end_index == int(target["endIndex"]) - 1
    expected = _canonical([_paragraph(new_paragraph, start=10)])
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)


@pytest.mark.parametrize(("named_style", "html_tag"), [("TITLE", "h1"), ("HEADING_3", "h3")])
def test_full_heading_or_title_replacement_preserves_paragraph_properties(
    named_style: str, html_tag: str
) -> None:
    old_heading = "Current Heading"
    new_heading = "Updated Title"
    paragraph_style = {
        "namedStyleType": named_style,
        "headingId": "h.stable-provider-id",
        "keepWithNext": True,
    }
    target = _paragraph(old_heading, start=10, paragraph_style=paragraph_style)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(
            old_html=f"<{html_tag}>{old_heading}</{html_tag}>",
            new_html=f"<{html_tag}>{new_heading}</{html_tag}>",
        )
    )

    proof, plan = _compile(change, baseline)

    assert proof.payload.location.edit_start_index == 10
    assert proof.payload.location.edit_end_index == int(target["endIndex"]) - 1
    expected = _canonical(
        [_paragraph(new_heading, start=10, paragraph_style=paragraph_style)]
    )
    expected_paragraph = expected["tabs"][0]["body"][0]
    assert expected_paragraph["paragraphStyle"] == paragraph_style
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)
    assert all(
        "updateParagraphStyle" not in request
        for request in plan.payload.provider_operations[0].requests
    )


def test_full_block_replacement_with_multiple_styled_runs_remains_unsupported() -> None:
    old_paragraph = "Vendor Agreement"
    new_paragraph = "Business Vendor Agreement"
    runs = [
        {
            "kind": "text",
            "startIndex": 10,
            "endIndex": 16,
            "text": "Vendor",
            "style": {"bold": True},
        },
        {
            "kind": "text",
            "startIndex": 16,
            "endIndex": 27,
            "text": " Agreement\n",
            "style": {},
        },
    ]
    target = _paragraph(old_paragraph, start=10, runs=runs)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(old_html=f"<p>{old_paragraph}</p>", new_html=f"<p>{new_paragraph}</p>")
    )

    with pytest.raises(MappingFailure) as error:
        map_replacement(change, baseline, NOW)

    assert error.value.code is MappingFailureCode.UNSUPPORTED_MULTIPLE_RUNS


def test_full_block_deletion_to_empty_remains_unsupported() -> None:
    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(
            _proposal(old_html="<p>Vendor Agreement</p>", new_html="<p></p>")
        )

    assert error.value.code is MappingFailureCode.NON_CONTIGUOUS_REPLACEMENT


@pytest.mark.parametrize(
    ("old_value", "new_value", "delta"),
    [
        ("45", "7", -1),
        ("30", "14 calendar", 9),
    ],
)
def test_variable_length_replacement_shifts_complete_trailing_postimage(
    old_value: str, new_value: str, delta: int
) -> None:
    old_paragraph = f"Payment is due within {old_value} days."
    target = _paragraph(old_paragraph)
    trailing = _paragraph("Trailing content stays exact.", start=240)
    baseline = _baseline(_canonical([target, trailing]))
    change = normalize_reviewed_change(
        _proposal(
            old_html=f"<p>{old_paragraph}</p>",
            new_html=f"<p>Payment is due within {new_value} days.</p>",
        )
    )

    proof, plan = _compile(change, baseline)

    assert change.old_text == old_value
    assert change.new_text == new_value
    assert proof.payload.eligibility.equal_utf16_length is (delta == 0)
    assert proof.payload.location.edit_start_index == 184
    assert proof.payload.location.edit_end_index == 184 + len(old_value)
    operation = plan.payload.provider_operations[0]
    delete_range = operation.requests[0]["deleteContentRange"]["range"]
    insert = operation.requests[1]["insertText"]
    assert delete_range["startIndex"] == 184
    assert delete_range["endIndex"] == 184 + len(old_value)
    assert insert["location"]["index"] == 184
    assert insert["text"] == new_value

    expected = deepcopy(baseline.canonical_payload)
    expected_body = expected["tabs"][0]["body"]
    expected_target = expected_body[0]
    expected_target["endIndex"] += delta
    expected_target["runs"][0]["endIndex"] += delta
    expected_target["runs"][0]["text"] = f"Payment is due within {new_value} days.\n"
    expected_body[1]["startIndex"] += delta
    expected_body[1]["endIndex"] += delta
    expected_body[1]["runs"][0]["startIndex"] += delta
    expected_body[1]["runs"][0]["endIndex"] += delta
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)
    assert expected_body[1]["runs"][0]["text"] == "Trailing content stays exact.\n"


@pytest.mark.parametrize(
    ("named_style", "html_tag"),
    [
        ("TITLE", "h1"),
        ("SUBTITLE", "h2"),
        ("HEADING_1", "h1"),
        ("HEADING_2", "h2"),
        ("HEADING_3", "h3"),
        ("HEADING_4", "h4"),
        ("HEADING_5", "h5"),
        ("HEADING_6", "h6"),
    ],
)
def test_supported_named_style_replacement_preserves_complete_paragraph_metadata(
    named_style: str, html_tag: str
) -> None:
    old_heading = "DocRelay Contract 45 Draft"
    new_heading = "DocRelay Contract 30 Draft"
    paragraph_style = {
        "namedStyleType": named_style,
        "headingId": "h.stable-provider-id",
        "direction": "LEFT_TO_RIGHT",
        "keepWithNext": True,
    }
    target = _paragraph(old_heading, start=10, paragraph_style=paragraph_style)
    baseline = _baseline(_canonical([target]))
    change = normalize_reviewed_change(
        _proposal(
            old_html=f'<{html_tag} data-chunk-id="same">{old_heading}</{html_tag}>',
            new_html=f'<{html_tag} data-chunk-id="same">{new_heading}</{html_tag}>',
        )
    )

    proof, plan = _compile(change, baseline)

    assert proof.payload.eligibility.supported_named_style == named_style
    expected = deepcopy(baseline.canonical_payload)
    expected_paragraph = expected["tabs"][0]["body"][0]
    expected_paragraph["runs"][0]["text"] = f"{new_heading}\n"
    assert expected_paragraph["paragraphStyle"] == paragraph_style
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)
    requests = plan.payload.provider_operations[0].requests
    assert all("updateParagraphStyle" not in request for request in requests)


def test_benign_wrapper_chain_normalizes_to_one_supported_block() -> None:
    change = normalize_reviewed_change(
        _proposal(
            old_html=(
                '<section data-layout="review">\n<div class="chunk">'
                '<h2 data-id="same">Payment is due within 45 days.</h2>'
                "</div>\n</section>"
            ),
            new_html=(
                '<section data-layout="review">\n<div class="chunk">'
                '<h2 data-id="same">Payment is due within 30 days.</h2>'
                "</div>\n</section>"
            ),
        )
    )

    assert change.old_paragraph == "Payment is due within 45 days."
    assert change.new_paragraph == "Payment is due within 30 days."
    assert change.old_text == "45"
    assert change.new_text == "30"


def test_live_omitted_zero_start_on_leading_section_break_is_supported() -> None:
    """The sanitized 2026-08-13 Google shape omits the zero-valued startIndex."""
    leading_section_break = {
        "startIndex": None,
        "endIndex": 1,
        "type": "sectionBreak",
        "sectionStyle": {},
    }
    target = _paragraph(start=1)
    baseline = _baseline(_canonical([leading_section_break, target]))
    change = normalize_reviewed_change(_proposal())

    proof, plan = _compile(change, baseline)

    assert proof.payload.location.structural_element_index == 1
    operation = plan.payload.provider_operations[0]
    assert operation.requests[0]["deleteContentRange"]["range"]["startIndex"] == 23
    assert plan.payload.expected_postimage.canonical_payload["structural_element_index"] == 1
    # The compiler establishes that this exact provider omission means zero, but
    # preserves the canonical shape and never invents a writable range from it.
    expected = deepcopy(baseline.canonical_payload)
    expected["tabs"][0]["body"][1]["runs"][0]["text"] = "Payment is due within 30 days.\n"
    assert expected["tabs"][0]["body"][0]["startIndex"] is None
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(expected)


@pytest.mark.parametrize(
    "leading_section_break",
    [
        {
            "startIndex": "0",
            "endIndex": 1,
            "type": "sectionBreak",
            "sectionStyle": {},
        },
        {
            "startIndex": {},
            "endIndex": 1,
            "type": "sectionBreak",
            "sectionStyle": {},
        },
        {
            "startIndex": -1,
            "endIndex": 1,
            "type": "sectionBreak",
            "sectionStyle": {},
        },
        {
            "startIndex": 2,
            "endIndex": 1,
            "type": "sectionBreak",
            "sectionStyle": {},
        },
        {
            "startIndex": None,
            "endIndex": 2,
            "type": "sectionBreak",
            "sectionStyle": {},
        },
    ],
)
def test_malformed_or_impossible_leading_indexes_never_produce_a_write_plan(
    leading_section_break: dict[str, object],
) -> None:
    baseline = _baseline(_canonical([leading_section_break, _paragraph(start=1)]))
    change = normalize_reviewed_change(_proposal())
    proof = map_replacement(change, baseline, created_at=NOW)

    with pytest.raises(MappingFailure) as error:
        compile_write_plan(
            change=change,
            baseline=baseline,
            proof=proof,
            sync_run_id=UUID("00000000-0000-0000-0000-000000000301"),
            rule_identity=UUID("00000000-0000-0000-0000-000000000302"),
            rule_version=1,
            instruction_sha256=ZERO_HASH,
            configuration_sha256=ONE_HASH,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )

    assert error.value.code is MappingFailureCode.MALFORMED_SNAPSHOT


@pytest.mark.parametrize(
    ("proposal", "code"),
    [
        (_proposal(decision=ChangeDecision.REJECT), MappingFailureCode.NOT_APPROVED),
        (_proposal(decision=None, decision_id=None), MappingFailureCode.UNDECIDED),
        (_proposal(superseded=True), MappingFailureCode.SUPERSEDED),
        (_proposal(lineage_current=False), MappingFailureCode.STALE_LINEAGE),
    ],
)
def test_non_current_or_non_approved_proposal_fails_closed(
    proposal: ReviewedProposal, code: MappingFailureCode
) -> None:
    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(proposal)
    assert error.value.code is code


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"operation": ProposalOperation.CREATE}, MappingFailureCode.UNSUPPORTED_OPERATION),
        (
            {"new_html": '<p data-id="changed">Payment is due within 30 days.</p>'},
            MappingFailureCode.FORMATTING_DELTA,
        ),
        (
            {
                "old_html": "<p>Payment is due within café days.</p>",
                "new_html": "<p>Payment is due within bistro days.</p>",
            },
            MappingFailureCode.NON_ASCII_REPLACEMENT,
        ),
        (
            {"new_html": '<p data-id="same">Payment is due within 30\tdays.</p>'},
            MappingFailureCode.NON_ASCII_REPLACEMENT,
        ),
    ],
)
def test_normalization_rejects_changes_outside_proven_subset(
    changes: dict[str, object], code: MappingFailureCode
) -> None:
    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(_proposal(**changes))
    assert error.value.code is code


def test_live_create_proposal_is_not_reclassified_as_a_plain_text_replacement() -> None:
    """Sanitized shape persisted for the 2026-08-10 live add-at-end proposal."""
    proposal = _proposal(
        operation=ProposalOperation.CREATE,
        chunk_id="new",
        old_html=None,
        new_html=(
            '<div style="width: 100%; border-top: 2px solid #333; margin-top: 30px; '
            'padding-top: 10px; font-family: sans-serif;">'
            '<table style="width: 100%; border-collapse: collapse; border: none;">'
            "<tr><td><p>Representative:</p><p>Omkar Bansod</p></td>"
            "<td><p>Date:</p><p>August 10, 2026</p></td></tr>"
            "</table></div>"
        ),
    )

    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(proposal)

    assert error.value.code is MappingFailureCode.UNSUPPORTED_OPERATION
    assert str(error.value) == "only reviewed edit proposals are supported"


def test_paragraph_boundary_replacement_is_unsupported() -> None:
    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(
            _proposal(new_html="<p>Payment is due within 30 days.</p><p>Added paragraph.</p>")
        )

    assert error.value.code is MappingFailureCode.FORMATTING_DELTA


@pytest.mark.parametrize(
    "new_html",
    [
        "<table><tr><td>Payment is due within 30 days.</td></tr></table>",
        "<ul><li>Payment is due within 30 days.</li></ul>",
        (
            "<div><p>Payment is due within 30 days.</p>"
            "<span hidden>Undisclosed sibling content.</span></div>"
        ),
    ],
)
def test_structural_or_hidden_sibling_proposal_remains_unsupported(new_html: str) -> None:
    with pytest.raises(MappingFailure) as error:
        normalize_reviewed_change(_proposal(new_html=new_html))

    assert error.value.code in {
        MappingFailureCode.MALFORMED_REVIEW_HTML,
        MappingFailureCode.FORMATTING_DELTA,
    }
    assert error.value.safe_message == (
        "DocRelay can safely write text changes to a single supported paragraph or heading. "
        "This proposal changes unsupported document structure."
    )


def test_old_preimage_missing_fails_closed() -> None:
    change = normalize_reviewed_change(_proposal())
    with pytest.raises(MappingFailure) as error:
        map_replacement(change, _baseline(_canonical([_paragraph("Unrelated text.")])), NOW)
    assert error.value.code is MappingFailureCode.PREIMAGE_MISSING


def test_duplicate_old_preimage_is_ambiguous() -> None:
    change = normalize_reviewed_change(_proposal())
    payload = _canonical([_paragraph(start=10), _paragraph(start=100)])
    with pytest.raises(MappingFailure) as error:
        map_replacement(change, _baseline(payload), NOW)
    assert error.value.code is MappingFailureCode.AMBIGUOUS_PREIMAGE
    assert error.value.candidate_count == 2


def test_table_location_is_unsupported() -> None:
    change = normalize_reviewed_change(_proposal())
    table = {
        "startIndex": 10,
        "endIndex": 100,
        "type": "table",
        "rows": 1,
        "columns": 1,
        "tableRows": [
            {
                "cells": [{"content": [_paragraph(start=12)], "tableCellStyle": {}}],
                "tableRowStyle": {},
            }
        ],
        "tableStyle": {},
    }
    with pytest.raises(MappingFailure) as error:
        map_replacement(change, _baseline(_canonical([table])), NOW)
    assert error.value.code is MappingFailureCode.UNSUPPORTED_TABLE_LOCATION


def test_list_paragraph_is_unsupported() -> None:
    change = normalize_reviewed_change(_proposal())
    payload = _canonical([_paragraph(bullet={"listId": "list-a"})])
    with pytest.raises(MappingFailure) as error:
        map_replacement(change, _baseline(payload), NOW)
    assert error.value.code is MappingFailureCode.UNSUPPORTED_LIST_PARAGRAPH


def test_multiple_runs_or_formatting_boundary_is_unsupported() -> None:
    change = normalize_reviewed_change(_proposal())
    runs = [
        {
            "kind": "text",
            "startIndex": 162,
            "endIndex": 184,
            "text": "Payment is due within ",
            "style": {},
        },
        {
            "kind": "text",
            "startIndex": 184,
            "endIndex": 192,
            "text": "45 days.\n",
            "style": {"bold": True},
        },
    ]
    payload = _canonical([_paragraph(runs=runs)])
    with pytest.raises(MappingFailure) as error:
        map_replacement(change, _baseline(payload), NOW)
    assert error.value.code is MappingFailureCode.UNSUPPORTED_MULTIPLE_RUNS


@pytest.mark.parametrize(
    "baseline",
    [
        _baseline(run_baseline_revision_id="revision-B"),
        _baseline(capture_revision_id="revision-B"),
    ],
)
def test_wrong_google_revision_fails_closed(baseline: BaselineSnapshot) -> None:
    with pytest.raises(MappingFailure) as error:
        map_replacement(normalize_reviewed_change(_proposal()), baseline, NOW)
    assert error.value.code is MappingFailureCode.WRONG_REVISION


def test_malformed_provider_snapshot_fails_closed() -> None:
    canonical = _canonical()
    canonical["tabs"] = "not-a-list"
    with pytest.raises(MappingFailure) as error:
        map_replacement(
            normalize_reviewed_change(_proposal()),
            _baseline(canonical),
            NOW,
        )
    assert error.value.code is MappingFailureCode.MALFORMED_SNAPSHOT


@pytest.mark.parametrize("bad_start", [None, "1", {}, -1])
def test_target_paragraph_start_must_be_an_established_nonnegative_integer(
    bad_start: object,
) -> None:
    paragraph = _paragraph()
    paragraph["startIndex"] = bad_start
    with pytest.raises(MappingFailure) as error:
        map_replacement(
            normalize_reviewed_change(_proposal()),
            _baseline(_canonical([paragraph])),
            NOW,
        )

    assert error.value.code is MappingFailureCode.MALFORMED_SNAPSHOT


def test_mapping_rejects_snapshot_hash_mismatch() -> None:
    with pytest.raises(MappingFailure) as error:
        map_replacement(
            normalize_reviewed_change(_proposal()),
            _baseline(native_canonical_sha256=ZERO_HASH),
            NOW,
        )
    assert error.value.code is MappingFailureCode.STALE_SNAPSHOT


def test_plan_is_frozen_and_deterministic_and_changed_input_changes_identity() -> None:
    change, baseline, proof = _supported_mapping()
    kwargs = {
        "change": change,
        "baseline": baseline,
        "proof": proof,
        "sync_run_id": UUID("00000000-0000-0000-0000-000000000301"),
        "rule_identity": UUID("00000000-0000-0000-0000-000000000302"),
        "rule_version": 1,
        "instruction_sha256": ZERO_HASH,
        "configuration_sha256": ONE_HASH,
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=24),
    }
    first = compile_write_plan(**kwargs)
    second = compile_write_plan(**kwargs)
    assert first == second
    assert first.integrity_sha256 == second.integrity_sha256

    changed = compile_write_plan(**(kwargs | {"configuration_sha256": TWO_HASH}))
    assert changed.integrity_sha256 != first.integrity_sha256

    tampered = deepcopy(first.model_dump(mode="json"))
    tampered["integrity_sha256"] = ZERO_HASH
    with pytest.raises(ValidationError, match="integrity mismatch"):
        SealedWritePlan.model_validate(tampered)
