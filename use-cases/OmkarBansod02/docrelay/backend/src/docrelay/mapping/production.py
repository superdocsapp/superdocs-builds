import hashlib
import re
from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any, Literal, NoReturn, Self, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from docrelay.domain.enums import ChangeDecision, ProposalOperation, Provider
from docrelay.domain.write_plan import (
    ApprovalLineageContract,
    ExpectedPostimageContract,
    ExpectedReplacementContract,
    GoogleDocsBatchUpdate,
    MappingProofContract,
    PlannedReplacementContract,
    RuleContract,
    SealedWritePlan,
    Sha256,
    SourceSnapshotContract,
    WritePlanPayload,
    canonical_json_bytes,
)
from docrelay.integrations.google.canonical import sha256_json

MAPPER_VERSION = "docrelay.google-supported-block-mapper.v5"
COMPILER_VERSION = "docrelay.google-write-plan-compiler.v5"
MAPPING_SCHEMA_VERSION = "docrelay.mapping-proof.v1"
VERIFIER_VERSION = "docrelay.google-native-canonical.v2"
_ASCII_PLAIN_TEXT = re.compile(r"[A-Za-z0-9]+(?: [A-Za-z0-9]+)*")
_SUPPORTED_REVIEW_BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6"})
_BENIGN_REVIEW_WRAPPER_TAGS = frozenset({"div", "section"})
_SUPPORTED_NAMED_STYLES = frozenset(
    {
        "NORMAL_TEXT",
        "TITLE",
        "SUBTITLE",
        "HEADING_1",
        "HEADING_2",
        "HEADING_3",
        "HEADING_4",
        "HEADING_5",
        "HEADING_6",
    }
)

type SupportedNamedStyle = Literal[
    "NORMAL_TEXT",
    "TITLE",
    "SUBTITLE",
    "HEADING_1",
    "HEADING_2",
    "HEADING_3",
    "HEADING_4",
    "HEADING_5",
    "HEADING_6",
]
type ReviewBlockSignature = tuple[tuple[str, tuple[tuple[str, str | None], ...]], ...]


class MappingFailureCode(StrEnum):
    NOT_APPROVED = "NOT_APPROVED"
    UNDECIDED = "UNDECIDED"
    UNSUPPORTED_MULTIPLE_APPROVED_PROPOSALS = "UNSUPPORTED_MULTIPLE_APPROVED_PROPOSALS"
    OVERLAPPING_MAPPED_RANGES = "OVERLAPPING_MAPPED_RANGES"
    DUPLICATE_TARGET_MAPPING = "DUPLICATE_TARGET_MAPPING"
    SUPERSEDED = "SUPERSEDED"
    STALE_LINEAGE = "STALE_LINEAGE"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    MALFORMED_REVIEW_HTML = "MALFORMED_REVIEW_HTML"
    FORMATTING_DELTA = "FORMATTING_DELTA"
    NON_CONTIGUOUS_REPLACEMENT = "NON_CONTIGUOUS_REPLACEMENT"
    NON_INTERNAL_REPLACEMENT = "NON_INTERNAL_REPLACEMENT"
    NON_ASCII_REPLACEMENT = "NON_ASCII_REPLACEMENT"
    WRONG_REVISION = "WRONG_REVISION"
    STALE_SNAPSHOT = "STALE_SNAPSHOT"
    MALFORMED_SNAPSHOT = "MALFORMED_SNAPSHOT"
    PREIMAGE_MISSING = "PREIMAGE_MISSING"
    AMBIGUOUS_PREIMAGE = "AMBIGUOUS_PREIMAGE"
    UNSUPPORTED_TABLE_LOCATION = "UNSUPPORTED_TABLE_LOCATION"
    UNSUPPORTED_NON_BODY_LOCATION = "UNSUPPORTED_NON_BODY_LOCATION"
    UNSUPPORTED_LIST_PARAGRAPH = "UNSUPPORTED_LIST_PARAGRAPH"
    UNSUPPORTED_PARAGRAPH_STYLE = "UNSUPPORTED_PARAGRAPH_STYLE"
    UNSUPPORTED_MULTIPLE_RUNS = "UNSUPPORTED_MULTIPLE_RUNS"
    UNSUPPORTED_TEXT_STYLE = "UNSUPPORTED_TEXT_STYLE"
    UNSUPPORTED_STRUCTURAL_LOCATION = "UNSUPPORTED_STRUCTURAL_LOCATION"
    EXISTING_PLAN_LINEAGE_MISMATCH = "EXISTING_PLAN_LINEAGE_MISMATCH"


