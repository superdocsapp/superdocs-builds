from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from core.config import DATABASE_URL
from uuid import UUID
from typing import Optional, Any
import json

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def exec(sql: str, values: Optional[dict] = None) -> list[dict]:
    """Run a statement and return rows as dicts.

    Statements that return no rows (INSERT/UPDATE/DELETE without RETURNING)
    are committed and yield an empty list rather than raising
    ResourceClosedError from fetchall().
    """
    async with async_session() as session:
        result = await session.execute(text(sql), _serialize(values or {}))
        rows = result.fetchall() if result.returns_rows else []
        # Commit unconditionally: a mutating statement with RETURNING does
        # return rows, and skipping the commit for those silently discarded
        # the write when the session closed. Committing a SELECT is a no-op.
        await session.commit()
        return [dict(row._mapping) for row in rows]


async def exec_one(sql: str, values: Optional[dict] = None) -> Optional[dict]:
    rows = await exec(sql, values)
    return rows[0] if rows else None


async def exec_scalar(sql: str, values: Optional[dict] = None) -> Any:
    async with async_session() as session:
        result = await session.execute(text(sql), values or {})
        return result.scalar()


async def insert(table: str, data: dict, returning: str = "id") -> dict:
    cols = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING {returning}"
    async with async_session() as session:
        result = await session.execute(text(sql), _serialize(data))
        await session.commit()
        row = result.fetchone()
        return dict(row._mapping)


async def insert_many(statements: list[tuple[str, dict]]) -> None:
    """Run several inserts in one transaction.

    Ingest writes a document row and then its chunks; without a shared
    transaction a failure partway leaves a document with no chunks, which
    then renders and downloads as an empty file forever.
    """
    async with async_session() as session:
        async with session.begin():
            for table, data in statements:
                cols = ", ".join(data.keys())
                placeholders = ", ".join(f":{k}" for k in data)
                await session.execute(
                    text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"),
                    _serialize(data),
                )


async def delete(table: str, where: dict) -> None:
    where_clause = " AND ".join(f"{k} = :where_{k}" for k in where)
    sql = f"DELETE FROM {table} WHERE {where_clause}"
    params = {f"where_{k}": _serialize_val(v) for k, v in where.items()}
    async with async_session() as session:
        await session.execute(text(sql), params)
        await session.commit()


async def update(table: str, where: dict, data: dict) -> None:
    set_clause = ", ".join(f"{k} = :set_{k}" for k in data)
    where_clause = " AND ".join(f"{k} = :where_{k}" for k in where)
    sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
    params = {}
    for k, v in data.items():
        params[f"set_{k}"] = _serialize_val(v)
    for k, v in where.items():
        params[f"where_{k}"] = _serialize_val(v)
    async with async_session() as session:
        await session.execute(text(sql), params)
        await session.commit()


async def claim_job(job_id: UUID, agent_name: str) -> Optional[dict]:
    sql = """
        UPDATE jobs SET status = 'claimed', claimed_by = :agent, claimed_at = now()
        WHERE id = :id AND status = 'pending'
        RETURNING id, kind, agent, payload, status
    """
    return await exec_one(sql, {"id": str(job_id), "agent": agent_name})


async def poll_pending_job(kind: str, agent_name: str) -> Optional[dict]:
    row = await exec_one(
        "SELECT id FROM jobs WHERE kind = :kind AND status = 'pending' ORDER BY created_at LIMIT 1",
        {"kind": kind},
    )
    if not row:
        return None
    return await claim_job(row["id"], agent_name)


def to_uuid(v: Any) -> UUID:
    """Coerce a DB-returned id to a uuid.UUID.

    asyncpg returns native UUID objects (asyncpg.pgproto.pgproto.UUID, a
    uuid.UUID subclass) for uuid columns, so passing one back into UUID()
    raises AttributeError. This accepts either form.
    """
    if isinstance(v, UUID):
        return v
    return UUID(str(v))


def _serialize(data: dict) -> dict:
    return {k: _serialize_val(v) for k, v in data.items()}


def _serialize_val(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    # datetime is passed through as-is: asyncpg requires a native
    # datetime.datetime for timestamp/timestamptz columns, not a string.
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v