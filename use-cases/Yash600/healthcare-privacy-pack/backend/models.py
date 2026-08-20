"""
schema_v2.py -- Proposed database schema for the Healthcare Compliance
Workspace rebuild (Workspace -> Policy/Procedure groups -> upload -> Analyze
References -> validated graph -> maintenance loop -> versioned history ->
report -> export).

This supersedes the current models.py entirely. There is no hardcoded
demo pack anywhere in this design; every Document originates from a real
human upload, and every Workspace, Policy, and Procedure is created by the
user at runtime.

Design principle driving every table below: THE DATABASE IS THE SOURCE OF
TRUTH FOR EVERYTHING WE WOULD EVER WANT TO LOOK AT AGAIN. SuperDocs remains
the engine that does parsing and editing, but nothing SuperDocs hands back
to us is ever discarded after a single use -- original uploaded files,
full document HTML on every version, full section/chunk content (not just
hashes), full LLM reasoning/evidence, and every proposed change's old/new
HTML are all persisted as real rows, not fetched-on-demand or thrown away
after being shown once in a diff view.

--------------------------------------------------------------------------
ENTITY MAP (read top to bottom -- this is the dependency order tables are
defined in below)
--------------------------------------------------------------------------

Workspace
  |
  +-- Document (POLICY or PROCEDURE; PROCEDURE has parent_policy_id)
        |
        +-- DocumentVersion (1 = original upload w/ raw file bytes,
        |     N = every subsequent approved edit; ACTIVE/ARCHIVED/PROPOSED)
        |
        +-- Section (STABLE identity across versions -- "Policy S4" is the
              |        same Section row even after 3 edits change its chunk.
              |        Self-referential parent_section_id supports nested
              |        numbering, e.g. S4 -> S4.1 -> S4.1.1)
              |
              +-- SectionSnapshot (per-version realization of a Section:
              |      this version's chunk_id, full content, and hash)
              |
              +-- SectionRelation (records a resolved split/merge lineage
                    between two Section rows -- SEC_004 SPLIT_INTO SEC_004_A
                    + SEC_004_B -- written when a NEEDS_REANALYSIS section
                    is manually resolved, not inferred automatically)

AnalysisRun (one "Analyze References" click)
  |
  +-- AnalysisJob (one per policy/procedure pair)

ProcedurePolicyReference (the graph edge -- many-to-many at section level,
  pins BOTH sides' SectionSnapshots at confirmation time, carries
  confidence + full evidence text)

UpdateRequest (one "Update" click on a policy)
  |
  +-- ProposedChange (one row per SuperDocs proposed change -- used for
  |     BOTH the policy's own edit and every propagated procedure edit;
  |     distinguished by which Document/Section it targets; carries
  |     base_version_id so a stale-proposal race is detectable)
  |
  +-- (each procedure ProposedChange links back to the
        ProcedurePolicyReference that caused it, for full traceability)

ValidationRun
  |
  +-- ValidationCheckResult (one row per check, per edge/section --
        transient, scoped to one run)

Finding (a PERSISTENT, actionable problem record -- a conflict or broken
  reference the validator noticed -- deduplicated across validation runs
  and open until a human resolves it or a ProposedChange fixes it;
  distinct from ValidationCheckResult, which is just this run's log)

Report (rolls up a validation run + the change events since the last report)

ChangeEvent (flat audit log -- every table above writes one of these on
  every state transition; this is what the Report and the UI timeline
  read from)

ExportRecord (optional -- audit trail of what was actually exported and
  when, not required for correctness)

--------------------------------------------------------------------------
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, LargeBinary, Text
from sqlmodel import Field, Relationship, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ============================================================================
# enums
# ============================================================================


class WorkspaceStatus(str, enum.Enum):
    SETUP = "setup"                # documents still being uploaded/grouped
    ANALYZING = "analyzing"        # an AnalysisRun is in progress
    READY = "ready"                # graph validated, no blocking issues
    NEEDS_ATTENTION = "needs_attention"  # ready, but has NEEDS_REVIEW/conflicts


class DocType(str, enum.Enum):
    POLICY = "policy"
    PROCEDURE = "procedure"


class DocumentVersionStatus(str, enum.Enum):
    ACTIVE = "active"        # the current live version
    PROPOSED = "proposed"    # awaiting approval, not yet committed
    ARCHIVED = "archived"    # superseded by a later approved version
    REJECTED = "rejected"    # a proposed version a human rejected (kept for audit)


class SourceFormat(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    HTML = "html"
    MD = "md"
    RTF = "rtf"
    GENERATED = "generated"  # this version has no source file -- it came from an AI edit


class SectionStatus(str, enum.Enum):
    ACTIVE = "active"
    NEEDS_REANALYSIS = "needs_reanalysis"  # structural edit broke confident chunk mapping
    ARCHIVED = "archived"                  # section removed in a later version


class AnalysisRunStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class AnalysisJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ReferenceRelationship(str, enum.Enum):
    IMPLEMENTS = "implements"
    # room to grow: REFERENCES, CONTRADICTS, SUPERSEDES, etc. -- not used yet


class ReferenceStatus(str, enum.Enum):
    VALID = "valid"                  # confirmed correct, section hashes match
    NEEDS_REVIEW = "needs_review"    # LLM confidence below auto-accept threshold
    STALE = "stale"                  # policy section changed since last sync
    NEEDS_REANALYSIS = "needs_reanalysis"  # structural change broke the mapping
    REJECTED = "rejected"            # human reviewed and said this isn't real


class ReferenceSource(str, enum.Enum):
    LLM_ANALYSIS = "llm_analysis"    # produced by an AnalysisJob
    HUMAN = "human"                  # human manually linked at upload time


class UpdateRequestStatus(str, enum.Enum):
    PROCESSING = "processing"          # SuperDocs call in flight
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"              # policy change approved (procedures may still be pending)
    PARTIALLY_APPROVED = "partially_approved"  # some but not all procedure proposals approved
    REJECTED = "rejected"              # policy change itself was rejected -- nothing propagated


class ProposedChangeStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # SuperDocs failed to produce a proposal for a procedure we identified as
    # affected (e.g. chat_async errored). Recorded as a row in this state
    # rather than silently dropped, so "N procedures identified, M actually
    # proposed" is always reconstructable from ProposedChange rows alone --
    # no separate ImpactAnalysis table needed to reconcile the two counts.
    FAILED = "failed"


class ValidationCheckType(str, enum.Enum):
    HAS_PARENT_POLICY = "has_parent_policy"
    SECTION_EXISTS = "section_exists"
    HASH_MATCH = "hash_match"
    CITATION_MATCH = "citation_match"
    CONTRADICTION = "contradiction"
    MISSING_REFERENCE = "missing_reference"
    LOW_CONFIDENCE_UNREVIEWED = "low_confidence_unreviewed"


class FindingType(str, enum.Enum):
    CONFLICT = "conflict"                    # two sections disagree (e.g. different deadlines)
    BROKEN_REFERENCE = "broken_reference"     # reference points at a section that no longer resolves
    OUTDATED_REFERENCE = "outdated_reference"  # same as STALE on the edge, surfaced as an open problem
    MISSING_REFERENCE = "missing_reference"   # a procedure has no reference to any policy section
    INCONSISTENCY = "inconsistency"           # catch-all for validator-detected mismatches


class FindingStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"  # human reviewed and decided it isn't actually a problem


class SectionRelationType(str, enum.Enum):
    SPLIT_INTO = "split_into"
    MERGED_INTO = "merged_into"


class ChangeEventType(str, enum.Enum):
    WORKSPACE_CREATED = "workspace_created"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_DRAFTED = "document_drafted"  # created via AI + a SuperDocs template, not an uploaded file
    DOCUMENT_DELETED = "document_deleted"
    ANALYSIS_RUN_STARTED = "analysis_run_started"
    ANALYSIS_RUN_COMPLETED = "analysis_run_completed"
    REFERENCE_CREATED = "reference_created"
    REFERENCE_REVIEWED = "reference_reviewed"
    VALIDATION_RUN = "validation_run"
    POLICY_EDIT_REQUESTED = "policy_edit_requested"
    POLICY_EDIT_APPROVED = "policy_edit_approved"
    POLICY_EDIT_REJECTED = "policy_edit_rejected"
    EDGE_FLAGGED_STALE = "edge_flagged_stale"
    PROCEDURE_CHANGE_PROPOSED = "procedure_change_proposed"
    PROCEDURE_CHANGE_APPROVED = "procedure_change_approved"
    PROCEDURE_CHANGE_REJECTED = "procedure_change_rejected"
    REPORT_GENERATED = "report_generated"
    EXPORTED = "exported"


# ============================================================================
# workspace
# ============================================================================


class Workspace(SQLModel, table=True):
    """Top-level tenant. Everything else is scoped under one of these."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    organization_name: str
    # Optional, free-text ("hospital" | "clinic" | "laboratory" | ...).
    # Deliberately NOT a separate Organization table with its own id/FK --
    # we have no use case yet for one org owning multiple workspaces, so
    # that join would carry zero query benefit today. Promote this to a
    # real table if that use case ever actually shows up.
    organization_type: str | None = None
    pack_name: str
    status: WorkspaceStatus = Field(default=WorkspaceStatus.SETUP)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ============================================================================
