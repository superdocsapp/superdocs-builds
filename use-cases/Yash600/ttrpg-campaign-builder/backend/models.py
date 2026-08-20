"""
models.py -- SQLModel data model for the TTRPG campaign workspace, v2.

v1 (see git history) auto-uploaded one hardcoded campaign ("The Shattered
Crown") at seed time and tracked coherence via a generic Entity/Reference
hash-comparison graph. This version removes ALL auto-ingestion: a Campaign
starts empty, and every Document/Character/NPC/Location is created or
imported by the user through the API -- see main.py's docstring for the
create/import flow. The data model below is the user-specified schema
(Campaign, Document, DocumentVersion, DocumentLink, Character, NPC,
Location, Illustration, ChatSession, ChatMessage, Export, ChangeEvent),
with one addition kept from v1 by explicit decision: DocumentLink still
carries staleness tracking (synced_version_number + status), because
without it this build has no functional difference from a plain
multi-document editor -- "documents provably stay in sync" is the whole
point of building on SuperDocs rather than a generic CMS.

Document is deliberately generic (one table, a `doc_type` enum) rather than
a separate table per document kind -- CampaignBible/CharacterSheet/
SessionLog/NPC/Location all share the same versioning, linking, chat, and
export machinery, so splitting them into parallel tables would just mean
reimplementing that machinery N times. Character/NPC/Location are thin
"entity" rows that point at their own backing Document (1:1) and add the
structured fields (race/class/level for a Character, role for an NPC, etc)
that don't belong in freeform document prose.

DocumentVersion never overwrites: each edit (manual or chat-generated)
creates a new row. Status lifecycle:

  DRAFT      -- created but not yet the document's active content (unused
                today, reserved for a future "save without proposing" path)
  PROPOSED   -- a chat-generated edit awaiting human approval (mirrors a
                SuperDocs chat_async job in "awaiting_approval")
  ACTIVE     -- exactly one per document; what Document.active_version_id
                points at
  ARCHIVED   -- a former ACTIVE version, kept for history once superseded

DocumentLink staleness: synced_version_number stores the TARGET document's
active_version.version_number as of the last confirmed sync. Whenever a
document's active version changes, every DocumentLink whose target is that
document gets marked STALE if synced_version_number no longer matches --
a plain integer comparison, no prose-diffing, no LLM judgment call. This is
the same primitive as v1's content-hash comparison (chunking.is_stale),
just keyed to version numbers instead of hashes since links are now
document-to-document rather than chunk-to-chunk.
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class DocumentType(str, enum.Enum):
    CAMPAIGN_BIBLE = "campaign_bible"
    CHARACTER = "character"
    SESSION_LOG = "session_log"
    NPC = "npc"
    LOCATION = "location"
    OTHER = "other"


class DocumentVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACTIVE = "active"
    ARCHIVED = "archived"


class DocumentOrigin(str, enum.Enum):
    CREATED = "created"    # blank document started in-app
    IMPORTED = "imported"  # uploaded file, user picked the type
    GENERATED = "generated"  # created via chat (e.g. "create a new NPC")


class LinkRelationshipType(str, enum.Enum):
    BELONGS_TO_CAMPAIGN = "belongs_to_campaign"
    REFERENCES = "references"
    RELATED_TO = "related_to"
    DESCRIBES = "describes"
    APPEARS_IN = "appears_in"


class LinkStatus(str, enum.Enum):
    SYNCED = "synced"
    STALE = "stale"
    PENDING_REVIEW = "pending_review"


class IllustrationEntityType(str, enum.Enum):
    CHARACTER = "character"
    NPC = "npc"
    LOCATION = "location"


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ExportFormat(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    ZIP = "zip"
    HTML = "html"
    MARKDOWN = "markdown"
    TXT = "txt"


class ExportStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class ChangeEventType(str, enum.Enum):
    CAMPAIGN_CREATED = "campaign_created"
    DOCUMENT_CREATED = "document_created"
    DOCUMENT_IMPORTED = "document_imported"
    DOCUMENT_EDIT_PROPOSED = "document_edit_proposed"
    DOCUMENT_EDIT_APPROVED = "document_edit_approved"
    DOCUMENT_EDIT_REJECTED = "document_edit_rejected"
    LINK_CREATED = "link_created"
    LINK_FLAGGED_STALE = "link_flagged_stale"
    LINK_RESYNCED = "link_resynced"
    IMAGE_GENERATED = "image_generated"
    IMAGE_UPLOADED = "image_uploaded"
    EXPORT_CREATED = "export_created"
    DOCUMENT_SAVED = "document_saved"
    DOCUMENT_RENAMED = "document_renamed"
    DOCUMENT_DELETED = "document_deleted"
    CAMPAIGN_UPDATED = "campaign_updated"
    ASSISTANT_DRAFT_GENERATED = "assistant_draft_generated"


class Campaign(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    description: str = ""
    genre: str = ""
    setting: str = ""
    cover_image: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    documents: List["Document"] = Relationship(back_populates="campaign")


class Document(SQLModel, table=True):
    """One row per SuperDocs document: the campaign bible, a character
    sheet, a session log entry, an NPC writeup, or a location writeup."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    doc_type: DocumentType
    title: str
    description: str = ""
    origin: DocumentOrigin = DocumentOrigin.CREATED

    superdocs_document_id: str = Field(index=True, unique=True)
    superdocs_session_id: str = Field(index=True)

    # Points at the currently-active DocumentVersion. Nullable only for the
    # brief window between creating the Document row and creating its first
    # version -- every read path treats a null active_version_id as "still
    # being created" and main.py never returns a Document to the client
    # without one already set.
    active_version_id: str | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    campaign: Campaign = Relationship(back_populates="documents")


