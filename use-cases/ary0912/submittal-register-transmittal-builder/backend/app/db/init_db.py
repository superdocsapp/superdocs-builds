from sqlalchemy import text

from app.db.session import Base, engine
from app.models import (
    Project,
    Submittal,
    Finding,
    Review,
    Transmittal,
)


def init_db():
    Base.metadata.create_all(bind=engine)

       # `create_all` does not alter tables that already exist.
    # Keep small development migrations here for the local database.
    with engine.begin() as connection:

        # Add unique index for submittal number if missing (SQLite)
        if engine.dialect.name == "sqlite":
            existing_indexes = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA index_list(submittals)")
                )
            }
            if "ix_submittals_number" not in existing_indexes:
                connection.execute(text("CREATE UNIQUE INDEX ix_submittals_number ON submittals (number)"))
        else:
            # PostgreSQL creates unique index automatically with UNIQUE column
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_submittals_number ON submittals (number)"))
        # Add unique constraint index for (project_id, specification_section, title)
        if engine.dialect.name == "sqlite":
            existing_indexes = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA index_list(submittals)")
                )
            }
            if "uq_submittal_identity" not in existing_indexes:
                connection.execute(text("CREATE UNIQUE INDEX uq_submittal_identity ON submittals (project_id, specification_section, title)"))
        else:
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_submittal_identity ON submittals (project_id, specification_section, title)"))

        if engine.dialect.name == "sqlite":
            # Check existing columns in sqlite
            submittal_cols = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info(submittals)")
                )
            }
            transmittal_cols = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info(transmittals)")
                )
            }

            for col in (
                "superdocs_session_id",
                "superdocs_job_id",
                "export_url",
            ):
                if col not in transmittal_cols:
                    connection.execute(
                        text(f"ALTER TABLE transmittals ADD COLUMN {col} VARCHAR")
                    )

            if "description" not in submittal_cols:
                connection.execute(
                    text("ALTER TABLE submittals ADD COLUMN description TEXT")
                )
            if "required_by" not in submittal_cols:
                connection.execute(
                    text("ALTER TABLE submittals ADD COLUMN required_by VARCHAR(255)")
                )
            if "required_form" not in submittal_cols:
                connection.execute(
                    text("ALTER TABLE submittals ADD COLUMN required_form VARCHAR(255)")
                )
            if "source_evidence" not in submittal_cols:
                connection.execute(
                    text("ALTER TABLE submittals ADD COLUMN source_evidence TEXT")
                )
            if "specification_revision" not in submittal_cols:
                connection.execute(
                    text(
                        "ALTER TABLE submittals ADD COLUMN specification_revision VARCHAR(100)"
                    )
                )
            if "register_status" not in submittal_cols:
                connection.execute(
                    text(
                        "ALTER TABLE submittals ADD COLUMN register_status VARCHAR(50) DEFAULT 'NOT_RECEIVED'"
                    )
                )
            if "updated_at" not in submittal_cols:
                connection.execute(
                    text("ALTER TABLE submittals ADD COLUMN updated_at TIMESTAMP")
                )
        else:
            # PostgreSQL migrations
            for column in (
                "superdocs_session_id",
                "superdocs_job_id",
                "export_url",
            ):
                connection.execute(
                    text(
                        f"ALTER TABLE transmittals "
                        f"ADD COLUMN IF NOT EXISTS {column} VARCHAR"
                    )
                )

            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS description TEXT"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS required_by VARCHAR(255)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS required_form VARCHAR(255)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS source_evidence TEXT"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS "
                    "specification_revision VARCHAR(100)"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS "
                    "register_status VARCHAR(50) "
                    "DEFAULT 'NOT_RECEIVED'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE submittals "
                    "ADD COLUMN IF NOT EXISTS "
                    "updated_at TIMESTAMP"
                )
            )

        # Backfill the new register fields for rows created before Phase 4D.
        connection.execute(
            text(
                "UPDATE submittals "
                "SET register_status = 'NOT_RECEIVED' "
                "WHERE register_status IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE submittals "
                "SET updated_at = created_at "
                "WHERE updated_at IS NULL"
            )
        )

if __name__ == "__main__":
    init_db()
