from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def migrate() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('webhook-document-receiver-migrations'))"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version varchar(255) PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = %s", (path.name,)
            ).fetchone()
            if applied is not None:
                continue
            connection.execute(path.read_text(encoding="utf-8"), prepare=False)
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,)
            )
            print(f"applied {path.name}")


if __name__ == "__main__":
    migrate()
