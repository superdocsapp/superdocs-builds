import json
import asyncio
from uuid import UUID, uuid4
from datetime import datetime, timezone
from core.llm_provider import MockLLMProvider
from core.db import insert, exec


async def run_cli():
    import sys

    llm = MockLLMProvider()

    if len(sys.argv) < 3:
        print("Usage: python -m agent_2 run <run_id>  OR  python -m agent_2 analyze <change_feed_json>")
        return

    cmd = sys.argv[1]

    if cmd == "run":
        from agents.analyzer.poller import Poller

        run_id = UUID(sys.argv[2])
        rows = await exec("SELECT id FROM documents WHERE run_id = :rid", {"rid": str(run_id)})
        doc_ids = [to_uuid(r["id"]) for r in rows]
        if not doc_ids:
            print("No documents for this run")
            return

        p = Poller(llm)
        await p.run_manual(run_id, doc_ids)
        print(f"Analysis complete for run {run_id}")

    elif cmd == "analyze":
        feed_file = sys.argv[2]
        from agents.analyzer.change_parser import ChangeParser
        from agents.analyzer.finder import Finder
        from agents.analyzer.retriever import Retriever
        from agents.analyzer.poller import Poller

        run_id = uuid4()
        await insert("runs", {
            "id": str(run_id),
            "trigger": "manual",
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc),
        })

        cp = ChangeParser(llm)
        with open(feed_file) as f:
            feed = json.load(f)

        change_facts = await cp.parse(run_id, feed_jsonl=json.dumps(feed))
        print(f"Parsed {len(change_facts)} change facts from {feed_file}")


if __name__ == "__main__":
    asyncio.run(run_cli())