import json
from pathlib import Path

import httpx
import pytest

from edit_precision_evaluator.api import create_app


@pytest.mark.asyncio
async def test_health_and_corpus_endpoints() -> None:
    project = Path(__file__).resolve().parents[2]
    transport = httpx.ASGITransport(app=create_app(project))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/api/health")
        corpus = await client.get("/api/corpus")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "corpus_errors": []}
    assert corpus.status_code == 200
    assert corpus.json()["cases"] == 13
    assert corpus.json()["by_instruction_type"] == {
        "global_rename": 3,
        "one_section": 4,
        "single_sentence": 3,
        "table_row": 3,
    }
    assert corpus.json()["ambiguous_cases"] == ["section-notice-ambiguous"]


@pytest.mark.asyncio
async def test_report_is_explicitly_marked_as_fixture(tmp_path: Path) -> None:
    (tmp_path / "corpus/documents").mkdir(parents=True)
    (tmp_path / "results").mkdir()
    (tmp_path / "corpus/cases.jsonl").write_text("\n")
    (tmp_path / "results/demo.json").write_text(json.dumps({"schema_version": 1}))
    transport = httpx.ASGITransport(app=create_app(tmp_path))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/report")

    assert response.status_code == 200
    assert response.json()["data_source"] == "fixture"
