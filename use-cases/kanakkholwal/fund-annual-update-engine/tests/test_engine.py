"""Runs with no API key and no network. The client is exercised through a mock transport, so the
request shapes are really asserted rather than assumed.
"""

import json
from pathlib import Path

import httpx
import pytest

from fund_update.domain.documents import read_document, read_set
from fund_update.domain.fieldmap import load_fieldmap
from fund_update.domain.guards import (
    check_intended_values_landed,
    check_only_intended_values_moved,
    check_protected_wording,
    check_tables_did_not_reflow,
)
from fund_update.domain.plan import build_plan, read_figures, write_reference_markdown
from fund_update.superdocs.client import (
    OperationBudgetExceeded,
    SuperDocsClient,
    parse_change,
    save_export,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "fixtures" / "baseline"
DATA = ROOT / "fixtures" / "data" / "figures-2025.csv"


@pytest.fixture(scope="module")
def fieldmap():
    return load_fieldmap()


@pytest.fixture(scope="module")
def plan(fieldmap):
    views = read_set(BASELINE, fieldmap)
    return build_plan(views, read_figures(DATA), fieldmap)


# --- the documented trap ---------------------------------------------------------


def test_change_content_arriving_as_a_json_string_is_parsed():
    """The single most common integration failure: content is a JSON-encoded string."""
    raw = {"change_id": "c1", "content": json.dumps({"summary": "OCF 0.82% to 0.79%", "field": "ocf"})}
    change = parse_change(raw)

    assert isinstance(change.content, dict), "a string here produces cards of undefined fields"
    assert change.content["summary"] == "OCF 0.82% to 0.79%"
    assert change.change_id == "c1"


def test_change_content_arriving_as_an_object_is_left_alone():
    change = parse_change({"change_id": "c2", "content": {"summary": "already an object"}})
    assert change.content["summary"] == "already an object"


def test_double_encoded_content_is_still_recovered():
    raw = {"change_id": "c3", "content": json.dumps(json.dumps({"summary": "twice"}))}
    assert parse_change(raw).content["summary"] == "twice"


def test_unparseable_content_degrades_instead_of_exploding():
    change = parse_change({"change_id": "c4", "content": "not json at all"})
    assert change.content == {"text": "not json at all"}


# --- the plan --------------------------------------------------------------------


def test_only_changed_fields_become_edits(plan):
    """An update should cost like an update."""
    touched = {e.field_id for e in plan.edits}
    assert "perf_2021" not in touched
    assert "perf_2022" not in touched
    assert {"perf_2021", "perf_2022", "perf_2023", "perf_2024"} <= set(plan.unchanged)


def test_a_figure_arriving_incomplete_is_surfaced_not_invented(plan):
    unresolved = {u.field_id for u in plan.unresolved}
    assert "holding_2" in unresolved
    assert not any(e.field_id == "holding_2" for e in plan.edits)
    reason = next(u.reason for u in plan.unresolved if u.field_id == "holding_2")
    assert "will not invent" in reason


def test_a_value_inside_a_sentence_keeps_its_sentence(plan):
    """Replacing '4 out of 7' with a bare '5' would silently delete the scale."""
    sri = next(e for e in plan.edits if e.field_id == "sri")
    assert sri.old_value == "4 out of 7"
    assert sri.new_value == "5 out of 7"


def test_a_figure_shared_across_documents_updates_all_of_them(plan):
    ocf = {e.document for e in plan.edits if e.field_id == "ocf"}
    assert ocf == {"prospectus", "factsheet", "kid"}


def test_edits_are_batched_one_operation_per_document(plan):
    assert plan.operations == 3
    assert len(plan.edits) == 13, "thirteen edits still cost three operations, not thirteen"


def test_every_edit_carries_the_cell_it_came_from(plan):
    assert all(e.citation.strip() for e in plan.edits)


def test_the_instruction_forbids_collateral_change(plan):
    text = next(e for e in plan.edits if e.field_id == "ocf").instruction()
    assert "Change only that value" in text
    assert "Do not add or remove table rows" in text
    assert "Leave all legal wording exactly as it is" in text


def test_sample_mode_limits_the_work(fieldmap):
    views = read_set(BASELINE, fieldmap)
    small = build_plan(views, read_figures(DATA), fieldmap, sample=2)
    assert len(small.edits) < 13


# --- the guards ------------------------------------------------------------------


def test_untouched_legal_wording_is_byte_identical(fieldmap):
    before = read_document("prospectus", BASELINE / "prospectus.docx")
    after = read_document("prospectus", BASELINE / "prospectus.docx")
    result = check_protected_wording(before, after, fieldmap)
    assert result.ok
    assert len(result.passed) == 3


def test_a_reworded_protected_paragraph_fails(fieldmap, tmp_path):
    before = read_document("kid", BASELINE / "kid.docx")
    after = read_document("kid", BASELINE / "kid.docx")
    target = "This product does not include any protection"
    after.paragraphs = [
        (p + " Additionally, capital may be at risk.") if p.startswith(target) else p
        for p in after.paragraphs
    ]
    result = check_protected_wording(before, after, fieldmap)
    assert not result.ok
    assert any("protected wording changed" in f for f in result.failures)


def test_a_table_gaining_a_row_is_a_reflow_failure(fieldmap):
    before = read_document("factsheet", BASELINE / "factsheet.docx")
    after = read_document("factsheet", BASELINE / "factsheet.docx")
    after.tables["holdings"].rows.append(["6", "Extra Holding", "2.8%"])
    result = check_tables_did_not_reflow(before, after, fieldmap)
    assert not result.ok
    assert any("reflows the page" in f for f in result.failures)


def test_an_unrequested_paragraph_change_is_caught(fieldmap):
    before = read_document("prospectus", BASELINE / "prospectus.docx")
    after = read_document("prospectus", BASELINE / "prospectus.docx")
    after.paragraphs = [*after.paragraphs, "The Manager has also waived all fees indefinitely."]
    result = check_only_intended_values_moved(before, after, {"0.79%"})
    assert not result.ok
    assert any("no edit asked for" in f for f in result.failures)


# --- the client ------------------------------------------------------------------


def _client(handler, **kwargs) -> SuperDocsClient:
    return SuperDocsClient("test-key", "https://api.test", transport=httpx.MockTransport(handler), **kwargs)


def test_edits_always_request_human_approval():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"job_id": "j1", "session_id": "s1", "status": "queued"})

    with _client(handler) as client:
        client.request_edit("s1", "change the OCF")

    assert seen["approval_mode"] == "ask_every_time", "nothing may auto-commit"
    assert seen["async_mode"] is True


