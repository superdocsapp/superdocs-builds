"""
@file: backend/db/migrations/env.py
@description: Alembic environment. Runs migrations against the async engine, reusing the
    application's own settings so the migration target can never drift from what the app
    connects to. Also ensures the pgvector extension exists before any vector column is
    created.
@flow: alembic invoked -> read DATABASE_URL from settings -> open an async connection ->
    CREATE EXTENSION vector -> run migrations in a transaction.
@dependencies: alembic, sqlalchemy.ext.asyncio, backend.config, backend.models
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.config import settings
from backend.models import Base

config = context.config
# Single source of truth: the app's settings, not a duplicated URL in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # pgvector must exist before a Vector column is created, and Alembic gives us no
    # earlier hook than this.
    if connection.dialect.name == "postgresql":
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # Explicit commit. Under SQLAlchemy 2.0 async, connect() opens an implicit
        # transaction that is ROLLED BACK when the context exits unless committed here.
        # Without this line Alembic reports "Running upgrade -> 0001" and succeeds, but
        # the database is left completely empty — a silent no-op that looks like a
        # working migration.
        await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
