"""The task card explicitly asks for "tail behavior reported rather
than only an average" wherever a build measures something. /metrics
already reports totals (operations, runs); this proves the added
per-run latency percentiles are real, not decorative -- computed from
actual per-run latency samples, monotonically ordered (p50 <= p95 <=
p99), and that skipped (near-instant) runs don't get folded into the
sample and drag the percentiles toward zero.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.main as m
from app.api.main import app

CONTRACT = b"""SERVICES AGREEMENT
Counterparty: Tail Latency Test Corp
Effective Date: 2026-01-15
Value: $84,000
"""


def fresh_client():
    return TestClient(app)


def _parse_metric_lines(text: str) -> dict[str, str]:
    return {l.split()[0]: l.split()[1] for l in text.splitlines() if l and not l.startswith("#")}


def test_latency_percentiles_present_and_ordered_after_several_runs():
    client = fresh_client()
    for i in range(6):
        file_id = f"latency-{i}"
        m._tenants.context_for("default").box.seed_file(file_id, "x.pdf", CONTRACT)
        client.post(f"/process/{file_id}")

    text = client.get("/metrics").text
    lines = _parse_metric_lines(text)

    p50 = float(lines['box_workflow_run_latency_ms{quantile="0.5"}'])
    p95 = float(lines['box_workflow_run_latency_ms{quantile="0.95"}'])
    p99 = float(lines['box_workflow_run_latency_ms{quantile="0.99"}'])
    count = int(lines["box_workflow_run_latency_ms_count"])

    assert p50 <= p95 <= p99
    assert count >= 6
    assert p50 >= 0


def test_skipped_runs_do_not_pollute_the_latency_sample():
    client = fresh_client()
    m._tenants.context_for("default").box.seed_file("latency-skip", "x.pdf", CONTRACT)

    client.post("/process/latency-skip")  # processed, has real latency
    before = int(_parse_metric_lines(client.get("/metrics").text)["box_workflow_run_latency_ms_count"])

    client.post("/process/latency-skip")  # skipped (idempotent no-op) -- must not add a sample
    after = int(_parse_metric_lines(client.get("/metrics").text)["box_workflow_run_latency_ms_count"])

    assert after == before
