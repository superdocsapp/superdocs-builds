# tests/test_schema/conftest.py
"""
Pytest fixtures for schema property-based tests.

Provides:
- Database connection with migration application at session start
- Per-test transaction rollback isolation (no cleanup needed between tests)
- Pre-populated parent fixtures for relationship testing
- Hypothesis settings configured for minimum 100 examples
"""

import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
import pytest
from hypothesis import settings, HealthCheck
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.base import Base

# ---------------------------------------------------------------------------
# Hypothesis configuration: minimum 100 examples per property test
# ---------------------------------------------------------------------------
settings.register_profile(
    "schema_tests",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=None,
)
settings.load_profile("schema_tests")

# ---------------------------------------------------------------------------
# Database URL resolution
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/docdb_test",
)

# The admin URL connects to the default 'postgres' database for creating the test DB
_ADMIN_DATABASE_URL = os.environ.get(
    "ADMIN_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)


def _extract_dbname(url: str) -> str:
    """Extract the database name from a PostgreSQL connection URL."""
    # Handle the form: postgresql://user:pass@host:port/dbname
    return url.rstrip("/").rsplit("/", 1)[-1]


def _ensure_test_database_exists() -> None:
    """Create the test database if it doesn't already exist.

    Connects to the 'postgres' admin database to issue CREATE DATABASE.
    """
    dbname = _extract_dbname(TEST_DATABASE_URL)
    try:
        conn = psycopg2.connect(_ADMIN_DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,)
            )
            if cur.fetchone() is None:
                # Database doesn't exist — create it
                cur.execute(
                    psycopg2.sql.SQL("CREATE DATABASE {}").format(
                        psycopg2.sql.Identifier(dbname)
                    )
                )
        conn.close()
    except psycopg2.OperationalError as e:
        pytest.fail(
            f"Cannot connect to PostgreSQL admin database to create '{dbname}'. "
            f"Ensure PostgreSQL is running at the configured host.\n"
            f"Error: {e}"
        )


def _apply_migrations(engine) -> None:
    """Apply all SQL migration files in order against the given engine.

    Reads migration files from the project's migrations/ directory and applies
    them sequentially, skipping any already recorded in schema_migrations.
    """
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    migration_pattern = re.compile(r"^(\d+)_.+\.sql$")

    # Discover migration files
    migration_files: list[tuple[int, str, Path]] = []
    for entry in migrations_dir.iterdir():
        match = migration_pattern.match(entry.name)
        if match and entry.is_file():
            migration_id = int(match.group(1))
            migration_files.append((migration_id, entry.name, entry))
    migration_files.sort(key=lambda m: m[0])

    if not migration_files:
        pytest.fail(
            f"No migration files found in {migrations_dir}. "
            "Ensure migrations/ directory contains SQL files."
        )

    with engine.connect() as conn:
        # Ensure schema_migrations table exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        conn.commit()

        # Get already-applied migrations
        result = conn.execute(text("SELECT id FROM schema_migrations ORDER BY id;"))
        applied = {row[0] for row in result.fetchall()}
        highest_applied = max(applied) if applied else -1

        # Apply pending migrations
        for migration_id, filename, filepath in migration_files:
            if migration_id in applied or migration_id <= highest_applied:
                continue

            sql_content = filepath.read_text(encoding="utf-8")
            # Strip BEGIN/COMMIT since we manage transactions ourselves
            cleaned_sql = re.sub(
                r"^\s*BEGIN\s*;\s*$", "", sql_content, flags=re.MULTILINE | re.IGNORECASE
            )
            cleaned_sql = re.sub(
                r"^\s*COMMIT\s*;\s*$", "", cleaned_sql, flags=re.MULTILINE | re.IGNORECASE
            )

            conn.execute(text(cleaned_sql))
            conn.execute(
                text("INSERT INTO schema_migrations (id, filename) VALUES (:id, :filename);"),
                {"id": migration_id, "filename": filename},
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Session-scoped fixtures (one engine/session factory per test session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine():
    """Create a SQLAlchemy engine connected to the test database.

    Ensures the test database exists and all migrations are applied
    before any tests run.
    """
    _ensure_test_database_exists()
    engine = create_engine(TEST_DATABASE_URL, echo=False)
    _apply_migrations(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_session_factory(db_engine):
    """Provide a sessionmaker bound to the test engine."""
    return sessionmaker(bind=db_engine)


# ---------------------------------------------------------------------------
# Per-test fixture: transaction rollback isolation
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session(db_engine, db_session_factory):
    """Provide a database session wrapped in a transaction that rolls back after each test.

    This ensures complete isolation between tests with zero cleanup overhead.
    Each test sees a fresh transactional snapshot of the database.

    Tests use nested savepoints (begin_nested()) to isolate individual Hypothesis
    iterations from each other, preventing aborted-transaction cascades.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = db_session_factory(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Pre-populated parent fixtures for relationship testing
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_document(db_session):
    """Insert and return a pre-populated document row for relationship tests."""
    doc_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO documents (id, filename, mime_type, metadata)
            VALUES (:id, :filename, :mime_type, :metadata)
        """),
        {
            "id": str(doc_id),
            "filename": "test_fixture.pdf",
            "mime_type": "application/pdf",
            "metadata": "{}",
        },
    )
    db_session.flush()
    return doc_id


@pytest.fixture()
def sample_document_version(db_session, sample_document):
    """Insert and return a pre-populated document_version row for relationship tests."""
    version_id = uuid.uuid4()
    content_hash = "a" * 64  # Valid 64-char hex hash
    db_session.execute(
        text("""
            INSERT INTO document_versions (id, document_id, content_hash, storage_ref, version_number)
            VALUES (:id, :document_id, :content_hash, :storage_ref, :version_number)
        """),
        {
            "id": str(version_id),
            "document_id": str(sample_document),
            "content_hash": content_hash,
            "storage_ref": "s3://bucket/test_fixture.pdf",
            "version_number": 1,
        },
    )
    db_session.flush()
    return version_id


@pytest.fixture()
def sample_run(db_session):
    """Insert and return a pre-populated run row for relationship tests."""
    run_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO runs (id, status, initiator, config_snapshot)
            VALUES (:id, :status, :initiator, :config_snapshot)
        """),
        {
            "id": str(run_id),
            "status": "running",
            "initiator": "test_fixture",
            "config_snapshot": "{}",
        },
    )
    db_session.flush()
    return run_id


@pytest.fixture()
def sample_claim(db_session, sample_document_version, sample_run):
    """Insert and return a pre-populated claim row for relationship tests."""
    claim_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO claims (id, document_version_id, run_id, extracted_text, claim_type, confidence)
            VALUES (:id, :document_version_id, :run_id, :extracted_text, :claim_type, :confidence)
        """),
        {
            "id": str(claim_id),
            "document_version_id": str(sample_document_version),
            "run_id": str(sample_run),
            "extracted_text": "Test claim for fixture",
            "claim_type": "factual",
            "confidence": "0.950",
        },
    )
    db_session.flush()
    return claim_id


@pytest.fixture()
def sample_approval_queue_entry(db_session, sample_claim):
    """Insert and return a pre-populated approval_queue row for relationship tests."""
    aq_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO approval_queue (id, claim_id, status, priority)
            VALUES (:id, :claim_id, :status, :priority)
        """),
        {
            "id": str(aq_id),
            "claim_id": str(sample_claim),
            "status": "pending",
            "priority": 3,
        },
    )
    db_session.flush()
    return aq_id
