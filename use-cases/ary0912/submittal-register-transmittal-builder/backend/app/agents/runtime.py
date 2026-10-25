from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import (
    PostgresSaver,
)

from app.agents.workflow import build_graph
from app.core.config import settings


def _checkpointer_database_url(database_url: str) -> str:
    """Convert a SQLAlchemy PostgreSQL URL to a psycopg connection URL."""

    return database_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )


# ============================================================
# LANGGRAPH PERSISTENT CHECKPOINTER
# ============================================================

try:
    if settings.database_url and settings.database_url.startswith("postgresql"):
        _checkpointer_context = PostgresSaver.from_conn_string(
            _checkpointer_database_url(settings.database_url)
        )
        checkpointer = _checkpointer_context.__enter__()
        checkpointer.setup()
    else:
        checkpointer = MemorySaver()
except Exception:
    checkpointer = MemorySaver()


# ============================================================
# COMPILE THE GRAPH WITH PERSISTENCE
# ============================================================

workflow = build_graph(
    checkpointer=checkpointer
)
