"""EditRunner behavior tests against a scripted fake SuperDocs client:
happy path, revision loop, no-op completion, job failure, budget cap."""

import json

import pytest

from app.budget import BudgetExceeded
from app.pipeline import EditRunner, load_cases
from app.superdocs_client import SuperDocsError

from conftest import FakeSuperDocsClient, awaiting_job, completed_job


@pytest.fixture
def runner_factory(tree, tmp_path):
    def make(jobs=None, **kwargs):
        client = FakeSuperDocsClient(jobs=jobs,
                                     ledger_path=tree["data"] / "ledger_test.jsonl", **kwargs)
        return EditRunner(client=client), client
    return make


def _case(tree):
    return load_cases()[0]  # plan-01


class TestHappyPath:
    def test_four_call_sequence_and_artifacts(self, runner_factory, tree):
        runner, client = runner_factory([completed_job("EDITED")])
        rec = runner.run_case(_case(tree))

        assert rec["status"] == "completed"
        assert rec["pending_change_count"] == 0

        d = tree["edits"] / "plan-01"
        assert (d / "upload.json").exists()
        assert (d / "chat_start.json").exists()
        assert (d / "pending_changes.json").exists()
        assert (d / "job_final.json").exists()
        assert (d / "chat_result.json").exists()
        assert (d / "after.html").read_text(encoding="utf-8") == "EDITED"
        assert (d / "before.md").read_bytes() == b"FAKE-DOCX"
        assert (d / "after.md").read_bytes() == b"FAKE-DOCX"
        assert (d / "after.docx").read_bytes() == b"FAKE-DOCX"
        assert (d / "record.json").exists()

        # no approvals were needed, and the no-op path is recorded
        assert client.approved == []
        assert "no pending changes" in rec["steps"]["approve"]["note"]

    def test_usage_recorded_from_job_result(self, runner_factory, tree):
        runner, client = runner_factory([completed_job(usage={
            "was_billable": True, "ops_charged": 1, "monthly_remaining": 499})])
        runner.run_case(_case(tree))
        entries = json.loads(tree["data"].joinpath("ledger_test.jsonl").read_text(encoding="utf-8")
                             .splitlines()[0])
        assert entries["tag"] == "edit:plan-01"
        assert entries["was_billable"] is True
        assert entries["ops_charged"] == 1


class TestApprovalFlow:
    def test_revision_loop_two_rounds(self, runner_factory, tree):
        pending = [{"change_id": "c1"}, {"change_id": "c2"}]
        jobs = [
            awaiting_job(pending),
            awaiting_job([{"change_id": "c3"}]),   # AI revises after approval
            completed_job("FINAL"),
        ]
        runner, client = runner_factory(jobs)
        rec = runner.run_case(_case(tree))

        assert rec["status"] == "completed"
        assert rec["steps"]["approve"]["rounds"] == 2
        assert [c["change_id"] for c in client.approved[0]] == ["c1", "c2"]
        assert [c["change_id"] for c in client.approved[1]] == ["c3"]
        assert all(c["approved"] is True for batch in client.approved for c in batch)
        assert rec["final_status"] == "completed"

    def test_pending_changes_persisted(self, runner_factory, tree):
        pending = [{"change_id": "c1", "summary": "add Dave"}]
        runner, _ = runner_factory([awaiting_job(pending), completed_job()])
        runner.run_case(_case(tree))
        saved = json.loads((tree["edits"] / "plan-01" / "pending_changes.json")
                           .read_text(encoding="utf-8"))
        assert saved == pending

    def test_unapproved_then_no_pending_completes(self, runner_factory, tree):
        # one round, then the job completes without more pending changes
        runner, client = runner_factory([awaiting_job([{"change_id": "c1"}]), completed_job()])
        rec = runner.run_case(_case(tree))
        assert rec["status"] == "completed"
        assert rec["steps"]["approve"]["rounds"] == 1
        assert len(client.approved) == 1


class TestFailurePaths:
    def test_failed_job(self, runner_factory, tree):
        failed = {"status": "failed", "error": "model blew up"}
        runner, _ = runner_factory([failed])
        rec = runner.run_case(_case(tree))
        assert rec["status"] == "failed"
        assert "model blew up" in (rec.get("error") or "")
        saved = json.loads((tree["edits"] / "plan-01" / "job_final.json")
                           .read_text(encoding="utf-8"))
        assert saved["status"] == "failed"

    def test_upload_error_becomes_failed_run(self, runner_factory, tree):
        runner, _ = runner_factory(upload_error="upload refused")
        with pytest.raises(SuperDocsError):
            runner.run_case(_case(tree))

    def test_run_all_reports_failure(self, runner_factory, tree):
        runner, _ = runner_factory([{"status": "failed", "error": "x"}])
        summary = runner.run_all(["plan-01"])
        assert summary["results"][0]["status"] == "failed"
        assert len(summary["failed"]) == 1

    def test_run_all_only_runs_requested_ids(self, runner_factory, tree):
        runner, client = runner_factory([completed_job()])
        summary = runner.run_all(["meeting-01"])  # plan-01 must not run
        assert len(summary["results"]) == 1
        assert summary["results"][0]["case_id"] == "meeting-01"


class TestBudget:
    def test_budget_cap_blocks_start(self, runner_factory, tree):
        runner, _ = runner_factory(cap_ops=0)
        with pytest.raises(BudgetExceeded):
            runner.run_case(_case(tree))

    def test_run_all_breaks_on_budget_exceeded(self, runner_factory, tree):
        runner, _ = runner_factory(cap_ops=0)
        summary = runner.run_all(["plan-01", "meeting-01"])
        assert any("budget cap exceeded" in f["error"] for f in summary["failed"])

    def test_each_billable_edit_records_one_op(self, runner_factory, tree):
        runner, client = runner_factory([completed_job()])
        runner.run_case(_case(tree))
        assert client.budget.total_spend() == 1

    def test_no_ops_charged_for_uploads_exports(self, runner_factory, tree):
        # FakeClient records only through chat_async guard + job-result record;
        # uploads/exports never touch the ledger
        runner, client = runner_factory([completed_job(usage={
            "was_billable": False, "ops_charged": 0})])
        runner.run_case(_case(tree))
        entries = client.budget.load_ledger()
        assert sum(int(e["ops_charged"]) for e in entries) == 0


class TestCaseValidation:
    def test_bad_case_id_rejected(self, tree):
        from app.pipeline import CASE_ID_RE
        assert not CASE_ID_RE.match("plan 01")
        assert not CASE_ID_RE.match("plan/01")
        assert CASE_ID_RE.match("plan-01_2")

    def test_unknown_case_id_not_in_instructions(self, runner_factory, tree):
        runner, _ = runner_factory()
        summary = runner.run_all(["does-not-exist"])
        assert summary["results"] == []