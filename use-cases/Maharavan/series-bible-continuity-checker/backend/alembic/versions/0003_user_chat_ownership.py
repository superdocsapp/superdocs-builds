"""Add Google users and make chat history user-owned."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """CREATE TABLE users (
            id UUID PRIMARY KEY,
            google_subject VARCHAR(255) NOT NULL UNIQUE,
            email VARCHAR(320) NOT NULL UNIQUE,
            display_name VARCHAR(255) NOT NULL DEFAULT '',
            avatar_url VARCHAR(2048),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )""",
        "CREATE INDEX ix_users_google_subject ON users(google_subject)",
        "CREATE INDEX ix_users_email ON users(email)",
        "ALTER TABLE chat_sessions ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE",
        "CREATE INDEX ix_chat_sessions_user_id ON chat_sessions(user_id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE chat_sessions DROP COLUMN user_id")
    op.drop_table("users")