class MappingFailure(ValueError):
    def __init__(
        self,
        code: MappingFailureCode,
        message: str,
        *,
        candidate_count: int | None = None,
        proposal_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.candidate_count = candidate_count
        self.proposal_id = proposal_id


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewedProposal(_FrozenModel):
    proposal_id: UUID
    decision_id: UUID | None
    decision: ChangeDecision | None
    decision_sha256: Sha256 | None
    superseded: bool
    operation: ProposalOperation
    review_round: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    session_document_id: str = Field(min_length=1)
    durable_document_id: str | None = None
    job_id: str = Field(min_length=1)
    superdocs_export_id: UUID
    approved_export_sha256: Sha256
    final_version_id: str | None = None
    superdocs_change_id: str = Field(min_length=1)
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    lineage_current: bool


class SemanticReplacement(_FrozenModel):
    proposal_id: UUID
    decision_id: UUID
    decision_sha256: Sha256
    review_round: int
    session_id: str
    session_document_id: str
    durable_document_id: str | None
    job_id: str
    superdocs_export_id: UUID
    approved_export_sha256: Sha256
    final_version_id: str | None
    superdocs_change_id: str
    chunk_id: str
    old_html_sha256: Sha256
    new_html_sha256: Sha256
    old_paragraph: str
    new_paragraph: str
    old_text: str
    new_text: str
    prefix: str
    suffix: str


class BaselineSnapshot(_FrozenModel):
    snapshot_id: UUID
    provider: Literal[Provider.GOOGLE]
    provider_principal_subject: str = Field(min_length=1)
    provider_file_id: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = Field(min_length=1)
    baseline_revision_id: str = Field(min_length=1)
    run_baseline_revision_id: str = Field(min_length=1)
    capture_revision_id: str = Field(min_length=1)
    native_raw_sha256: Sha256
    native_canonical_sha256: Sha256
    exported_docx_sha256: Sha256
    canonical_payload: dict[str, JsonValue]


class ProofLineage(_FrozenModel):
    proposal_id: UUID
    decision_id: UUID
    decision_sha256: Sha256
    review_round: int
    session_id: str
    session_document_id: str
    durable_document_id: str | None
    job_id: str
    superdocs_export_id: UUID
    approved_export_sha256: Sha256
    final_version_id: str | None
    superdocs_change_id: str
    chunk_id: str
    old_html_sha256: Sha256
    new_html_sha256: Sha256


class ProviderLocation(_FrozenModel):
    tab_id: str = Field(min_length=1)
    segment_id: Literal[""] = ""
    structural_element_index: int = Field(ge=0)
    paragraph_start_index: int = Field(ge=0)
    paragraph_end_index: int = Field(gt=0)
    text_run_index: Literal[0] = 0
    text_run_start_index: int = Field(ge=0)
    text_run_end_index: int = Field(gt=0)
    edit_start_index: int = Field(ge=0)
    edit_end_index: int = Field(gt=0)


class LegacyStructuralEligibility(_FrozenModel):
    one_root_tab: Literal[True] = True
    body_segment: Literal[True] = True
    top_level_paragraph: Literal[True] = True
    normal_text: Literal[True] = True
    non_list: Literal[True] = True
    one_plain_text_run: Literal[True] = True
    no_formatting_delta: Literal[True] = True
    internal_ascii_token: Literal[True] = True
    equal_utf16_length: bool
    exact_preimage: Literal[True] = True
    minimum_range: Literal[True] = True


class SupportedBlockStructuralEligibility(_FrozenModel):
    one_root_tab: Literal[True] = True
    body_segment: Literal[True] = True
    top_level_paragraph: Literal[True] = True
    supported_named_style: SupportedNamedStyle
    non_list: Literal[True] = True
    one_plain_text_run: Literal[True] = True
    no_formatting_delta: Literal[True] = True
    internal_ascii_token: Literal[True] = True
    equal_utf16_length: bool
    exact_preimage: Literal[True] = True
    minimum_range: Literal[True] = True


class StructuralEligibility(_FrozenModel):
    one_root_tab: Literal[True] = True
    body_segment: Literal[True] = True
    top_level_paragraph: Literal[True] = True
    supported_named_style: SupportedNamedStyle
    non_list: Literal[True] = True
    one_plain_text_run: Literal[True] = True
    no_formatting_delta: Literal[True] = True
    contiguous_ascii_text: Literal[True] = True
    equal_utf16_length: bool
    exact_preimage: Literal[True] = True
    minimum_range: Literal[True] = True


class MappedReplacement(_FrozenModel):
    lineage: ProofLineage
    old_text: str
    new_text: str
    old_text_sha256: Sha256
    new_text_sha256: Sha256
    old_paragraph_sha256: Sha256
    new_paragraph_sha256: Sha256
    location: ProviderLocation
    candidate_count: Literal[1] = 1
    eligibility: (
        LegacyStructuralEligibility | SupportedBlockStructuralEligibility | StructuralEligibility
    )


class MappingProofPayload(_FrozenModel):
    schema_version: Literal["docrelay.mapping-proof.v1"] = "docrelay.mapping-proof.v1"
    mapper_version: Literal[
        "docrelay.google-plain-token-mapper.v1",
        "docrelay.google-plain-text-mapper.v2",
        "docrelay.google-plain-text-mapper.v3",
        "docrelay.google-supported-block-mapper.v4",
        "docrelay.google-supported-block-mapper.v5",
    ] = "docrelay.google-supported-block-mapper.v5"
    status: Literal["SUPPORTED"] = "SUPPORTED"
    status_reason: Literal[
        "ALL_V1_CONSTRAINTS_PASSED",
        "ALL_SUPPORTED_CONSTRAINTS_PASSED",
    ] = "ALL_SUPPORTED_CONSTRAINTS_PASSED"
    created_at: datetime
    source_snapshot_id: UUID
    provider_file_id: str
    baseline_revision_id: str
    native_snapshot_sha256: Sha256
    native_raw_sha256: Sha256
    lineage: ProofLineage
    old_text: str
    new_text: str
    old_text_sha256: Sha256
    new_text_sha256: Sha256
    old_paragraph_sha256: Sha256
    new_paragraph_sha256: Sha256
    location: ProviderLocation
    replacements: tuple[MappedReplacement, ...] = Field(min_length=1)
    candidate_count: Literal[1] = 1
    eligibility: (
        LegacyStructuralEligibility | SupportedBlockStructuralEligibility | StructuralEligibility
    )

    @model_validator(mode="after")
    def replacements_match_singular_fields(self) -> Self:
        first = self.replacements[0]
        if (
            first.lineage != self.lineage
            or first.old_text != self.old_text
            or first.new_text != self.new_text
            or first.old_text_sha256 != self.old_text_sha256
            or first.new_text_sha256 != self.new_text_sha256
            or first.old_paragraph_sha256 != self.old_paragraph_sha256
            or first.new_paragraph_sha256 != self.new_paragraph_sha256
            or first.location != self.location
            or first.eligibility != self.eligibility
            or first.candidate_count != self.candidate_count
        ):
            raise ValueError("MappingProof singular fields must match the first mapped replacement")
        proposal_ids = [item.lineage.proposal_id for item in self.replacements]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("MappingProof replacements must preserve unique proposal identity")
        ordered = tuple(
            sorted(
                self.replacements,
                key=lambda item: (
                    item.location.edit_start_index,
                    item.location.edit_end_index,
                    str(item.lineage.proposal_id),
                ),
            )
        )
        if ordered != self.replacements:
            raise ValueError("MappingProof replacements must be in deterministic document order")
        return self


class SealedMappingProof(_FrozenModel):
    mapping_proof_id: UUID
    payload: MappingProofPayload
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def verify_integrity(self) -> Self:
        calculated = _hash_model(self.payload)
        if calculated != self.integrity_sha256:
            raise ValueError("MappingProof integrity mismatch")
        if self.mapping_proof_id != _identity("mapping-proof", calculated):
            raise ValueError("MappingProof deterministic identity mismatch")
        return self

    @classmethod
    def seal(cls, payload: MappingProofPayload) -> "SealedMappingProof":
        integrity = _hash_model(payload)
        return cls(
            mapping_proof_id=_identity("mapping-proof", integrity),
            payload=payload,
            integrity_sha256=integrity,
        )


class _SupportedBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.signature: list[tuple[str, tuple[tuple[str, str | None], ...]]] = []
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.block_count = 0
        self.block_closed = False
        self.invalid = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len({name for name, _ in attrs}) != len(attrs) or self.block_closed:
            self.invalid = True
            return
        normalized_attrs = tuple(sorted(attrs))
        if tag in _BENIGN_REVIEW_WRAPPER_TAGS:
            if self.block_count or any(item in _SUPPORTED_REVIEW_BLOCK_TAGS for item in self.stack):
                self.invalid = True
                return
        elif tag in _SUPPORTED_REVIEW_BLOCK_TAGS:
            if self.block_count or any(item in _SUPPORTED_REVIEW_BLOCK_TAGS for item in self.stack):
                self.invalid = True
                return
            self.block_count = 1
        else:
            self.invalid = True
            return
        self.signature.append((tag, normalized_attrs))
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.invalid = True

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.invalid = True
            return
        self.stack.pop()
        if tag in _SUPPORTED_REVIEW_BLOCK_TAGS:
            self.block_closed = True

    def handle_data(self, data: str) -> None:
        if not any(item in _SUPPORTED_REVIEW_BLOCK_TAGS for item in self.stack):
            if data.strip():
                self.invalid = True
            return
        self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        self.invalid = True

    def handle_decl(self, decl: str) -> None:
        self.invalid = True

    def handle_pi(self, data: str) -> None:
        self.invalid = True

    def unknown_decl(self, data: str) -> None:
        self.invalid = True


def normalize_reviewed_change(proposal: ReviewedProposal) -> SemanticReplacement:
    if proposal.decision is None or proposal.decision_id is None:
        raise MappingFailure(MappingFailureCode.UNDECIDED, "proposal has no decision")
    if proposal.decision is not ChangeDecision.APPROVE:
        raise MappingFailure(MappingFailureCode.NOT_APPROVED, "proposal was not approved")
    if proposal.decision_sha256 is None:
        raise MappingFailure(MappingFailureCode.STALE_LINEAGE, "decision identity is incomplete")
    if proposal.superseded:
        raise MappingFailure(MappingFailureCode.SUPERSEDED, "proposal has been superseded")
    if not proposal.lineage_current:
        raise MappingFailure(MappingFailureCode.STALE_LINEAGE, "proposal lineage is stale")
    if proposal.operation is not ProposalOperation.EDIT:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_OPERATION,
            "only reviewed edit proposals are supported",
        )
    if proposal.chunk_id is None or proposal.old_html is None or proposal.new_html is None:
        raise MappingFailure(
            MappingFailureCode.MALFORMED_REVIEW_HTML,
            "proposal lacks strict edit evidence",
        )

    old_signature, old_paragraph = _parse_supported_block(proposal.old_html)
    new_signature, new_paragraph = _parse_supported_block(proposal.new_html)
    if old_signature != new_signature:
        raise MappingFailure(
            MappingFailureCode.FORMATTING_DELTA,
            "proposal block structure or attributes changed",
        )
    prefix_length = 0
    maximum_prefix = min(len(old_paragraph), len(new_paragraph))
    while (
        prefix_length < maximum_prefix
        and old_paragraph[prefix_length] == new_paragraph[prefix_length]
    ):
        prefix_length += 1
    suffix_length = 0
    maximum_suffix = min(
        len(old_paragraph) - prefix_length,
        len(new_paragraph) - prefix_length,
    )
    while (
        suffix_length < maximum_suffix
        and old_paragraph[len(old_paragraph) - suffix_length - 1]
        == new_paragraph[len(new_paragraph) - suffix_length - 1]
    ):
        suffix_length += 1
    old_end = len(old_paragraph) - suffix_length if suffix_length else len(old_paragraph)
    new_end = len(new_paragraph) - suffix_length if suffix_length else len(new_paragraph)
    old_text = old_paragraph[prefix_length:old_end]
    new_text = new_paragraph[prefix_length:new_end]
    prefix = old_paragraph[:prefix_length]
    suffix = old_paragraph[old_end:]
    if not old_text and new_text:
        if not prefix or not suffix:
            # A boundary insertion has no deletable minimal preimage. Widen it to
            # the proven visible block so the operation remains a non-empty text
            # replacement and the provider terminator remains outside the range.
            old_text = old_paragraph
            new_text = new_paragraph
            prefix = ""
            suffix = ""
        else:
            # Keep an internal insertion narrow by borrowing one unchanged plain
            # token from the suffix. This preserves a non-empty exact preimage.
            borrowed = re.match(r"[A-Za-z0-9]+", suffix)
            if borrowed is not None:
                token = borrowed.group()
                old_text = token
                new_text = f"{new_text}{token}"
                old_end += len(token)
                suffix = old_paragraph[old_end:]
    if not old_text or not new_text:
        raise MappingFailure(
            MappingFailureCode.NON_CONTIGUOUS_REPLACEMENT,
            "create/delete deltas are unsupported",
        )
    if (
        _ASCII_PLAIN_TEXT.fullmatch(old_text) is None
        or _ASCII_PLAIN_TEXT.fullmatch(new_text) is None
    ):
        raise MappingFailure(
            MappingFailureCode.NON_ASCII_REPLACEMENT,
            "replacement must be ordinary space-separated ASCII text",
        )
    return SemanticReplacement(
        proposal_id=proposal.proposal_id,
        decision_id=proposal.decision_id,
        decision_sha256=proposal.decision_sha256,
        review_round=proposal.review_round,
        session_id=proposal.session_id,
        session_document_id=proposal.session_document_id,
        durable_document_id=proposal.durable_document_id,
        job_id=proposal.job_id,
        superdocs_export_id=proposal.superdocs_export_id,
        approved_export_sha256=proposal.approved_export_sha256,
        final_version_id=proposal.final_version_id,
        superdocs_change_id=proposal.superdocs_change_id,
        chunk_id=proposal.chunk_id,
        old_html_sha256=_sha256_text(proposal.old_html),
        new_html_sha256=_sha256_text(proposal.new_html),
        old_paragraph=old_paragraph,
        new_paragraph=new_paragraph,
        old_text=old_text,
        new_text=new_text,
        prefix=prefix,
        suffix=suffix,
    )


