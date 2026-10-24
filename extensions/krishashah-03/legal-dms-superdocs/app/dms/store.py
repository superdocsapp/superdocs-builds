"""
Mock legal document-management system.

Models the parts of iManage-style DMSes that this integration actually depends
on: a document belongs to exactly one matter, a matter can restrict which
users may see it (an "ethical wall"), a document can be locked to one user at
a time (check-out/check-in), and every check-in creates a new version with a
DMS-native comment and metadata rather than overwriting history.

New in this revision: create_document() lets a real uploaded file become
version 1 (with real exported_bytes from day one - not the earlier seed-data
shortcut where version 1 was just typed-in text with no file behind it).
get_version()/list_versions() support the version-history and download
endpoints, reusing the exact same ethical-wall check every other read
already goes through.
"""
from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class DMSError(Exception):
    """Base class for all mock-DMS errors."""


class EthicalWallViolation(DMSError):
    """Raised when a user without matter access tries to read or write it."""


class DocumentLockedError(DMSError):
    """Raised when a document is checked out by someone else."""


class NotCheckedOutError(DMSError):
    """Raised when a check-in is attempted by someone who doesn't hold the lock."""


class NotFoundError(DMSError):
    """Raised when a matter/document/user/version id doesn't exist."""


_id_counter = itertools.count(1)


def _next_id(prefix: str) -> str:
    return f"{prefix}-{next(_id_counter)}"


@dataclass
class User:
    user_id: str
    name: str
    role: str  # "attorney" | "paralegal" | "admin"


@dataclass
class Matter:
    matter_id: str
    name: str
    client_name: str
    # None = open to every user in the firm. A non-None set is the ethical
    # wall: only these user_ids may read/write anything filed to this matter.
    ethical_wall: set[str] | None = None

    def is_accessible(self, user_id: str) -> bool:
        if self.ethical_wall is None:
            return True
        return user_id in self.ethical_wall


@dataclass
class Version:
    version_number: int
    html: str  # editable-form snapshot, re-fed into SuperDocs on the next checkout
    comment: str
    metadata: dict
    created_by: str
    created_at: datetime
    # The actual DMS-stored file for this version (e.g. docx bytes). Real
    # uploads (via create_document) always set this from day one. Older
    # seed/demo fixtures may leave this None - see README "known limitations".
    exported_bytes: bytes | None = None
    exported_format: str | None = None


@dataclass
class Document:
    document_id: str
    matter_id: str
    title: str
    versions: list[Version] = field(default_factory=list)
    checked_out_by: str | None = None
    # Set once the document has been loaded into a SuperDocs session, so a
    # check-in knows which session to export from.
    active_session_id: str | None = None

    @property
    def current_version(self) -> Version:
        if not self.versions:
            raise NotFoundError(f"Document {self.document_id} has no versions")
        return self.versions[-1]


