"""Alembic environment configuration.

Reads the database URL from our app config (never hardcoded)
and imports all models so autogenerate can detect them.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import our app config for the database URL
from app.core.config import settings

# Import Base and all models so Alembic autogenerate sees them
from app.models import Base  # noqa: F401

# Alembic Config object
config = context.config

# Override sqlalchemy.url with our app's setting
config.set_main_option("sqlalchemy.url", settings.database_url)

# Set up Python logging from the .ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the DB and applies."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