def map_replacement(
    change: SemanticReplacement,
    baseline: BaselineSnapshot,
    created_at: datetime,
) -> SealedMappingProof:
    if not (
        baseline.baseline_revision_id
        == baseline.run_baseline_revision_id
        == baseline.capture_revision_id
    ):
        raise MappingFailure(
            MappingFailureCode.WRONG_REVISION,
            "baseline revision lineage does not match",
        )
    if sha256_json(baseline.canonical_payload) != baseline.native_canonical_sha256:
        raise MappingFailure(
            MappingFailureCode.STALE_SNAPSHOT,
            "persisted native snapshot hash does not match",
        )

    tab, body, tab_id = _one_root_tab(baseline.canonical_payload)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, element in enumerate(body):
        if not isinstance(element, dict):
            _malformed("body structural element is malformed")
        if element.get("type") == "paragraph":
            if _paragraph_text(element) == change.old_paragraph:
                candidates.append((index, element))
        elif element.get("type") not in {
            "sectionBreak",
            "table",
            "tableOfContents",
            "unknown",
        }:
            _malformed("unknown body structural type")

    if len(candidates) > 1:
        raise MappingFailure(
            MappingFailureCode.AMBIGUOUS_PREIMAGE,
            "approved paragraph preimage has multiple baseline candidates",
            candidate_count=len(candidates),
        )
    if not candidates:
        nested_kind = _find_unsupported_location(tab, change.old_paragraph)
        if nested_kind == "table":
            raise MappingFailure(
                MappingFailureCode.UNSUPPORTED_TABLE_LOCATION,
                "approved preimage is inside a table",
                candidate_count=0,
            )
        if nested_kind is not None:
            raise MappingFailure(
                MappingFailureCode.UNSUPPORTED_NON_BODY_LOCATION,
                "approved preimage is outside the document body",
                candidate_count=0,
            )
        raise MappingFailure(
            MappingFailureCode.PREIMAGE_MISSING,
            "approved paragraph preimage is absent from baseline",
            candidate_count=0,
        )

    structural_index, paragraph = candidates[0]
    if paragraph.get("bullet") is not None:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_LIST_PARAGRAPH,
            "list paragraphs are outside the proven subset",
            candidate_count=1,
        )
    style = paragraph.get("paragraphStyle")
    if not isinstance(style, dict):
        _malformed("paragraph style is malformed")
    named_style = style.get("namedStyleType")
    if named_style not in _SUPPORTED_NAMED_STYLES:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_PARAGRAPH_STYLE,
            "paragraph named style is outside the supported text-bearing set",
            candidate_count=1,
        )
    if paragraph.get("positionedObjectIds") not in (None, []):
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_STRUCTURAL_LOCATION,
            "paragraph contains positioned objects",
            candidate_count=1,
        )
    runs = paragraph.get("runs")
    if not isinstance(runs, list) or len(runs) != 1:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_MULTIPLE_RUNS,
            "paragraph must contain exactly one text run",
            candidate_count=1,
        )
    run = runs[0]
    if not isinstance(run, dict) or run.get("kind") != "text":
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_STRUCTURAL_LOCATION,
            "paragraph run is not plain text",
            candidate_count=1,
        )
    if run.get("style") != {}:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_TEXT_STYLE,
            "explicit text styles are outside the proven subset",
            candidate_count=1,
        )
    paragraph_start = _integer_index(paragraph, "startIndex")
    paragraph_end = _integer_index(paragraph, "endIndex")
    run_start = _integer_index(run, "startIndex")
    run_end = _integer_index(run, "endIndex")
    run_text = run.get("text")
    if (
        not isinstance(run_text, str)
        or run_text != f"{change.old_paragraph}\n"
        or paragraph_start != run_start
        or paragraph_end != run_end
        or run_end - run_start != _utf16_length(run_text)
    ):
        _malformed("paragraph indexes do not match the persisted UTF-16 text run")
    edit_start = run_start + _utf16_length(change.prefix)
    edit_end = edit_start + _utf16_length(change.old_text)
    visible_text_end = run_end - _utf16_length("\n")
    if edit_start < run_start or edit_end > visible_text_end:
        raise MappingFailure(
            MappingFailureCode.NON_CONTIGUOUS_REPLACEMENT,
            "replacement range must stay within visible paragraph text",
            candidate_count=1,
        )

    lineage = ProofLineage(
        proposal_id=change.proposal_id,
        decision_id=change.decision_id,
        decision_sha256=change.decision_sha256,
        review_round=change.review_round,
        session_id=change.session_id,
        session_document_id=change.session_document_id,
        durable_document_id=change.durable_document_id,
        job_id=change.job_id,
        superdocs_export_id=change.superdocs_export_id,
        approved_export_sha256=change.approved_export_sha256,
        final_version_id=change.final_version_id,
        superdocs_change_id=change.superdocs_change_id,
        chunk_id=change.chunk_id,
        old_html_sha256=change.old_html_sha256,
        new_html_sha256=change.new_html_sha256,
    )
    location = ProviderLocation(
        tab_id=tab_id,
        structural_element_index=structural_index,
        paragraph_start_index=paragraph_start,
        paragraph_end_index=paragraph_end,
        text_run_start_index=run_start,
        text_run_end_index=run_end,
        edit_start_index=edit_start,
        edit_end_index=edit_end,
    )
    eligibility = StructuralEligibility(
        supported_named_style=cast(SupportedNamedStyle, named_style),
        equal_utf16_length=_utf16_length(change.old_text) == _utf16_length(change.new_text),
    )
    mapped = MappedReplacement(
        lineage=lineage,
        old_text=change.old_text,
        new_text=change.new_text,
        old_text_sha256=_sha256_text(change.old_text),
        new_text_sha256=_sha256_text(change.new_text),
        old_paragraph_sha256=_sha256_text(change.old_paragraph),
        new_paragraph_sha256=_sha256_text(change.new_paragraph),
        location=location,
        eligibility=eligibility,
    )
    payload = MappingProofPayload(
        created_at=created_at,
        source_snapshot_id=baseline.snapshot_id,
        provider_file_id=baseline.provider_file_id,
        baseline_revision_id=baseline.baseline_revision_id,
        native_snapshot_sha256=baseline.native_canonical_sha256,
        native_raw_sha256=baseline.native_raw_sha256,
        lineage=lineage,
        old_text=change.old_text,
        new_text=change.new_text,
        old_text_sha256=mapped.old_text_sha256,
        new_text_sha256=mapped.new_text_sha256,
        old_paragraph_sha256=mapped.old_paragraph_sha256,
        new_paragraph_sha256=mapped.new_paragraph_sha256,
        location=location,
        replacements=(mapped,),
        eligibility=eligibility,
    )
    return SealedMappingProof.seal(payload)