class DocumentVersion(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="document.id", index=True)
    version_number: int
    content_html: str
    content_text: str = ""
    status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE

    superdocs_version_id: str | None = None
    change_summary: str = ""
    created_by: str = "human"  # "human" | "ai"

    # Set on a PROPOSED version while it's awaiting approval via SuperDocs'
    # chat_async job/approve flow; cleared once approved/rejected.
    pending_job_id: str | None = None
    pending_change_id: str | None = None

    created_at: datetime = Field(default_factory=_now)


class DocumentLink(SQLModel, table=True):
    """The edge: source_document REFERENCES/DESCRIBES/etc target_document.
    Carries staleness tracking against the target's active version (see
    module docstring) -- editing the target and getting its active version
    bumped is what flips every inbound link to STALE."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    source_document_id: str = Field(foreign_key="document.id", index=True)
    target_document_id: str = Field(foreign_key="document.id", index=True)
    relationship_type: LinkRelationshipType = LinkRelationshipType.RELATED_TO
    note: str = ""  # freeform label, e.g. "mentions Blackspire Keep"

    synced_version_number: int
    status: LinkStatus = LinkStatus.SYNCED

    created_at: datetime = Field(default_factory=_now)
    last_checked_at: datetime = Field(default_factory=_now)


class Character(SQLModel, table=True):
    """A player character. 1:1 with its own sheet Document."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    document_id: str = Field(foreign_key="document.id", index=True, unique=True)
    name: str
    race: str = ""
    char_class: str = ""
    level: int | None = None
    image_url: str | None = None
    created_at: datetime = Field(default_factory=_now)


class NPC(SQLModel, table=True):
    """A non-player character. 1:1 with its own writeup Document."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    document_id: str = Field(foreign_key="document.id", index=True, unique=True)
    name: str
    role: str = ""
    related_location_id: str | None = Field(default=None, foreign_key="location.id")
    image_url: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Location(SQLModel, table=True):
    """A place in the world. 1:1 with its own writeup Document."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    document_id: str = Field(foreign_key="document.id", index=True, unique=True)
    name: str
    image_url: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Illustration(SQLModel, table=True):
    """One illustration generated (Pollinations, keyless) and embedded via
    SuperDocs' image upload + a chat edit, for a Character, NPC, or Location."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    entity_type: IllustrationEntityType
    entity_id: str = Field(index=True)  # Character.id | NPC.id | Location.id
    prompt: str
    provider: str = "pollinations"
    model: str = "flux"
    superdocs_image_url: str
    # Locally re-hosted copy of the same bytes, served from this backend's
    # own /static/illustrations mount. SuperDocs' upload-base64 endpoint is
    # documented to return a "stable public URL", but in practice the
    # returned storage.googleapis.com link can come back with the object's
    # GCS ACL not actually set to public-read (anonymous fetches 403 with
    # AccessDenied) -- a platform-side issue, not something this app's
    # request/response handling controls. Keeping our own copy means the
    # in-app gallery still renders even when that happens; superdocs_image_url
    # is still what gets embedded into the document itself, since that's the
    # URL SuperDocs' own editor/export pipeline needs to resolve.
    local_image_path: str | None = Field(default=None)
    embedded_in_document_id: str | None = Field(default=None, foreign_key="document.id")
    embedded: bool = False
    created_at: datetime = Field(default_factory=_now)


class ChatSession(SQLModel, table=True):
    """One conversation thread. document_id is null for a campaign-level
    chat (e.g. "create a new NPC"); set for a document-scoped chat (e.g.
    editing one character sheet)."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    document_id: str | None = Field(default=None, foreign_key="document.id")
    created_at: datetime = Field(default_factory=_now)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    chat_session_id: str = Field(foreign_key="chatsession.id", index=True)
    role: ChatRole
    content: str
    # set on an assistant message that resulted in a new DocumentVersion or
    # a newly-created Document, so the frontend can link straight to it
    result_document_id: str | None = None
    result_version_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Export(SQLModel, table=True):
    """Audit row per export request. The actual bytes are streamed straight
    back in the HTTP response (never stored server-side), so this is a
    record of "what was exported when", not a file store."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    campaign_id: str = Field(foreign_key="campaign.id", index=True)
    format: ExportFormat
    status: ExportStatus = ExportStatus.COMPLETE
    document_count: int = 0
    created_at: datetime = Field(default_factory=_now)


class ChangeEvent(SQLModel, table=True):
    """Append-only audit log. Every document create/import, proposed edit,
    approve/reject decision, link staleness flip, image generation, and
    export lands here."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    event_type: ChangeEventType
    timestamp: datetime = Field(default_factory=_now)

    campaign_id: str | None = Field(default=None, foreign_key="campaign.id")
    document_id: str | None = Field(default=None, foreign_key="document.id")
    link_id: str | None = Field(default=None, foreign_key="documentlink.id")

    actor: str = "system"  # "system" | "human:<name>" | "ai"
    description: str
    approved: bool | None = None
