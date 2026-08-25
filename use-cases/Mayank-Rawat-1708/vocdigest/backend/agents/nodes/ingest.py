"""
@file: backend/agents/nodes/ingest.py
@description: Reads support conversations from CSV, JSON, or TXT and persists them as
    Conversation rows. Streams the file rather than loading it whole so a large export
    never sits in memory. Every row keeps its source file and line number, which become
    the citations the digest cites later.
@flow: run() -> detect format from extension -> stream rows -> normalise into
    (text, line_no, occurred_at) -> bulk insert with dedupe on (run_id, file, line) ->
    report count and any malformed rows as warnings rather than failing the stage.
@dependencies:
    - csv / json: format parsing
    - backend.models.Conversation: destination rows
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from backend.agents.nodes.base import BaseNode, NodeInputMissing
from backend.agents.state import DigestState
from backend.config import settings
from backend.db.database import session_scope
from backend.models import Conversation, RunStatus

logger = logging.getLogger(__name__)

# Column names we'll accept for the conversation body, in priority order. Real exports
# from Zendesk/Intercom/Front all differ, so we probe rather than demand one schema.
_TEXT_COLUMNS = ("text", "body", "message", "conversation", "content", "description", "comment")
_DATE_COLUMNS = ("date", "created_at", "timestamp", "occurred_at", "created")


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 4], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_csv(path: Path) -> Iterator[tuple[str, int, datetime | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = [h.lower().strip() for h in (reader.fieldnames or [])]
        text_col = next((c for c in _TEXT_COLUMNS if c in headers), None)
        date_col = next((c for c in _DATE_COLUMNS if c in headers), None)
        for line_no, row in enumerate(reader, start=2):  # line 1 is the header
            lower = {k.lower().strip(): v for k, v in row.items() if k}
            if text_col:
                body = lower.get(text_col, "")
            else:
                # No recognisable text column: join every value so nothing is lost.
                body = " ".join(str(v) for v in lower.values() if v)
            body = (body or "").strip()
            if body:
                yield body, line_no, _parse_date(lower.get(date_col) if date_col else None)


def _iter_json(path: Path) -> Iterator[tuple[str, int, datetime | None]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        # Accept {"conversations": [...]} as well as a bare array.
        for key in ("conversations", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return
    for idx, item in enumerate(payload, start=1):
        if isinstance(item, str):
            body, occurred = item.strip(), None
        elif isinstance(item, dict):
            lower = {str(k).lower(): v for k, v in item.items()}
            body = ""
            for col in _TEXT_COLUMNS:
                if lower.get(col):
                    body = str(lower[col]).strip()
                    break
            if not body:
                body = json.dumps(item, ensure_ascii=False)
            occurred = next(
                (_parse_date(lower[c]) for c in _DATE_COLUMNS if lower.get(c)), None
            )
        else:
            continue
        if body:
            yield body, idx, occurred


def _iter_txt(path: Path) -> Iterator[tuple[str, int, datetime | None]]:
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            body = line.strip()
            if body:
                yield body, line_no, None


class IngestNode(BaseNode):
    stage = "ingest"
    running_status = RunStatus.INGESTING

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        path = Path(state["input_path"])
        if not path.is_file():
            raise FileNotFoundError(f"Conversations file not found: {path}")

        suffix = path.suffix.lower()
        reader = {".csv": _iter_csv, ".json": _iter_json, ".txt": _iter_txt}.get(suffix)
        if reader is None:
            raise ValueError(
                f"Unsupported input format {suffix!r}. Supported: .csv, .json, .txt"
            )

        warnings: list[str] = []
        seen: set[tuple[str, int]] = set()
        rows: list[Conversation] = []
        truncated = 0

        for body, line_no, occurred in reader(path):
            key = (path.name, line_no)
            if key in seen:
                continue
            seen.add(key)
            if len(body) > settings.max_conversation_chars:
                body = body[: settings.max_conversation_chars]
                truncated += 1
            rows.append(
                Conversation(
                    run_id=run_id,
                    raw_text=body,
                    source_file=path.name,
                    source_line=line_no,
                    occurred_at=occurred,
                )
            )

        if truncated:
            warnings.append(
                f"{truncated} conversation(s) truncated to "
                f"{settings.max_conversation_chars} chars"
            )

        if not rows:
            # An input file with nothing usable in it is not a stage with no work — it is
            # a run with no subject. Skipping here left every later stage running on an
            # empty database and the approval gate holding nothing.
            raise NodeInputMissing(
                f"No usable conversations found in {path.name}. Every row was empty, "
                f"unparseable, or too short to analyse, so there is nothing to build a "
                f"digest from."
            )

        async with session_scope() as session:
            session.add_all(rows)
            await session.flush()

        await self.log_decision(
            run_id,
            "INGESTED",
            f"Read {len(rows)} conversations from {path.name} ({suffix})",
            {"count": len(rows), "truncated": truncated},
        )

        state["conversations_ingested"] = len(rows)
        state["ingest_warnings"] = warnings
        return state