def map_approved_replacements(
    changes: tuple[SemanticReplacement, ...],
    baseline: BaselineSnapshot,
    created_at: datetime,
) -> SealedMappingProof:
    if not changes:
        raise MappingFailure(
            MappingFailureCode.NOT_APPROVED,
            "review has no approved writable proposal",
        )
    proofs: list[SealedMappingProof] = []
    for change in changes:
        try:
            proofs.append(map_replacement(change, baseline, created_at))
        except MappingFailure as exc:
            raise MappingFailure(
                exc.code,
                (
                    f"approved proposal {change.proposal_id} cannot be safely mapped: "
                    f"{exc.safe_message}"
                ),
                candidate_count=exc.candidate_count,
                proposal_id=change.proposal_id,
            ) from exc
    return seal_mapped_set(tuple(proofs), created_at=created_at)


def seal_mapped_set(
    proofs: tuple[SealedMappingProof, ...],
    *,
    created_at: datetime,
) -> SealedMappingProof:
    if not proofs:
        raise MappingFailure(
            MappingFailureCode.NOT_APPROVED,
            "review has no approved writable proposal",
        )
    first_payload = proofs[0].payload
    replacements = tuple(
        sorted(
            (item for proof in proofs for item in proof.payload.replacements),
            key=lambda item: (
                item.location.edit_start_index,
                item.location.edit_end_index,
                str(item.lineage.proposal_id),
            ),
        )
    )
    for proof in proofs:
        payload = proof.payload
        if (
            payload.source_snapshot_id != first_payload.source_snapshot_id
            or payload.provider_file_id != first_payload.provider_file_id
            or payload.baseline_revision_id != first_payload.baseline_revision_id
            or payload.native_snapshot_sha256 != first_payload.native_snapshot_sha256
            or payload.native_raw_sha256 != first_payload.native_raw_sha256
        ):
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "mapped replacements do not share the same frozen source revision",
            )
    _reject_overlapping_or_duplicate_ranges(replacements)
    if len(proofs) == 1:
        return proofs[0]
    first = replacements[0]
    return SealedMappingProof.seal(
        MappingProofPayload(
            created_at=created_at,
            source_snapshot_id=first_payload.source_snapshot_id,
            provider_file_id=first_payload.provider_file_id,
            baseline_revision_id=first_payload.baseline_revision_id,
            native_snapshot_sha256=first_payload.native_snapshot_sha256,
            native_raw_sha256=first_payload.native_raw_sha256,
            lineage=first.lineage,
            old_text=first.old_text,
            new_text=first.new_text,
            old_text_sha256=first.old_text_sha256,
            new_text_sha256=first.new_text_sha256,
            old_paragraph_sha256=first.old_paragraph_sha256,
            new_paragraph_sha256=first.new_paragraph_sha256,
            location=first.location,
            replacements=replacements,
            eligibility=first.eligibility,
        )
    )