def test_the_operation_budget_stops_before_it_overspends():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "j", "session_id": "s", "status": "queued"})

    with _client(handler, max_operations=2) as client:
        client.request_edit("s", "one")
        client.request_edit("s", "two")
        with pytest.raises(OperationBudgetExceeded) as excinfo:
            client.request_edit("s", "three")

    assert "budget of 2" in str(excinfo.value)
    assert "Raise FUND_UPDATE_MAX_OPERATIONS" in str(excinfo.value)


def test_exports_do_not_count_as_operations():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"file_base64": ""})

    with _client(handler) as client:
        client.export("s", "docx")
        client.export("s", "pdf")
        assert client.usage.operations == 0, "exports never cost operations"
        assert client.usage.requests == 2


def test_an_api_error_names_the_endpoint_and_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="session_id is required")

    with _client(handler) as client, pytest.raises(Exception) as excinfo:
        client.start_session()
    assert "/v1/sessions/init" in str(excinfo.value)
    assert "session_id is required" in str(excinfo.value)


def test_a_missing_key_fails_with_the_fix_in_the_message():
    with pytest.raises(Exception) as excinfo:
        SuperDocsClient("", "https://api.test")
    assert "SUPERDOCS_API_KEY" in str(excinfo.value)


def test_pending_changes_are_parsed_off_the_job(monkeypatch):
    payload = {
        "status": "awaiting_approval",
        "pending_changes": [
            {"change_id": "a", "content": json.dumps({"summary": "OCF"})},
            {"change_id": "b", "content": {"summary": "NAV"}},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        state = client.get_job("j1")

    assert state.awaiting_review
    assert [c.change_id for c in state.changes] == ["a", "b"]
    assert [c.content["summary"] for c in state.changes] == ["OCF", "NAV"]


def test_batch_decisions_send_one_entry_per_change():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        client.decide("s1", "j1", [("a", True, ""), ("b", False, "figure disputed")])

    assert len(sent["changes"]) == 2
    assert sent["changes"][1] == {"change_id": "b", "approved": False, "feedback": "figure disputed"}


def test_export_saves_a_base64_payload(tmp_path):
    import base64

    target = tmp_path / "out.docx"
    saved = save_export({"file_base64": base64.b64encode(b"PK\x03\x04docx").decode()}, target)
    assert saved == target
    assert target.read_bytes().startswith(b"PK")


def test_figures_go_up_as_markdown_because_the_api_rejects_csv(tmp_path):
    """415 UNSUPPORTED_FILE_TYPE on .csv, found on the first live run."""
    dest = write_reference_markdown(read_figures(DATA), tmp_path / "approved-figures.md")

    assert dest.suffix == ".md"
    body = dest.read_text(encoding="utf-8")
    assert "| ocf | 0.79% | 2025 expense ledger | AR-2025 Charges B14 |" in body
    assert "compute nothing" in body


def test_pending_changes_are_found_under_metadata_where_the_api_puts_them():
    """The live API nests them in metadata and sends result: null while running."""
    payload = {
        "status": "awaiting_approval",
        "result": None,
        "progress": 90,
        "metadata": {
            "pending_changes": [{"change_id": "m1", "content": {"summary": "OCF"}}],
            "intermediate_responses": [{"content": "locating the field", "type": "user_facing"}],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        state = client.get_job("j9")

    assert [c.change_id for c in state.changes] == ["m1"]
    assert state.progress == 90
    assert state.notes == ["locating the field"]


def test_export_returns_raw_bytes_not_json(tmp_path):
    """The live endpoint returns the .docx itself; decoding it as text corrupts it."""
    payload = b"PK" + bytes([3, 4]) + b"real docx bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

    target = tmp_path / "factsheet.docx"
    with _client(handler) as client:
        body = client.export("s1", "docx")
        assert client.usage.operations == 0

    assert save_export(body, target) == target
    assert target.read_bytes() == payload


def test_an_unchanged_export_fails_instead_of_passing_vacuously(fieldmap):
    """The first live run exported before the approvals applied. Every other guard passed on
    the untouched document, because nothing had moved."""
    untouched = read_document("kid", BASELINE / "kid.docx")

    result = check_intended_values_landed(untouched, {"0.79%", "5 out of 7"})

    assert not result.ok
    assert "2 of 2 requested value(s) are not in the export" in result.failures[0]


def test_the_landed_guard_passes_when_the_values_are_there(fieldmap):
    doc = read_document("kid", BASELINE / "kid.docx")
    result = check_intended_values_landed(doc, {"0.82%"})
    assert result.ok
    assert "all 1 requested value(s) present" in result.passed[0]


def test_a_composite_holding_counts_as_landed_when_its_parts_are_in_their_cells():
    """`Aurora Semiconductor | 5.2%` is a name cell and a weight cell, never one string."""
    from fund_update.domain.documents import DocumentView, TableView

    view = DocumentView(
        name="factsheet",
        path=BASELINE / "factsheet.docx",
        paragraphs=[],
        tables={"holdings": TableView(name="holdings", headers=["#", "Holding", "Weight"], rows=[["1", "Aurora Semiconductor", "5.2%"]])},
    )

    assert check_intended_values_landed(view, {"Aurora Semiconductor | 5.2%"}).ok
    assert not check_intended_values_landed(view, {"Aurora Semiconductor | 9.9%"}).ok