class DMSStore:
    """
    The whole mock DMS. One instance is created per test / per app process;
    there is no cross-process persistence, matching the scope of a take-home
    integration rather than a production system.
    """

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.matters: dict[str, Matter] = {}
        self.documents: dict[str, Document] = {}

    # ---------- setup / seeding ----------

    def add_user(self, user_id: str, name: str, role: str = "attorney") -> User:
        user = User(user_id=user_id, name=name, role=role)
        self.users[user_id] = user
        return user

    def add_matter(
        self,
        matter_id: str,
        name: str,
        client_name: str,
        ethical_wall: set[str] | None = None,
    ) -> Matter:
        matter = Matter(
            matter_id=matter_id,
            name=name,
            client_name=client_name,
            ethical_wall=ethical_wall,
        )
        self.matters[matter_id] = matter
        return matter

    def add_document(
        self,
        document_id: str,
        matter_id: str,
        title: str,
        initial_html: str,
        created_by: str,
    ) -> Document:
        """
        Seed-data helper: creates a document with a version 1 that has NO
        exported_bytes, because it's invented text standing in for "however
        this document originally got into the DMS" - not a real upload.
        Real documents should go through create_document() instead, which
        always gives version 1 real file bytes. Kept for the fictional
        Acme/Stratus/Northwind fixtures only.
        """
        if matter_id not in self.matters:
            raise NotFoundError(f"No such matter: {matter_id}")
        doc = Document(document_id=document_id, matter_id=matter_id, title=title)
        doc.versions.append(
            Version(
                version_number=1,
                html=initial_html,
                comment="Initial version",
                metadata={"source": "seed"},
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
            )
        )
        self.documents[document_id] = doc
        return doc

    def create_document(
        self,
        matter_id: str,
        user_id: str,
        title: str,
        html: str,
        exported_bytes: bytes,
        exported_format: str,
    ) -> Document:
        """
        Creates a NEW document from a real uploaded file. Version 1 always
        carries the real uploaded bytes - this is the path that makes the
        "upload -> version 1 -> edit -> version 2" flow actually correct,
        replacing the earlier seed-data shortcut for anything a real user
        does going forward. Ethical-wall-checked: uploading into a matter
        you can't access raises EthicalWallViolation, same as every read.
        """
        self._require_matter_access(matter_id, user_id)
        document_id = _next_id("doc")
        doc = Document(document_id=document_id, matter_id=matter_id, title=title)
        doc.versions.append(
            Version(
                version_number=1,
                html=html,
                comment="Initial upload",
                metadata={"source": "upload", "uploaded_by": user_id},
                created_by=user_id,
                created_at=datetime.now(timezone.utc),
                exported_bytes=exported_bytes,
                exported_format=exported_format,
            )
        )
        self.documents[document_id] = doc
        return doc

    # ---------- access control ----------

    def _require_user(self, user_id: str) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError(f"No such user: {user_id}")
        return user

    def _require_matter_access(self, matter_id: str, user_id: str) -> Matter:
        matter = self.matters.get(matter_id)
        if matter is None:
            raise NotFoundError(f"No such matter: {matter_id}")
        self._require_user(user_id)
        if not matter.is_accessible(user_id):
            raise EthicalWallViolation(
                f"User {user_id} is walled off from matter {matter_id}"
            )
        return matter

    def _require_document(self, document_id: str, user_id: str) -> Document:
        doc = self.documents.get(document_id)
        if doc is None:
            raise NotFoundError(f"No such document: {document_id}")
        self._require_matter_access(doc.matter_id, user_id)
        return doc

    # ---------- reads ----------

    def list_documents(self, matter_id: str, user_id: str) -> list[Document]:
        """Documents in one matter. Raises if the user can't see the matter at all."""
        self._require_matter_access(matter_id, user_id)
        return [d for d in self.documents.values() if d.matter_id == matter_id]

    def get_document(self, document_id: str, user_id: str) -> Document:
        return self._require_document(document_id, user_id)

    def all_documents_visible_to(self, user_id: str) -> list[Document]:
        """
        Every document across every matter this user is entitled to see -
        the candidate pool for precedent search. A document in a matter with
        an ethical wall the user isn't on is never in this list, full stop.
        """
        self._require_user(user_id)
        visible = []
        for doc in self.documents.values():
            matter = self.matters[doc.matter_id]
            if matter.is_accessible(user_id):
                visible.append(doc)
        return visible

    def list_versions(self, document_id: str, user_id: str) -> list[Version]:
        """Every version of a document, oldest first - same ethical-wall
        check as every other read, via _require_document."""
        doc = self._require_document(document_id, user_id)
        return doc.versions

    def get_version(self, document_id: str, version_number: int, user_id: str) -> Version:
        doc = self._require_document(document_id, user_id)
        for version in doc.versions:
            if version.version_number == version_number:
                return version
        raise NotFoundError(f"Document {document_id} has no version {version_number}")

    # ---------- checkout / checkin ----------

    def checkout(self, document_id: str, user_id: str) -> Document:
        doc = self._require_document(document_id, user_id)
        if doc.checked_out_by is not None and doc.checked_out_by != user_id:
            raise DocumentLockedError(
                f"Document {document_id} is checked out by {doc.checked_out_by}"
            )
        doc.checked_out_by = user_id
        return doc

    def set_active_session(self, document_id: str, user_id: str, session_id: str) -> None:
        doc = self._require_document(document_id, user_id)
        doc.active_session_id = session_id

    def checkin(
        self,
        document_id: str,
        user_id: str,
        new_html: str,
        version_comment: str,
        metadata: dict,
        exported_bytes: bytes | None = None,
        exported_format: str | None = None,
    ) -> Version:
        doc = self._require_document(document_id, user_id)
        if doc.checked_out_by != user_id:
            raise NotCheckedOutError(
                f"Document {document_id} is not checked out by {user_id} "
                f"(checked out by: {doc.checked_out_by!r})"
            )
        next_version_number = doc.current_version.version_number + 1
        version = Version(
            version_number=next_version_number,
            html=new_html,
            comment=version_comment,
            metadata=metadata,
            created_by=user_id,
            created_at=datetime.now(timezone.utc),
            exported_bytes=exported_bytes,
            exported_format=exported_format,
        )
        doc.versions.append(version)
        doc.checked_out_by = None
        doc.active_session_id = None
        return version

    def discard_checkout(self, document_id: str, user_id: str) -> None:
        """Release a lock without creating a new version (an abandoned edit)."""
        doc = self._require_document(document_id, user_id)
        if doc.checked_out_by == user_id:
            doc.checked_out_by = None
            doc.active_session_id = None