def compile_write_plan(
    *,
    change: SemanticReplacement | None = None,
    mapped: tuple[SemanticReplacement, ...] | None = None,
    baseline: BaselineSnapshot,
    proof: SealedMappingProof,
    sync_run_id: UUID,
    rule_identity: UUID,
    rule_version: int,
    instruction_sha256: Sha256,
    configuration_sha256: Sha256,
    created_at: datetime,
    expires_at: datetime,
) -> SealedWritePlan:
    if mapped is None:
        if change is None:
            raise MappingFailure(
                MappingFailureCode.NOT_APPROVED,
                "write planning requires at least one approved mapped replacement",
            )
        mapped = (change,)
    elif change is not None and change.proposal_id not in {item.proposal_id for item in mapped}:
        raise MappingFailure(
            MappingFailureCode.STALE_LINEAGE,
            "MappingProof does not bind to the requested immutable inputs",
        )
    proof_payload = proof.payload
    if (
        proof_payload.source_snapshot_id != baseline.snapshot_id
        or proof_payload.baseline_revision_id != baseline.baseline_revision_id
        or proof_payload.native_snapshot_sha256 != baseline.native_canonical_sha256
        or proof_payload.native_raw_sha256 != baseline.native_raw_sha256
        or proof_payload.provider_file_id != baseline.provider_file_id
    ):
        raise MappingFailure(
            MappingFailureCode.STALE_LINEAGE,
            "MappingProof does not bind to the requested immutable inputs",
        )
    changes_by_id = {item.proposal_id: item for item in mapped}
    if len(changes_by_id) != len(mapped):
        raise MappingFailure(
            MappingFailureCode.DUPLICATE_TARGET_MAPPING,
            "approved proposals are not uniquely identified",
        )
    if len(proof_payload.replacements) != len(mapped):
        raise MappingFailure(
            MappingFailureCode.STALE_LINEAGE,
            "MappingProof does not bind to the requested immutable inputs",
        )
    document_order: list[tuple[SemanticReplacement, MappedReplacement]] = []
    for replacement in proof_payload.replacements:
        matched = changes_by_id.get(replacement.lineage.proposal_id)
        if (
            matched is None
            or replacement.lineage.decision_id != matched.decision_id
            or replacement.old_text_sha256 != _sha256_text(matched.old_text)
            or replacement.new_text_sha256 != _sha256_text(matched.new_text)
            or replacement.old_paragraph_sha256 != _sha256_text(matched.old_paragraph)
            or replacement.new_paragraph_sha256 != _sha256_text(matched.new_paragraph)
        ):
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "MappingProof does not bind to the requested immutable inputs",
            )
        document_order.append((matched, replacement))
    _reject_overlapping_or_duplicate_ranges(tuple(item for _, item in document_order))
    google_order = tuple(
        sorted(
            document_order,
            key=lambda item: (
                -item[1].location.edit_start_index,
                -item[1].location.edit_end_index,
                str(item[1].lineage.proposal_id),
            ),
        )
    )
    requests: list[dict[str, JsonValue]] = []
    for matched, replacement in google_order:
        location = replacement.location
        requests.extend(
            _delete_insert_pair(
                tab_id=location.tab_id,
                segment_id=location.segment_id,
                start=location.edit_start_index,
                end=location.edit_end_index,
                new_text=matched.new_text,
            )
        )
    expected = deepcopy(baseline.canonical_payload)
    tabs = expected["tabs"]
    assert isinstance(tabs, list)
    tab = tabs[0]
    assert isinstance(tab, dict)
    body = tab["body"]
    assert isinstance(body, list)
    for matched, replacement in google_order:
        _apply_one_splice(
            body,
            structural_element_index=replacement.location.structural_element_index,
            edit_start=replacement.location.edit_start_index,
            edit_end=replacement.location.edit_end_index,
            new_text=matched.new_text,
        )
    expected_sha256 = sha256_json(expected)
    first_change, first_mapped = document_order[0]
    first_location = first_mapped.location
    expected_paragraph = body[first_location.structural_element_index]
    assert isinstance(expected_paragraph, dict)
    expected_runs = expected_paragraph["runs"]
    assert isinstance(expected_runs, list)
    expected_run = expected_runs[0]
    assert isinstance(expected_run, dict)
    expected_paragraph_text = expected_run["text"]
    assert isinstance(expected_paragraph_text, str) and expected_paragraph_text.endswith("\n")
    planned = tuple(
        PlannedReplacementContract(
            proposal_id=matched.proposal_id,
            decision_id=matched.decision_id,
            old_text=matched.old_text,
            new_text=matched.new_text,
            old_paragraph_sha256=_sha256_text(matched.old_paragraph),
            new_paragraph_sha256=_sha256_text(matched.new_paragraph),
            tab_id=replacement.location.tab_id,
            segment_id=replacement.location.segment_id,
            structural_element_index=replacement.location.structural_element_index,
            baseline_edit_start_index=replacement.location.edit_start_index,
            baseline_edit_end_index=replacement.location.edit_end_index,
            google_delete_start_index=replacement.location.edit_start_index,
            google_delete_end_index=replacement.location.edit_end_index,
            google_insert_index=replacement.location.edit_start_index,
        )
        for matched, replacement in document_order
    )
    payload = WritePlanPayload(
        created_at=created_at,
        expires_at=expires_at,
        sync_run_id=sync_run_id,
        source=SourceSnapshotContract(
            snapshot_id=baseline.snapshot_id,
            provider=Provider.GOOGLE,
            provider_principal_subject=baseline.provider_principal_subject,
            provider_file_id=baseline.provider_file_id,
            parent_ids=baseline.parent_ids,
            baseline_revision_id=baseline.baseline_revision_id,
            native_raw_sha256=baseline.native_raw_sha256,
            native_canonical_sha256=baseline.native_canonical_sha256,
            exported_docx_sha256=baseline.exported_docx_sha256,
        ),
        rule=RuleContract(
            rule_id=rule_identity,
            version=rule_version,
            instruction_sha256=instruction_sha256,
            configuration_sha256=configuration_sha256,
        ),
        mapping=MappingProofContract(
            mapping_proof_id=proof.mapping_proof_id,
            schema_version=proof_payload.schema_version,
            mapper_version=proof_payload.mapper_version,
            integrity_sha256=proof.integrity_sha256,
        ),
        compiler_version=COMPILER_VERSION,
        approval_lineage=tuple(
            ApprovalLineageContract(
                proposal_id=matched.proposal_id,
                decision_id=matched.decision_id,
                review_round=matched.review_round,
                session_id=matched.session_id,
                session_document_id=matched.session_document_id,
                durable_document_id=matched.durable_document_id,
                job_id=matched.job_id,
                superdocs_export_id=matched.superdocs_export_id,
                approved_export_sha256=matched.approved_export_sha256,
                final_version_id=matched.final_version_id,
                superdocs_change_id=matched.superdocs_change_id,
                chunk_id=matched.chunk_id,
                approved=True,
                old_html_sha256=matched.old_html_sha256,
                new_html_sha256=matched.new_html_sha256,
            )
            for matched, _replacement in document_order
        ),
        expected_replacement=ExpectedReplacementContract(
            old_text=first_change.old_text,
            new_text=first_change.new_text,
            old_paragraph_sha256=_sha256_text(first_change.old_paragraph),
            new_paragraph_sha256=_sha256_text(first_change.new_paragraph),
        ),
        planned_replacements=planned,
        provider_operations=(
            GoogleDocsBatchUpdate(
                required_revision_id=baseline.baseline_revision_id,
                requests=tuple(requests),
            ),
        ),
        expected_postimage=ExpectedPostimageContract(
            schema_version="docrelay.google-canonical.v1",
            verifier_version=VERIFIER_VERSION,
            canonical_sha256=expected_sha256,
            canonical_payload={
                "tab_id": first_location.tab_id,
                "segment_id": first_location.segment_id,
                "structural_element_index": first_location.structural_element_index,
                "paragraph_start_index": expected_paragraph["startIndex"],
                "paragraph_end_index": expected_paragraph["endIndex"],
                "paragraph_sha256": _sha256_text(expected_paragraph_text[:-1]),
                "replacements": [
                    {
                        "proposal_id": str(matched.proposal_id),
                        "structural_element_index": replacement.location.structural_element_index,
                        "baseline_edit_start_index": replacement.location.edit_start_index,
                        "baseline_edit_end_index": replacement.location.edit_end_index,
                        "new_text": matched.new_text,
                    }
                    for matched, replacement in document_order
                ],
            },
        ),
    )
    return SealedWritePlan.seal(payload)


