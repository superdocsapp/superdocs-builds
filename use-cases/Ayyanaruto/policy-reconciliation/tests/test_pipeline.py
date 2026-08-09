"""Tests run without a live SuperDocs key."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import pipeline
import report
from superdocs_client import (
    QuotaExhausted,
    check_usage,
    is_safety_refusal,
    parse_json_from_reply,
    parse_pending_changes,
    reply_text,
)


def test_parse_pending_changes_double_encoded_json():
    inner = [
        {
            "change_id": "ch_1",
            "operation": "edit",
            "chunk_id": "chunk-aaa",
            "old_html": "<p>old</p>",
            "new_html": "<p>new</p>",
            "ai_explanation": "Unify receipt threshold",
        }
    ]
    encoded = json.dumps(json.dumps(inner))
    parsed = parse_pending_changes(encoded)
    assert isinstance(parsed, list)
    assert parsed[0]["change_id"] == "ch_1"
    assert parsed[0]["new_html"] == "<p>new</p>"


def test_parse_pending_changes_already_a_list():
    raw = [{"change_id": "ch_2", "operation": "create"}]
    assert parse_pending_changes(raw)[0]["change_id"] == "ch_2"


def test_parse_json_from_reply_fenced_and_double_encoded():
    payload = {"obligations": [{"id": "obl_a_001", "estate": "a", "text": "Give 3 days notice."}]}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_json_from_reply(fenced)["obligations"][0]["id"] == "obl_a_001"
    double = json.dumps(json.dumps(payload))
    assert parse_json_from_reply(json.loads(double))["obligations"][0]["id"] == "obl_a_001"


def test_parse_json_from_reply_empty_or_prose_returns_none():
    assert parse_json_from_reply("") is None
    assert parse_json_from_reply(None) is None
    assert parse_json_from_reply("   ") is None
    assert parse_json_from_reply("I'll read the policy and list the obligations.") is None


def test_reply_text_reads_common_job_shapes():
    assert reply_text({"result": {"response": '{"ok": true}'}}) == '{"ok": true}'
    assert reply_text({"result": {"message": "hello"}}) == "hello"
    assert reply_text({"metadata": {"intermediate_responses": [{"text": '{"a":1}'}]}}) == '{"a":1}'
    assert reply_text({"result": {}}) == ""


def test_is_safety_refusal():
    assert is_safety_refusal(
        "I found what I needed, but I wasn't able to put together a safe reply to share here. "
        "Could you rephrase that, or tell me a bit more about what you're trying to do with your document?"
    )
    assert not is_safety_refusal('{"policies": []}')


def test_parse_extract_reply_stamps_estate_and_topic():
    payload = {
        "obligations": [
            {"text": "Employees may work fully remotely from any location in the United States.", "topic": "Work location"},
            {"text": "There are no required in-office days.", "topic": "Office attendance"},
            {"text": "   ", "topic": "empty ignored"},
        ]
    }
    doc = {"estate": "a", "filename": "remote_work_policy.docx", "document_id": "doc_a_remote"}
    counters = {"a": 0, "b": 0}
    rows = pipeline.parse_extract_reply(payload, doc, counters)
    assert [r["id"] for r in rows] == ["obl_a_001", "obl_a_002"]
    assert all(r["estate"] == "a" for r in rows)
    assert all(r["document_filename"] == "remote_work_policy.docx" for r in rows)
    assert rows[0]["topic"] == "Work location"
    assert rows[1]["text"] == "There are no required in-office days."


def test_usage_hard_stop_below_threshold():
    with pytest.raises(QuotaExhausted):
        check_usage({"monthly_remaining": 5})
    check_usage({"monthly_remaining": 80})
    check_usage(None)


def test_conflict_from_opposite_obligations():
    obligations = [
        {
            "id": "obl_a_001",
            "estate": "a",
            "document_filename": "remote_work_policy.docx",
            "chunk_id": "c1",
            "text": "Employees may work fully remotely from any location in the United States.",
        },
        {
            "id": "obl_b_004",
            "estate": "b",
            "document_filename": "flexible_working.docx",
            "chunk_id": "c9",
            "text": "Employees must work from a company office on Tuesday, Wednesday, and Thursday.",
        },
    ]
    match_payload = {
        "conflicts": [
            {
                "id": "conflict_001",
                "obligation_a_id": "obl_a_001",
                "obligation_b_id": "obl_b_004",
                "reason": "Full WFH vs required office days",
                "policy_a_excerpt": "PARAPHRASE FROM SUPERDOCS MUST NOT BE USED",
                "policy_b_excerpt": "ALSO A PARAPHRASE",
            }
        ]
    }
    result = pipeline.detect_conflicts(obligations, match_payload)
    assert len(result["conflicts"]) == 1
    row = result["conflicts"][0]
    assert row["id"] == "conflict_001"
    assert row["policy_a_excerpt"] == obligations[0]["text"]
    assert row["policy_b_excerpt"] == obligations[1]["text"]
    assert "PARAPHRASE" not in row["policy_a_excerpt"]


def test_coverage_flags_gap_only_and_totals_reconcile():
    obligations = [
        {"id": "obl_a_001", "estate": "a", "document_filename": "code_of_conduct.docx", "text": "No confidential posts on social media."},
        {"id": "obl_a_002", "estate": "a", "document_filename": "code_of_conduct.docx", "text": "Gift limit is $25."},
        {"id": "obl_b_001", "estate": "b", "document_filename": "workplace_conduct.docx", "text": "Gift limit is $75."},
    ]
    match_payload = {
        "coverage": [
            {"obligation_id": "obl_a_002", "disposition": "mapped"},
            {"obligation_id": "obl_b_001", "disposition": "mapped"},
            # obl_a_001 deliberately omitted — must become gap-A-only
        ]
    }
    docs = [
        {"estate": "a", "filename": "code_of_conduct.docx"},
        {"estate": "b", "filename": "workplace_conduct.docx"},
    ]
    coverage = pipeline.build_coverage(obligations, match_payload, docs)
    by_id = {o["id"]: o["disposition"] for o in coverage["obligations"]}
    assert by_id["obl_a_001"] == "gap-A-only"
    assert by_id["obl_a_002"] == "mapped"
    assert by_id["obl_b_001"] == "mapped"
    totals = coverage["totals"]
    assert totals["documents_total"] == 2
    assert totals["obligations_total"] == 3
    assert totals["mapped"] + totals["gap_a_only"] + totals["gap_b_only"] == 3
    assert totals["gap_a_only"] == 1
    assert totals["mapped"] == 2


def test_decide_never_auto_merges_a_conflict():
    assert pipeline.decide({"recommendation": "merge", "conflict": True}) == "new"
    assert pipeline.decide({"recommendation": "keep_a"}) == "keep_a"
    assert pipeline.decide({"recommendation": "keep_b"}) == "keep_b"
    assert pipeline.decide({"recommendation": "merge"}) == "merge"
    assert pipeline.decide({"recommendation": "merge", "conflict": False}) == "merge"
    assert pipeline.decide({"recommendation": "new"}) == "new"
    assert pipeline.decide({"recommendation": "unknown"}) == "new"
    assert pipeline.decide({}) == "new"


def test_extract_skips_file_after_non_json_retry():
    docs = [
        {"estate": "a", "filename": "expense_policy.docx", "session_id": "sess", "document_id": "doc_1"},
        {"estate": "a", "filename": "pto_policy.docx", "session_id": "sess", "document_id": "doc_2"},
    ]
    jobs = [
        {"job_id": "j1", "result": {"response": ""}},
        {"job_id": "j2", "result": {"response": "I'll extract the obligations next."}},
        {
            "job_id": "j3",
            "result": {"response": json.dumps({"obligations": [{"text": "PTO accrues at 15 days.", "topic": "PTO"}]})},
        },
    ]

    with patch.object(pipeline.client, "chat_async", side_effect=jobs):
        cleaned, job_ids = pipeline.extract(docs)

    assert [o["text"] for o in cleaned] == ["PTO accrues at 15 days."]
    assert job_ids == ["j1", "j2", "j3"]


def test_match_errors_after_superdocs_safety_refusal():
    docs = [
        {"estate": "a", "filename": "expense_policy.docx", "session_id": "sess", "document_id": "doc_a"},
        {"estate": "b", "filename": "reimbursement_guidelines.docx", "session_id": "sess", "document_id": "doc_b"},
    ]
    obligations = [
        {"id": "obl_a_001", "estate": "a", "document_filename": "expense_policy.docx", "topic": "Receipts"},
        {"id": "obl_b_001", "estate": "b", "document_filename": "reimbursement_guidelines.docx", "topic": "Receipts"},
    ]
    refusal = {
        "job_id": "j-ref",
        "result": {
            "response": (
                "I found what I needed, but I wasn't able to put together a safe reply to share here. "
                "Could you rephrase that?"
            )
        },
    }

    with patch.object(pipeline.client, "chat_async", return_value=refusal):
        with pytest.raises(pipeline.client.SuperDocsError, match="safety filter"):
            pipeline.match(docs, obligations, "sess")


def test_ingest_uses_one_compare_session(tmp_path):
    estate_a = tmp_path / "a"
    estate_b = tmp_path / "b"
    estate_a.mkdir()
    estate_b.mkdir()
    (estate_a / "pto_policy.docx").write_bytes(b"PK-a")
    (estate_b / "time_off_policy.docx").write_bytes(b"PK-b")
    uploads = []

    def fake_upload(path, session_id, open_mode="replace"):
        uploads.append((Path(path).name, session_id, open_mode))
        return {"document_id": f"doc_{Path(path).stem}", "chunks_count": 3}

    with patch.object(pipeline.client, "upload", side_effect=fake_upload):
        docs, session_id = pipeline.ingest(estate_a, estate_b, "run_1")

    assert session_id == "pr_run_1_compare"
    assert all(d["session_id"] == session_id for d in docs)
    assert [u[2] for u in uploads] == ["replace", "new_focused"]
    assert {u[1] for u in uploads} == {session_id}


def test_apply_partial_decisions_reject_does_not_block_rest(tmp_path):
    src_a = tmp_path / "pto_policy.docx"
    src_b = tmp_path / "time_off_policy.docx"
    src_a.write_bytes(b"PK-fake-a")
    src_b.write_bytes(b"PK-fake-b")
    output_dir = tmp_path / "run_1"
    output_dir.mkdir()
    (output_dir / "mapping.json").write_text(
        json.dumps(
            {
                "policies": [
                    {
                        "id": "map_keep",
                        "recommendation": "keep_a",
                        "doc_a": {"path": str(src_a), "filename": "pto_policy.docx"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    run_manifest = {
        "run_id": "run_1",
        "docs": [
            {"estate": "a", "filename": "pto_policy.docx", "path": str(src_a)},
            {"estate": "b", "filename": "time_off_policy.docx", "path": str(src_b)},
        ],
        "merges": [
            {
                "id": "merge_001",
                "session_id": "sess-merge",
                "job_id": "job-ok",
                "title": "Expense policy",
                "pending_changes": [{"change_id": "ch_1", "operation": "edit"}],
            },
            {
                "id": "merge_002",
                "session_id": "sess-merge-2",
                "job_id": "job-reject",
                "title": "Conduct",
                "pending_changes": [{"change_id": "ch_2", "operation": "edit"}],
            },
        ],
        "mapping": {
            "policies": [
                {
                    "id": "map_keep",
                    "recommendation": "keep_a",
                    "doc_a": {"path": str(src_a), "filename": "pto_policy.docx"},
                }
            ]
        },
    }
    decisions = {
        "run_id": "run_1",
        "conflicts": [
            {
                "id": "conflict_001",
                "decision": "keep_b",
                "document_b": "time_off_policy.docx",
                "policy_a_excerpt": "3 business days notice",
                "policy_b_excerpt": "30 days notice",
            },
            {"id": "conflict_002", "decision": "pending"},
        ],
        "merges": [
            {"id": "merge_001", "decision": "approve"},
            {"id": "merge_002", "decision": "reject", "reviewer_notes": "Too aggressive"},
        ],
    }

    def fake_approve(session_id, job_id, approved, change_id=None, changes=None, feedback=None):
        if job_id == "job-ok":
            assert approved is True
            return {"ok": True}
        if job_id == "job-reject":
            assert approved is False
            return {"ok": True}
        raise AssertionError(f"unexpected job {job_id}")

    with patch.object(pipeline.client, "approve", side_effect=fake_approve) as approve_mock, patch.object(
        pipeline.client,
        "poll_job",
        return_value={"status": "completed", "job_id": "job-ok"},
    ), patch.object(pipeline.client, "export_docx", side_effect=lambda dest, **kwargs: Path(dest).write_bytes(b"docx")):
        results = pipeline.apply_decisions(decisions, run_manifest, output_dir)

    by_id = {r["id"]: r for r in results}
    assert by_id["map_keep"]["status"] == "ok"
    assert by_id["conflict_001"]["status"] == "ok"
    assert by_id["conflict_002"]["status"] == "pending"
    assert by_id["merge_001"]["status"] == "ok"
    assert by_id["merge_002"]["status"] == "ok"
    assert by_id["merge_002"]["action"] == "reject"
    assert approve_mock.call_count == 2
    assert (output_dir / "final" / "keep_a_pto_policy.docx").is_file()
    assert (output_dir / "final" / "conflict_keep_b_time_off_policy.docx").is_file()
    assert (output_dir / "final" / "expense_policy.docx").is_file()


def test_apply_reject_does_not_abort_when_one_merge_errors(tmp_path):
    output_dir = tmp_path / "run_err"
    output_dir.mkdir()
    run_manifest = {
        "docs": [],
        "merges": [
            {
                "id": "merge_001",
                "session_id": "s1",
                "job_id": "j1",
                "title": "One",
                "pending_changes": [{"change_id": "ch_1"}],
            },
            {
                "id": "merge_002",
                "session_id": "s2",
                "job_id": "j2",
                "title": "Two",
                "pending_changes": [{"change_id": "ch_2"}],
            },
        ],
        "mapping": {"policies": []},
    }
    decisions = {
        "conflicts": [],
        "merges": [
            {"id": "merge_001", "decision": "approve"},
            {"id": "merge_002", "decision": "approve"},
        ],
    }

    def boom(session_id, job_id, approved, **kwargs):
        if job_id == "j1":
            raise RuntimeError("transient approve failure")
        return {"ok": True}

    with patch.object(pipeline.client, "approve", side_effect=boom), patch.object(
        pipeline.client, "poll_job", return_value={"status": "completed"}
    ), patch.object(pipeline.client, "export_docx", return_value=output_dir / "final" / "two.docx"):
        results = pipeline.apply_decisions(decisions, run_manifest, output_dir)

    by_id = {r["id"]: r for r in results}
    assert by_id["merge_001"]["status"] == "error"
    assert by_id["merge_002"]["status"] == "ok"


def test_report_seeds_pending_decisions(tmp_path):
    mapping = {
        "policies": [
            {
                "id": "map_001",
                "title": "Remote work / Flexible working",
                "recommendation": "new",
                "evidence": "Full WFH vs three office days.",
                "doc_a": {"filename": "remote_work_policy.docx"},
                "doc_b": {"filename": "flexible_working.docx"},
            }
        ]
    }
    conflicts = {
        "conflicts": [
            {
                "id": "conflict_001",
                "policy_a_excerpt": "Employees may work fully remotely.",
                "policy_b_excerpt": "Employees must work from a company office Tuesday through Thursday.",
                "reason": "Opposite in-office requirements",
                "document_a": "remote_work_policy.docx",
                "document_b": "flexible_working.docx",
            }
        ]
    }
    coverage = {
        "totals": {
            "documents_total": 10,
            "obligations_total": 2,
            "mapped": 0,
            "gap_a_only": 1,
            "gap_b_only": 1,
        },
        "obligations": [
            {
                "id": "obl_a_009",
                "estate": "a",
                "document_filename": "code_of_conduct.docx",
                "text": "Employees must not post confidential company information on social media.",
                "disposition": "gap-A-only",
            },
            {
                "id": "obl_b_010",
                "estate": "b",
                "document_filename": "separation_policy.docx",
                "text": "Severance is 1 week of base pay per completed year of service.",
                "disposition": "gap-B-only",
            },
        ],
    }
    html_path = report.write_review_artifacts(
        tmp_path,
        "run_1",
        mapping,
        conflicts,
        coverage,
        merges=[{"id": "merge_001", "title": "Expenses", "proposed_draft_ref": "merged_drafts/expense_policy.html", "status": "awaiting_approval"}],
    )
    html = html_path.read_text(encoding="utf-8")
    assert "Fully remotely" in html or "fully remotely" in html
    assert "gap-A-only" in html or "A only" in html
    decisions = (tmp_path / "decisions.yaml").read_text(encoding="utf-8")
    assert "conflict_001" in decisions
    assert "pending" in decisions
    assert "merge_001" in decisions
