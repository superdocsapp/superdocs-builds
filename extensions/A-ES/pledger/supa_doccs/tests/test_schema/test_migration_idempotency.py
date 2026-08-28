# Feature: core-postgres-schema, Property 14: Migration Idempotency
"""
Property-based test: Migration Idempotency

For any migration file, applying it to a database where it has already been applied
SHALL produce no errors and no schema changes, due to IF NOT EXISTS guards on all
DDL statements.

**Validates: Requirements 8.4**
"""

import re
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Discover migration files
# ---------------------------------------------------------------------------
_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
_MIGRATION_PATTERN = re.compile(r"^\d+_.+\.sql$")

migration_files: list[Path] = sorted(
    [
        f
        for f in _MIGRATIONS_DIR.iterdir()
        if f.is_file() and _MIGRATION_PATTERN.match(f.name)
    ],
    key=lambda p: p.name,
)

assert len(migration_files) > 0, (
    f"No migration files found in {_MIGRATIONS_DIR}. "
    "Ensure migrations/ directory contains SQL files matching NNN_description.sql."
)


def _strip_transaction_wrappers(sql: str) -> str:
    """Remove BEGIN/COMMIT statements from migration SQL.

    The conftest migration runner and this test manage transactions externally,
    so we strip these to avoid nested transaction errors.
    """
    cleaned = re.sub(
        r"^\s*BEGIN\s*;\s*$", "", sql, flags=re.MULTILINE | re.IGNORECASE
    )
    cleaned = re.sub(
        r"^\s*COMMIT\s*;\s*$", "", cleaned, flags=re.MULTILINE | re.IGNORECASE
    )
    return cleaned


@given(migration=st.sampled_from(migration_files))
def test_migration_idempotency(migration: Path, db_engine):
    """Re-applying any migration to an already-migrated database produces no errors.

    Since conftest.py applies all migrations at session start, re-executing them
    here tests idempotency directly. All DDL uses IF NOT EXISTS and
    CREATE OR REPLACE, so no errors should occur.

    **Validates: Requirements 8.4**
    """
    sql_content = migration.read_text(encoding="utf-8")
    cleaned_sql = _strip_transaction_wrappers(sql_content)

    with db_engine.connect() as conn:
        conn.execute(text(cleaned_sql))
        conn.commit()