def write_plan_identity(plan: SealedWritePlan) -> UUID:
    return _identity("write-plan", plan.integrity_sha256)


def _reject_overlapping_or_duplicate_ranges(
    replacements: tuple[MappedReplacement, ...],
) -> None:
    seen: list[MappedReplacement] = []
    for item in replacements:
        for other in seen:
            if item.location.tab_id != other.location.tab_id:
                continue
            if (
                item.location.edit_start_index == other.location.edit_start_index
                and item.location.edit_end_index == other.location.edit_end_index
            ):
                raise MappingFailure(
                    MappingFailureCode.DUPLICATE_TARGET_MAPPING,
                    "two approved proposals mapped to the same frozen baseline span",
                    candidate_count=2,
                )
            if (
                item.location.edit_start_index < other.location.edit_end_index
                and other.location.edit_start_index < item.location.edit_end_index
            ):
                raise MappingFailure(
                    MappingFailureCode.OVERLAPPING_MAPPED_RANGES,
                    "approved mapped ranges overlap on the frozen baseline",
                    candidate_count=2,
                )
        seen.append(item)


def _delete_insert_pair(
    *,
    tab_id: str,
    segment_id: str,
    start: int,
    end: int,
    new_text: str,
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    return (
        {
            "deleteContentRange": {
                "range": {
                    "segmentId": segment_id,
                    "tabId": tab_id,
                    "startIndex": start,
                    "endIndex": end,
                }
            }
        },
        {
            "insertText": {
                "location": {
                    "segmentId": segment_id,
                    "tabId": tab_id,
                    "index": start,
                },
                "text": new_text,
            }
        },
    )


def _apply_one_splice(
    body: list[Any],
    *,
    structural_element_index: int,
    edit_start: int,
    edit_end: int,
    new_text: str,
) -> None:
    paragraph = body[structural_element_index]
    if not isinstance(paragraph, dict):
        _malformed("mapped paragraph is malformed")
    runs = paragraph.get("runs")
    if not isinstance(runs, list) or not runs:
        _malformed("mapped paragraph has no text run")
    run = runs[0]
    if not isinstance(run, dict):
        _malformed("mapped paragraph run is malformed")
    run_start = _integer_index(run, "startIndex")
    text = run.get("text")
    if not isinstance(text, str):
        _malformed("mapped text run content is malformed")
    encoded = text.encode("utf-16-le")
    offset_start = (edit_start - run_start) * 2
    offset_end = (edit_end - run_start) * 2
    if not 0 <= offset_start < offset_end <= len(encoded):
        _malformed("replacement range does not map to one baseline text run")
    run["text"] = (
        encoded[:offset_start] + new_text.encode("utf-16-le") + encoded[offset_end:]
    ).decode("utf-16-le")
    _shift_body_indexes(
        body,
        replaced_start=edit_start,
        replaced_end=edit_end,
        delta=_utf16_length(new_text) - (edit_end - edit_start),
    )


def _parse_supported_block(html: str) -> tuple[ReviewBlockSignature, str]:
    parser = _SupportedBlockParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise MappingFailure(
            MappingFailureCode.MALFORMED_REVIEW_HTML,
            "proposal HTML is malformed",
        ) from exc
    if parser.invalid or parser.stack or not parser.block_closed or parser.block_count != 1:
        code = (
            MappingFailureCode.FORMATTING_DELTA
            if "<" in html
            and any(
                html.lstrip().lower().startswith(f"<{tag}") for tag in _SUPPORTED_REVIEW_BLOCK_TAGS
            )
            else MappingFailureCode.MALFORMED_REVIEW_HTML
        )
        raise MappingFailure(
            code,
            "DocRelay can safely write text changes to a single supported paragraph or "
            "heading. This proposal changes unsupported document structure.",
        )
    return tuple(parser.signature), "".join(parser.parts)


def _one_root_tab(
    payload: dict[str, JsonValue],
) -> tuple[dict[str, Any], list[Any], str]:
    tabs = payload.get("tabs")
    if not isinstance(tabs, list):
        _malformed("native snapshot tabs are malformed")
    if len(tabs) != 1:
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_STRUCTURAL_LOCATION,
            "exactly one root tab is required",
        )
    if not isinstance(tabs[0], dict):
        _malformed("native snapshot root tab is malformed")
    tab = tabs[0]
    if tab.get("childTabs") not in (None, []):
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_STRUCTURAL_LOCATION,
            "child tabs are outside the proven subset",
        )
    properties = tab.get("tabProperties")
    body = tab.get("body")
    if not isinstance(properties, dict) or not isinstance(body, list):
        _malformed("native tab is missing properties or body")
    if properties.get("parentTabId") is not None or properties.get("nestingLevel") not in (0, None):
        raise MappingFailure(
            MappingFailureCode.UNSUPPORTED_STRUCTURAL_LOCATION,
            "mapped tab is not a root tab",
        )
    tab_id = properties.get("tabId")
    if not isinstance(tab_id, str) or not tab_id:
        _malformed("native root tab has no tabId")
    return tab, body, tab_id


