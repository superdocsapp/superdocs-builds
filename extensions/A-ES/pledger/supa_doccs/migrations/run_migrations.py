"""
Migration runner for the agentic document-intelligence system.

Applies sequential SQL migration files from the migrations/ directory,
tracking applied migrations in the schema_migrations table.

Usage:
    python migrations/run_migrations.py

Requires DATABASE_URL environment variable (e.g., postgresql://user:pass@host:port/dbname).
"""

import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql


MIGRATIONS_DIR = Path(__file__).parent

# Pattern to match migration files: NNN_description.sql
MIGRATION_FILE_PATTERN = re.compile(r"^(\d+)_.+\.sql$")


def get_database_url() -> str:
    """Retrieve DATABASE_URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return url


def ensure_schema_migrations_table(conn) -> None:
    """Create the schema_migrations table if it does not exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
    conn.commit()


def get_applied_migrations(conn) -> set[int]:
    """Return the set of migration IDs already applied."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM schema_migrations ORDER BY id;")
        return {row[0] for row in cur.fetchall()}


def discover_migration_files() -> list[tuple[int, str, Path]]:
    """
    Discover all SQL migration files in the migrations directory.

    Returns a sorted list of (id, filename, full_path) tuples.
    """
    migrations = []
    for entry in MIGRATIONS_DIR.iterdir():
        match = MIGRATION_FILE_PATTERN.match(entry.name)
        if match and entry.is_file():
            migration_id = int(match.group(1))
            migrations.append((migration_id, entry.name, entry))
    migrations.sort(key=lambda m: m[0])
    return migrations


def apply_migration(conn, migration_id: int, filename: str, filepath: Path) -> None:
    """
    Apply a single migration file within a transaction.

    Reads the SQL content, executes it, and records success in schema_migrations.
    The entire operation is wrapped in a single transaction — if anything fails,
    the migration and its record both roll back.
    """
    sql_content = filepath.read_text(encoding="utf-8")

    # Strip any BEGIN/COMMIT from the file since we manage the transaction
    # ourselves. This allows migration files to optionally include them
    # for standalone execution while still working with this runner.
    cleaned_sql = sql_content
    cleaned_sql = re.sub(r"^\s*BEGIN\s*;\s*$", "", cleaned_sql, flags=re.MULTILINE | re.IGNORECASE)
    cleaned_sql = re.sub(r"^\s*COMMIT\s*;\s*$", "", cleaned_sql, flags=re.MULTILINE | re.IGNORECASE)

    with conn.cursor() as cur:
        # Execute the migration SQL
        cur.execute(cleaned_sql)
        # Record the migration as applied
        cur.execute(
            "INSERT INTO schema_migrations (id, filename) VALUES (%s, %s);",
            (migration_id, filename),
        )
    conn.commit()


def run_migrations() -> None:
    """Main entry point: connect, discover, and apply pending migrations."""
    database_url = get_database_url()

    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    try:
        # Ensure tracking table exists
        ensure_schema_migrations_table(conn)

        # Get already-applied migrations
        applied = get_applied_migrations(conn)
        highest_applied = max(applied) if applied else -1

        # Discover available migration files
        migrations = discover_migration_files()

        if not migrations:
            print("No migration files found.")
            return

        applied_count = 0
        skipped_count = 0

        for migration_id, filename, filepath in migrations:
            if migration_id in applied or migration_id <= highest_applied:
                print(f"  SKIP  {filename} (already applied)")
                skipped_count += 1
                continue

            print(f"  APPLY {filename} ...", end=" ")
            try:
                apply_migration(conn, migration_id, filename, filepath)
                print("OK")
                applied_count += 1
            except Exception as e:
                conn.rollback()
                print(f"FAILED\n\nERROR applying {filename}: {e}", file=sys.stderr)
                sys.exit(1)

        print(f"\nDone. Applied: {applied_count}, Skipped: {skipped_count}")

    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
