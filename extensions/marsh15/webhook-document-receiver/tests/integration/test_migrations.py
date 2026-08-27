import os

import psycopg
import pytest

from scripts.migrate import MIGRATIONS_DIR, migrate

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_initial_migration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    from app.config import get_settings

    get_settings.cache_clear()
    migrate()
    migrate()

    with psycopg.connect(DATABASE_URL) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
        }
        assert {
            "deliveries",
            "jobs",
            "pending_changes",
            "decisions",
            "delivery_transitions",
            "schema_migrations",
        } <= tables
        expected_versions = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
        applied_versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        assert applied_versions == expected_versions

    get_settings.cache_clear()