def _paragraph_text(paragraph: dict[str, Any]) -> str | None:
    runs = paragraph.get("runs")
    if not isinstance(runs, list):
        _malformed("paragraph runs are malformed")
    parts: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            _malformed("paragraph run is malformed")
        if run.get("kind") != "text":
            return None
        text = run.get("text")
        if not isinstance(text, str):
            _malformed("text run content is malformed")
        parts.append(text)
    full = "".join(parts)
    if not full.endswith("\n") or full.endswith("\n\n"):
        _malformed("paragraph lacks one provider newline")
    return full[:-1]


def _find_unsupported_location(tab: dict[str, Any], old_paragraph: str) -> str | None:
    body = tab.get("body")
    assert isinstance(body, list)
    for element in body:
        if isinstance(element, dict) and element.get("type") == "table":
            if _contains_paragraph(element, old_paragraph):
                return "table"
    for segment_name in ("headers", "footers", "footnotes"):
        segments = tab.get(segment_name)
        if not isinstance(segments, dict):
            _malformed(f"{segment_name} map is malformed")
        for segment in segments.values():
            if _contains_paragraph(segment, old_paragraph):
                return segment_name
    return None


def _contains_paragraph(value: Any, old_paragraph: str) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "paragraph" and _paragraph_text(value) == old_paragraph:
            return True
        return any(_contains_paragraph(child, old_paragraph) for child in value.values())
    if isinstance(value, list):
        return any(_contains_paragraph(child, old_paragraph) for child in value)
    return False


