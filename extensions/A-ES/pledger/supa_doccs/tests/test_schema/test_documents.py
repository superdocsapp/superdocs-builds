# Feature: core-postgres-schema, Property 1: MIME Type Validation
# Feature: core-postgres-schema, Property 2: Content-Hash Deduplication
# Feature: core-postgres-schema, Property 3: Document Version Immutability
# Feature: core-postgres-schema, Property 4: Composite Unique Constraints
"""
Property-based tests for documents and document_versions tables.

Tests cover:
- MIME type CHECK constraint validation
- Content-hash deduplication via UNIQUE(document_id, content_hash)
- Immutability trigger on content_hash and storage_ref
- Composite unique constraint on (document_id, version_number)
"""

import uuid

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InternalError


# Valid MIME types as defined in the schema CHECK constraint
VALID_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
]

# Strategy for generating valid 64-character hex content hashes
content_hash_strategy = st.text(
    alphabet="0123456789abcdef", min_size=64, max_size=64
)


# ---------------------------------------------------------------------------
# Property 1: MIME Type Validation
# ---------------------------------------------------------------------------


@given(
    mime_type=st.sampled_from(VALID_MIME_TYPES) | st.text(min_size=1, max_size=100).filter(
        lambda s: "\x00" not in s
    ),
)
def test_mime_type_validation(db_session, mime_type: str):
    """**Validates: Requirements 1.1, 1.6**

    For any string used as mime_type when inserting into documents,
    the insertion SHALL succeed if and only if the value is one of the
    allowed MIME types.
    """
    doc_id = uuid.uuid4()

    savepoint = db_session.begin_nested()
    try:
        db_session.execute(
            text("""
                INSERT INTO documents (id, filename, mime_type, metadata)
                VALUES (:id, :filename, :mime_type, :metadata)
            """),
            {
                "id": str(doc_id),
                "filename": "test_file.pdf",
                "mime_type": mime_type,
                "metadata": "{}",
            },
        )
        db_session.flush()
        savepoint.commit()

        # Insertion succeeded — mime_type must be in the allowed list
        assert mime_type in VALID_MIME_TYPES, (
            f"Insertion should have failed for mime_type='{mime_type}' "
            f"which is not in the allowed set"
        )

    except (IntegrityError, InternalError):
        savepoint.rollback()

        # Insertion was rejected — mime_type must NOT be in the allowed list
        assert mime_type not in VALID_MIME_TYPES, (
            f"Insertion should have succeeded for valid mime_type='{mime_type}'"
        )


# ---------------------------------------------------------------------------
# Property 2: Content-Hash Deduplication
# ---------------------------------------------------------------------------


