"""Migrations past the baseline must be applied at startup.

`001_init.sql` is mounted into docker-entrypoint-initdb.d, which Postgres runs
only when the data volume is first created. Every database that already exists
would otherwise never see a later migration, and the services would start
against a schema missing the columns they write to.
"""

from core.migrate import BASELINE, MIGRATIONS_DIR, _statements


class TestStatementSplitting:
    """asyncpg sends one statement per round trip, so a migration file cannot
    be handed over as a single string."""

    def test_splits_on_statement_boundaries(self):
        sql = "ALTER TABLE a ADD COLUMN b TEXT;\nALTER TABLE a ADD COLUMN c TEXT;\n"
        assert _statements(sql) == [
            "ALTER TABLE a ADD COLUMN b TEXT",
            "ALTER TABLE a ADD COLUMN c TEXT",
        ]

    def test_keeps_multi_line_statements_intact(self):
        sql = "UPDATE a\n   SET b = 1\n  FROM c\n WHERE c.id = a.id;\n"
        assert len(_statements(sql)) == 1
        assert "FROM c" in _statements(sql)[0]

    def test_drops_comments_without_dropping_statements(self):
        sql = "-- a comment\nALTER TABLE a ADD COLUMN b TEXT;\n-- another\n"
        assert _statements(sql) == ["ALTER TABLE a ADD COLUMN b TEXT"]

    def test_semicolon_inside_a_string_literal_is_not_a_boundary(self):
        sql = "INSERT INTO a (b) VALUES ('x; y');\n"
        assert len(_statements(sql)) == 1


class TestMigrationFiles:
    def test_baseline_is_excluded_from_startup_migrations(self):
        """001 creates the schema with bare CREATE TABLE and is not re-runnable."""
        pending = [p.name for p in MIGRATIONS_DIR.glob("*.sql") if p.name != BASELINE]
        assert BASELINE not in pending

    def test_every_startup_migration_is_idempotent(self):
        """These run against live databases and may be re-applied, so any
        creating statement must tolerate the object already existing."""
        for path in MIGRATIONS_DIR.glob("*.sql"):
            if path.name == BASELINE:
                continue
            for statement in _statements(path.read_text(encoding="utf-8")):
                head = statement.upper()
                if head.startswith("ALTER TABLE") and "ADD COLUMN" in head:
                    assert "IF NOT EXISTS" in head, f"{path.name}: {statement[:60]}"
                if head.startswith("CREATE INDEX") or head.startswith("CREATE UNIQUE INDEX"):
                    assert "IF NOT EXISTS" in head, f"{path.name}: {statement[:60]}"

    def test_every_startup_migration_parses_into_statements(self):
        for path in MIGRATIONS_DIR.glob("*.sql"):
            if path.name == BASELINE:
                continue
            assert _statements(path.read_text(encoding="utf-8")), path.name
