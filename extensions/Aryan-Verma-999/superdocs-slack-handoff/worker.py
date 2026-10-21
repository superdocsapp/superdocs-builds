"""Run durable Slack-to-SuperDocs handoff jobs."""
from __future__ import annotations

import asyncio

from app import DATABASE_PATH, Settings, Store, _store, process_one
import app


async def main() -> None:
    Settings.from_env()
    app._store = Store(DATABASE_PATH)
    try:
        while True:
            processed = await process_one()
            await asyncio.sleep(0 if processed else 2)
    finally:
        app._store.close()


if __name__ == "__main__":
    asyncio.run(main())