@given(
    content_hash=content_hash_strategy,
    version_number=st.integers(min_value=2, max_value=10000),
)
def test_content_hash_deduplication(db_session, sample_document, content_hash: str, version_number: int):
    """**Validates: Requirements 1.3, 7.5**

    For any document and content hash, inserting a second document_versions row
    with the same (document_id, content_hash) pair SHALL raise a unique constraint
    violation.
    """
    # Wrap entire iteration in a savepoint so data doesn't persist
    outer_savepoint = db_session.begin_nested()

    # Insert first version — should always succeed
    version_id_1 = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
            VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
        """),
        {
            "id": str(version_id_1),
            "document_id": str(sample_document),
            "content_hash": content_hash,
            "storage_ref": "s3://bucket/first.pdf",
            "version_number": version_number,
        },
    )
    db_session.flush()

    # Insert second version with SAME (document_id, content_hash) — must fail
    version_id_2 = uuid.uuid4()
    inner_savepoint = db_session.begin_nested()
    with pytest.raises((IntegrityError, InternalError)):
        db_session.execute(
            text("""
                INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
                VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
            """),
            {
                "id": str(version_id_2),
                "document_id": str(sample_document),
                "content_hash": content_hash,
                "storage_ref": "s3://bucket/second.pdf",
                "version_number": version_number + 1,
            },
        )
        db_session.flush()

    inner_savepoint.rollback()

    # Rollback the entire iteration
    outer_savepoint.rollback()


# ---------------------------------------------------------------------------
# Property 3: Document Version Immutability
# ---------------------------------------------------------------------------


@given(
    new_content_hash=content_hash_strategy,
    new_storage_ref=st.text(min_size=1, max_size=200).filter(
        lambda s: "\x00" not in s
    ),
    modify_hash=st.booleans(),
)
def test_document_version_immutability(
    db_session,
    sample_document,
    new_content_hash: str,
    new_storage_ref: str,
    modify_hash: bool,
):
    """**Validates: Requirements 1.4**

    For any existing document_versions row, any UPDATE that modifies content_hash
    or storage_ref SHALL be rejected by the immutability trigger.
    """
    # Wrap entire iteration in a savepoint so data doesn't persist
    outer_savepoint = db_session.begin_nested()

    # Insert a version to attempt modification on
    version_id = uuid.uuid4()
    original_hash = "b" * 64
    original_ref = "s3://bucket/original.pdf"

    db_session.execute(
        text("""
            INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
            VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
        """),
        {
            "id": str(version_id),
            "document_id": str(sample_document),
            "content_hash": original_hash,
            "storage_ref": original_ref,
            "version_number": 2,
        },
    )
    db_session.flush()

    if modify_hash:
        # Attempt to change content_hash
        # Skip if the new hash happens to be the same as original
        assume(new_content_hash != original_hash)

        inner_savepoint = db_session.begin_nested()
        with pytest.raises((IntegrityError, InternalError)) as exc_info:
            db_session.execute(
                text("""
                    UPDATE document_versions
                    SET content_hash = :new_hash
                    WHERE id = :id
                """),
                {"id": str(version_id), "new_hash": new_content_hash},
            )
            db_session.flush()

        inner_savepoint.rollback()
        assert "immutable" in str(exc_info.value).lower(), (
            f"Expected 'immutable' in error message, got: {exc_info.value}"
        )
    else:
        # Attempt to change storage_ref
        assume(new_storage_ref != original_ref)

        inner_savepoint = db_session.begin_nested()
        with pytest.raises((IntegrityError, InternalError)) as exc_info:
            db_session.execute(
                text("""
                    UPDATE document_versions
                    SET storage_ref = :new_ref
                    WHERE id = :id
                """),
                {"id": str(version_id), "new_ref": new_storage_ref},
            )
            db_session.flush()

        inner_savepoint.rollback()
        assert "immutable" in str(exc_info.value).lower(), (
            f"Expected 'immutable' in error message, got: {exc_info.value}"
        )

    # Rollback the entire iteration
    outer_savepoint.rollback()


# ---------------------------------------------------------------------------
# Property 4: Composite Unique Constraints
# ---------------------------------------------------------------------------


@given(
    version_number=st.integers(min_value=1, max_value=10000),
)
def test_composite_unique_document_version_number(
    db_session, sample_document, version_number: int,
):
    """**Validates: Requirements 1.5, 3.5**

    For any (document_id, version_number) pair in document_versions, inserting a
    duplicate combination SHALL raise a unique constraint violation.
    """
    # Wrap entire iteration in a savepoint so data doesn't persist
    outer_savepoint = db_session.begin_nested()

    # Insert first version with the given version_number
    version_id_1 = uuid.uuid4()
    hash_1 = uuid.uuid4().hex + uuid.uuid4().hex  # 64-char unique hex string

    db_session.execute(
        text("""
            INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
            VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
        """),
        {
            "id": str(version_id_1),
            "document_id": str(sample_document),
            "content_hash": hash_1,
            "storage_ref": "s3://bucket/v1.pdf",
            "version_number": version_number,
        },
    )
    db_session.flush()

    # Insert second version with SAME (document_id, version_number) — must fail
    version_id_2 = uuid.uuid4()
    hash_2 = uuid.uuid4().hex + uuid.uuid4().hex  # Different hash

    inner_savepoint = db_session.begin_nested()
    with pytest.raises((IntegrityError, InternalError)):
        db_session.execute(
            text("""
                INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
                VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
            """),
            {
                "id": str(version_id_2),
                "document_id": str(sample_document),
                "content_hash": hash_2,
                "storage_ref": "s3://bucket/v2.pdf",
                "version_number": version_number,
            },
        )
        db_session.flush()

    inner_savepoint.rollback()

    # Rollback the entire iteration
    outer_savepoint.rollback()