# documents / versions
# ============================================================================


class Document(SQLModel, table=True):
    """
    One policy or procedure. Holds NO content itself -- content lives on
    DocumentVersion rows. superdocs_document_id/session_id are stable across
    every edit because SuperDocs edits happen in place on one document; a
    new logical "version" here is our own snapshot, not a new SuperDocs doc.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)

    doc_type: DocType
    # Only set for PROCEDURE documents -- which policy this procedure was
    # grouped under at upload time (STEP 1/2 of the setup flow). This is
    # document-level grouping, established with zero AI involvement, before
    # Analyze References ever runs.
    parent_policy_id: str | None = Field(default=None, foreign_key="document.id", index=True)

    title: str

    superdocs_document_id: str = Field(index=True, unique=True)
    superdocs_session_id: str = Field(index=True)

    # Nullable because it isn't known until the first DocumentVersion is
    # created (chicken-and-egg with the FK below); set immediately after.
    active_version_id: str | None = Field(default=None, foreign_key="documentversion.id")

    # Flexible compliance metadata (domain, authority, jurisdiction,
    # department, tags, ...) as a JSON blob rather than a normalized
    # ComplianceDomain/ComplianceMetadata table pair -- these fields vary
    # by organization and we don't query across them relationally today,
    # so a JSON column gets the same flexibility with zero schema
    # migrations when a new org has different metadata needs.
    metadata_json: str | None = Field(default=None, sa_column=Column(Text))

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DocumentVersion(SQLModel, table=True):
    """
    A full, persisted snapshot of a document at one point in time.

    Version 1 of every document always has raw_file_bytes/filename/mime_type
    populated (the literal file the human uploaded) and source_format set
    from that file's extension. Every later version comes from an approved
    SuperDocs edit: raw_file_* stays null (nothing was re-uploaded),
    source_format is GENERATED, and normalized_html is the full document
    HTML fetched from SuperDocs right after approval -- persisted here
    instead of being re-fetched from SuperDocs every time someone wants to
    look at it.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    version_number: int  # 1, 2, 3... per document

    status: DocumentVersionStatus = Field(default=DocumentVersionStatus.ACTIVE)

    source_format: SourceFormat

    # The literal bytes of the file the human uploaded, when this version
    # came from an upload. BYTEA in Postgres -- fine at compliance-document
    # scale (KB, not GB), no object storage needed.
    raw_file_bytes: bytes | None = Field(default=None, sa_column=Column(LargeBinary))
    raw_file_filename: str | None = None
    raw_file_mime_type: str | None = None

    # The full document HTML as SuperDocs represents it as of this version.
    # This is what STOP re-fetching-from-SuperDocs-every-time fixes.
    normalized_html: str = Field(sa_column=Column(Text))

    superdocs_version_id: str | None = None  # SuperDocs' own version marker, if any

    change_summary: str | None = None  # e.g. the instruction text that produced this version
    created_by: str = "system"         # "human:<email>" or "system"
    created_at: datetime = Field(default_factory=_now)


# ============================================================================
# sections / section snapshots
# ============================================================================


class Section(SQLModel, table=True):
    """
    STABLE logical section identity, e.g. "Policy S4 -- Access Control".
    This row does not change when the document is edited, even if the
    section's heading text, position, or underlying chunk_id changes --
    that's the whole point of splitting Section from SectionSnapshot below.
    A rename/reorg only updates `title`/`section_number` and flips `status`
    to NEEDS_REANALYSIS if the edit was structural enough that we can't
    confidently say "same section, new content" (see STEP 19 discussion).

    Self-referential `parent_section_id` supports nested numbering
    (S4 -> S4.1 -> S4.1.1), which real healthcare policies commonly use.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    parent_section_id: str | None = Field(default=None, foreign_key="section.id", index=True)

    section_number: str   # "4", "4.1", "4.1.1" -- display order, not identity
    title: str             # current heading text
    level: int = 1         # nesting depth: top-level = 1, "4.1" = 2, etc.
    # Optional classification (PURPOSE/SCOPE/REQUIREMENT/PROCEDURE/...).
    # Free text, never enforced -- defaults to unset rather than a forced
    # "OTHER" value when the uploaded document doesn't map cleanly.
    section_type: str | None = None
    status: SectionStatus = Field(default=SectionStatus.ACTIVE)

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SectionRelation(SQLModel, table=True):
    """
    Records a RESOLVED split/merge lineage between two Section rows, e.g.
    SEC_004 SPLIT_INTO {SEC_004_A, SEC_004_B}. This is written when a human
    (or a future, conservative heuristic) resolves a section that was
    flagged NEEDS_REANALYSIS after a structural edit -- it is deliberately
    NOT something the system infers automatically today. Existing only as
    an audit/traceability record of "how did we get from the old section
    graph to the new one" lets a report explain historical references
    correctly even after a section has been split or merged.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    source_section_id: str = Field(foreign_key="section.id", index=True)
    target_section_id: str = Field(foreign_key="section.id", index=True)
    relation_type: SectionRelationType

    notes: str | None = Field(default=None, sa_column=Column(Text))
    created_by: str = "system"
    created_at: datetime = Field(default_factory=_now)