def _integer_index(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        _malformed(f"provider {key} is malformed")
    return result


def _malformed(message: str) -> NoReturn:
    raise MappingFailure(MappingFailureCode.MALFORMED_SNAPSHOT, message)


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _shift_body_indexes(
    body: list[Any],
    *,
    replaced_start: int,
    replaced_end: int,
    delta: int,
) -> None:
    for offset, element in enumerate(body):
        _shift_provider_indexes(
            element,
            replaced_start=replaced_start,
            replaced_end=replaced_end,
            delta=delta,
            allow_implicit_zero_section_break=offset == 0,
        )


def _shift_provider_indexes(
    value: Any,
    *,
    replaced_start: int,
    replaced_end: int,
    delta: int,
    allow_implicit_zero_section_break: bool = False,
) -> None:
    if isinstance(value, list):
        for child in value:
            _shift_provider_indexes(
                child,
                replaced_start=replaced_start,
                replaced_end=replaced_end,
                delta=delta,
            )
        return
    if not isinstance(value, dict):
        return
    implicit_zero_start = (
        allow_implicit_zero_section_break
        and value.get("type") == "sectionBreak"
        and "startIndex" in value
        and value.get("startIndex") is None
        and value.get("endIndex") == 1
    )
    if "startIndex" in value or "endIndex" in value:
        start = value.get("startIndex")
        end = value.get("endIndex")
        if implicit_zero_start:
            start = 0
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or start < 0
            or not isinstance(end, int)
            or isinstance(end, bool)
            or end < 0
            or end < start
        ):
            _malformed("provider structural range is malformed")
    for key, child in value.items():
        if key in {"startIndex", "endIndex"}:
            if key == "startIndex" and implicit_zero_start:
                # Google omits the zero-valued startIndex on the mandatory leading
                # body section break. Keep the omission in the canonical postimage;
                # it is not a writable range and no index is fabricated from it.
                continue
            if not isinstance(child, int) or isinstance(child, bool) or child < 0:
                _malformed(f"provider {key} is malformed")
            if replaced_start < child < replaced_end:
                _malformed("provider index boundary intersects the replacement range")
            if child >= replaced_end:
                value[key] = child + delta
            continue
        _shift_provider_indexes(
            child,
            replaced_start=replaced_start,
            replaced_end=replaced_end,
            delta=delta,
        )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_model(value: BaseModel) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity(kind: str, integrity: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"docrelay:{kind}:{integrity}")
