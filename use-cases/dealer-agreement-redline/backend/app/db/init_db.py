from app.db.base import Base
from app.db.session import engine

from app.models.redline_review import (
    RedlineReview,
    RedlineFinding,
)


async def init_db():
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )