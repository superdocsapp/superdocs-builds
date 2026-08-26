from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    # PostgreSQL deployments should install pgvector; the migration target is vector(16).
    # Keeping the model importable without the optional package makes the offline test path lightweight.
    if Vector is not None:
        embedding = mapped_column(Vector(16), nullable=True)
