import asyncio
from uuid import uuid4
from core.superdocs_client import SuperDocsClient
from agents.ingestor.ingestor import Ingestor
from agents.ingestor.dispatcher import Dispatcher
from agents.ingestor.watcher import DocWatcher
from core.db import insert
from datetime import datetime, timezone


async def run_cli():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m agent_1 [watch|ingest] <path>")
        return

    cmd = sys.argv[1]

    if cmd == "watch":
        path = sys.argv[2] if len(sys.argv) > 2 else None
        sd = SuperDocsClient()

        async def cb(p: str):
            rid = uuid4()
            await insert(
                "runs",
                {
                    "id": str(rid),
                    "trigger": f"file_change:{p}",
                    "status": "in_progress",
                    "created_at": datetime.now(timezone.utc),
                },
            )
            ing = Ingestor(sd, sd.session_id)
            parsed = await ing.ingest_file(p, rid)
            if parsed:
                await Dispatcher.dispatch_ingestion(rid, [parsed.document_id])
                print(f"dispatched {p}")

        w = DocWatcher(watched_dir=path, callback=cb)
        w.start()
        print(f"watching {w.watched_dir}")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            w.stop()

    elif cmd == "ingest":
        path = sys.argv[2]
        sd = SuperDocsClient()
        ing = Ingestor(sd, sd.session_id)
        rid = uuid4()
        await insert(
            "runs",
            {
                "id": str(rid),
                "trigger": "manual",
                "status": "in_progress",
                "created_at": datetime.now(timezone.utc),
            },
        )
        parsed = await ing.ingest_file(path, rid)
        if parsed:
            await Dispatcher.dispatch_ingestion(rid, [parsed.document_id])
            print(f"ingested {path} -> {parsed.document_id}")
        else:
            print("no new file to ingest")


if __name__ == "__main__":
    asyncio.run(run_cli())