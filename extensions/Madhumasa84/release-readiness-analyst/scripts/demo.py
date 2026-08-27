from __future__ import annotations

import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
db_fd, db_name = tempfile.mkstemp(prefix="rra-demo-", suffix=".db")
os.close(db_fd)
db_file = Path(db_name)
os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

import sys

sys.path.insert(0, str(ROOT / "backend"))
from app.db import init_db, SessionLocal  # noqa: E402
from app.workflow import DurableWorkflow  # noqa: E402


def main() -> None:
    try:
        init_db()
        workflow = DurableWorkflow(SessionLocal)
        run = workflow.create_run("demo-workspace", "Q3 release readiness")
        for filename in ("requirements.md", "test-evidence.md", "design-notes.md"):
            workflow.add_source(run.id, filename, "text/markdown", (ROOT / "fixtures" / filename).read_bytes())
        snapshot = workflow.execute(run.id)
        required = [item for item in snapshot["findings"] if item["decision_required"]]
        final = workflow.submit_decisions(run.id, [{"finding_id": item["id"], "state": "approved"} for item in required])
        print(f"run={run.id} status={final['status']} findings={len(final['findings'])} stages={len(final['metrics'])}")
        print(f"verdict={final['report']['verdict']} cited_findings={len(final['report']['findings'])}")
    finally:
        db_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