class SectionSnapshot(SQLModel, table=True):
    """
    The concrete realization of a Section within one specific
    DocumentVersion: this version's REPRESENTATIVE SuperDocs chunk_id (the
    heading chunk that anchors the section), and the FULL combined content
    (not just a hash) persisted so evidence/diffs never require a live
    SuperDocs round trip to reconstruct.

    Updated assumption (was: one Section == one SuperDocs chunk -- true
    only for hand-authored HTML with a pre-baked div-per-section wrapper).
    Empirically, a real SuperDocs parse of an uploaded file chunks per
    ELEMENT: one chunk id per paragraph, heading, table, etc, as top-level
    siblings -- so a section's actual content spans MANY chunk ids (its
    own heading chunk plus every body chunk up to the next heading). The
    full member list now lives in SectionSnapshotChunk below; `chunk_id`
    here stays as the single representative id (the heading chunk) used
    for version-to-version re-sync matching.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    section_id: str = Field(foreign_key="section.id", index=True)
    document_version_id: str = Field(foreign_key="documentversion.id", index=True)

    chunk_id: str = Field(index=True)  # representative (heading) SuperDocs data-chunk-id for this version
    content_html: str = Field(sa_column=Column(Text))   # combined body HTML (all member chunks after the heading), persisted
    content_text: str = Field(sa_column=Column(Text))   # normalized heading + body text (search/LLM/hash payload)
    content_hash: str = Field(index=True)               # sha256(content_text) -- fast staleness check
    order_index: int

    created_at: datetime = Field(default_factory=_now)


class SectionSnapshotChunk(SQLModel, table=True):
    """
    One row per SuperDocs chunk id that belongs to a SectionSnapshot --
    the heading chunk plus every body chunk (paragraph, table, list, etc)
    up to the next heading. Exists so a later SuperDocs edit response
    (which reports its own chunk_id, almost always a body chunk rather
    than the section's heading chunk) can still be resolved back to the
    right Section: look up by ANY member chunk_id, not just the one
    representative id stored on SectionSnapshot itself.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    section_snapshot_id: str = Field(foreign_key="sectionsnapshot.id", index=True)
    chunk_id: str = Field(index=True)


# ============================================================================
# analyze references
# ============================================================================


class AnalysisRun(SQLModel, table=True):
    """One 'Analyze References' click."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    status: AnalysisRunStatus = Field(default=AnalysisRunStatus.PROCESSING)
    triggered_by: str = "system"
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None


class AnalysisJob(SQLModel, table=True):
    """
    One (policy, procedure) pair within a run -- the unit of work run under
    the concurrency-limited worker pool. Token counts persisted for cost
    auditing since this is the one LLM-calling phase in the whole system.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(foreign_key="analysisrun.id", index=True)
    policy_document_id: str = Field(foreign_key="document.id")
    procedure_document_id: str = Field(foreign_key="document.id")

    status: AnalysisJobStatus = Field(default=AnalysisJobStatus.PENDING)
    error_message: str | None = None

    llm_model: str | None = None
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None


# ============================================================================
# the reference graph -- the single most important table in the system
# ============================================================================


class ProcedurePolicyReference(SQLModel, table=True):
    """
    procedure_section_id IMPLEMENTS policy_section_id. Many-to-many at the
    section level by design: one procedure section can implement several
    policy sections, one policy section can be implemented by several
    procedure sections (across the same or different procedures).

    `evidence` holds the LLM's full reasoning text, not a truncated summary
    -- this is what makes reference discovery debuggable, reviewable, and
    reportable later, per the "proof over assertion" principle carried over
    from the current build's validator.

    `policy_section_snapshot_id` and `procedure_section_snapshot_id` pin the
    EXACT SectionSnapshot on both sides that this edge was last confirmed
    valid against -- not just the policy side. Staleness on the policy side
    = the policy Section's current active SectionSnapshot has a different
    content_hash than the pinned one; the procedure-side pin catches the
    less obvious case where someone edits the PROCEDURE directly (outside
    the propagation flow) and the reference silently drifts without the
    policy ever having changed. No LLM judgment call at staleness-check
    time -- only at initial-discovery time.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)

    procedure_section_id: str = Field(foreign_key="section.id", index=True)
    policy_section_id: str = Field(foreign_key="section.id", index=True)

    relationship_type: ReferenceRelationship = Field(default=ReferenceRelationship.IMPLEMENTS)
    confidence: float | None = None  # null when source == HUMAN (no model confidence to report)
    evidence: str | None = Field(default=None, sa_column=Column(Text))

    status: ReferenceStatus = Field(default=ReferenceStatus.VALID)
    source: ReferenceSource = Field(default=ReferenceSource.LLM_ANALYSIS)

    analysis_job_id: str | None = Field(default=None, foreign_key="analysisjob.id")
    policy_section_snapshot_id: str = Field(foreign_key="sectionsnapshot.id")
    procedure_section_snapshot_id: str = Field(foreign_key="sectionsnapshot.id")

    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ============================================================================
# maintenance / update flow
# ============================================================================


class UpdateRequest(SQLModel, table=True):
    """One 'Update' click on a policy -- the parent record for everything
    that flows from a single user instruction: the policy's own proposed
    edit, plus every procedure proposal it fans out to."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    document_id: str = Field(foreign_key="document.id")  # the policy being edited
    instruction_text: str = Field(sa_column=Column(Text))

    status: UpdateRequestStatus = Field(default=UpdateRequestStatus.PROCESSING)
    requested_by: str = "system"
    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None


class ProposedChange(SQLModel, table=True):
    """
    One SuperDocs proposed change -- used for BOTH the policy's own edit and
    every procedure edit it propagates to. old_html/new_html are the
    chunk-level diff (for the Review screen) and are persisted permanently,
    not discarded after being shown once. On approval, a new DocumentVersion
    (full-document snapshot) is created separately -- this row stays as the
    permanent record of what that specific change was and why.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    update_request_id: str | None = Field(default=None, foreign_key="updaterequest.id", index=True)

    document_id: str = Field(foreign_key="document.id")
    section_id: str | None = Field(default=None, foreign_key="section.id")  # null = whole-document edit

    # Which DocumentVersion this proposal was generated against. If the
    # document's active_version_id has moved on by the time a human reviews
    # this proposal (someone else approved a different change first), that
    # mismatch is detectable directly -- base_version_id != current active
    # version means "this proposal is stale, re-evaluate before approving"
    # rather than silently approving a change computed against old content.
    base_version_id: str = Field(foreign_key="documentversion.id")

    # Set only for propagated procedure changes -- which graph edge caused
    # this proposal to be generated. Null for the policy's own top-level edit.
    reference_id: str | None = Field(default=None, foreign_key="procedurepolicyreference.id")

    superdocs_job_id: str | None = None
    superdocs_change_id: str | None = None

    # Nullable: chat_async returns only a job_id at submission time. These
    # get filled in once the job reaches awaiting_approval and we fetch its
    # pending_changes -- there's a real gap between "this row exists" and
    # "we know what the diff actually is" for async jobs, unlike the old
    # synchronous-chat flow where the diff was known immediately.
    old_html: str | None = Field(default=None, sa_column=Column(Text))
    new_html: str | None = Field(default=None, sa_column=Column(Text))
    ai_explanation: str | None = Field(default=None, sa_column=Column(Text))

    status: ProposedChangeStatus = Field(default=ProposedChangeStatus.PENDING)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    feedback: str | None = Field(default=None, sa_column=Column(Text))

    # Set once approved -- the DocumentVersion this change produced.
    resulting_version_id: str | None = Field(default=None, foreign_key="documentversion.id")

    created_at: datetime = Field(default_factory=_now)


# ============================================================================
# validation
# ============================================================================


class ValidationRun(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    triggered_at: datetime = Field(default_factory=_now)
    overall_status: str = "pending"  # "pass" | "fail"
    total_checks: int = 0
    passed: int = 0
    failed: int = 0


class ValidationCheckResult(SQLModel, table=True):
    """One row per individual check performed during a ValidationRun --
    the granular evidence behind the pass/fail summary, matching the five
    check types from the setup-validation design plus the two staleness
    checks the maintenance loop already relies on."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    validation_run_id: str = Field(foreign_key="validationrun.id", index=True)

    check_type: ValidationCheckType
    reference_id: str | None = Field(default=None, foreign_key="procedurepolicyreference.id")
    section_id: str | None = Field(default=None, foreign_key="section.id")

    passed: bool
    details: str | None = Field(default=None, sa_column=Column(Text))


# ============================================================================
# findings -- persistent, actionable problems (distinct from the transient
# per-run ValidationCheckResult log above)
# ============================================================================


class Finding(SQLModel, table=True):
    """
    A PERSISTENT record of an open problem the validator noticed -- a
    conflict, a broken reference, a procedure with no reference at all.
    Deliberately separate from ValidationCheckResult: a check result is
    scoped to one ValidationRun and says "this failed, this time"; a
    Finding is deduplicated across runs (re-running validation doesn't
    create a second OPEN finding for the same problem) and stays OPEN
    until a human dismisses it or a ProposedChange resolves it. This is
    what turns "the validator failed" into an actual worklist rather than
    a report that has to be re-read after every run.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)

    finding_type: FindingType
    source_section_id: str = Field(foreign_key="section.id")
    target_section_id: str | None = Field(default=None, foreign_key="section.id")  # null for MISSING_REFERENCE
    reference_id: str | None = Field(default=None, foreign_key="procedurepolicyreference.id")

    description: str = Field(sa_column=Column(Text))
    evidence: str | None = Field(default=None, sa_column=Column(Text))

    status: FindingStatus = Field(default=FindingStatus.OPEN)
    resolved_by_change_id: str | None = Field(default=None, foreign_key="proposedchange.id")

    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None


# ============================================================================
# report + audit log
# ============================================================================


class Report(SQLModel, table=True):
    """The 'living report' -- generated after every approved UpdateRequest
    and available on demand, rolling up what changed, what was affected,
    what was approved/rejected, and the validation status as of that point."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    update_request_id: str | None = Field(default=None, foreign_key="updaterequest.id")
    validation_run_id: str | None = Field(default=None, foreign_key="validationrun.id")

    generated_at: datetime = Field(default_factory=_now)
    pack_version_label: str  # e.g. "v1.1"
    summary: str = Field(sa_column=Column(Text))  # rendered/structured summary text (JSON-in-text is fine)


class ChangeEvent(SQLModel, table=True):
    """Append-only audit log. Every table above writes one of these on
    every state transition -- this is what the Report and UI timeline
    read from, and it's the cheapest place to answer 'what happened and
    when' without re-deriving it from every other table."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    event_type: ChangeEventType
    timestamp: datetime = Field(default_factory=_now)

    document_id: str | None = Field(default=None, foreign_key="document.id")
    document_version_id: str | None = Field(default=None, foreign_key="documentversion.id")
    section_id: str | None = Field(default=None, foreign_key="section.id")
    reference_id: str | None = Field(default=None, foreign_key="procedurepolicyreference.id")
    update_request_id: str | None = Field(default=None, foreign_key="updaterequest.id")
    proposed_change_id: str | None = Field(default=None, foreign_key="proposedchange.id")

    actor: str = "system"
    description: str = Field(sa_column=Column(Text))
    approved: bool | None = None


# ============================================================================
# export (optional -- audit trail of generated exports, not required for
# correctness; everything it would export is already fully reconstructible
# from Document + DocumentVersion + Report above)
# ============================================================================


class ExportRecord(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.id", index=True)
    report_id: str | None = Field(default=None, foreign_key="report.id")

    format: str  # "docx" | "pdf" | "zip" | ...
    file_bytes: bytes | None = Field(default=None, sa_column=Column(LargeBinary))

    exported_by: str = "system"
    exported_at: datetime = Field(default_factory=_now)
