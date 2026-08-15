import json

import pytest

from payment_plan_agreement.models import ReviewDecision
from payment_plan_agreement.superdocs import EditJob, FakeSuperDocsClient, HttpSuperDocsClient, SuperDocsExportFailed, SuperDocsMalformedProposal, SuperDocsTimeout, SuperDocsUnauthorized, parse_proposal, poll_job
from payment_plan_agreement.workflow import AgreementWorkflow, Lifecycle


def test_double_json_proposal_parse():
    payload = {"change_id":"c1","operation":"edit","chunk_id":"x","old_html":"a","new_html":"b"}
    assert parse_proposal(json.dumps(json.dumps(payload))).change_id == "c1"
    with pytest.raises(SuperDocsMalformedProposal): parse_proposal("not json")


def test_fake_end_to_end_requires_item_decision_and_exports_docx(request_factory):
    workflow = AgreementWorkflow(FakeSuperDocsClient()); run = workflow.start(request_factory())
    assert run.state == Lifecycle.AWAITING_HUMAN
    with pytest.raises(ValueError): workflow.review(run, [])
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)])
    assert run.state == Lifecycle.FINAL_VERIFIED
    exported = workflow.export(run)
    assert exported.content.startswith(b"PK") and run.state == Lifecycle.EXPORTED


def test_rejection_preserves_document_and_can_finalize(request_factory):
    workflow = AgreementWorkflow(FakeSuperDocsClient()); run = workflow.start(request_factory())
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=False)])
    assert run.final_html == run.seed_html and run.verification.status == "pass"


def test_protected_mutation_blocks_finalize_and_export(request_factory):
    workflow = AgreementWorkflow(FakeSuperDocsClient(mode="protected_amount")); run = workflow.start(request_factory())
    # Defense in depth: even if a caller bypasses proposal classification, final verification blocks export.
    run.job = run.job.model_copy(update={"proposals": [run.job.proposals[0].model_copy(update={"blocked": False})]})
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)])
    assert run.state == Lifecycle.BLOCKED
    with pytest.raises(ValueError): workflow.export(run)


def test_protected_proposal_cannot_be_approved(request_factory):
    workflow = AgreementWorkflow(FakeSuperDocsClient(mode="protected_amount")); run = workflow.start(request_factory())
    assert run.job and run.job.proposals[0].blocked is True
    with pytest.raises(ValueError, match="cannot be approved"):
        workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)])


def test_polling_reaches_review_without_extra_sleep():
    class PollingClient:
        calls = 0
        def get_job(self, job_id):
            self.calls += 1
            return EditJob(job_id=job_id, session_id="session", status="awaiting_approval")
    client = PollingClient()
    job = poll_job(client, "job", terminal_statuses={"awaiting_approval"}, interval_seconds=0)
    assert job.status == "awaiting_approval" and client.calls == 1


def test_http_adapter_uses_current_approval_and_export_shapes():
    class RecordingClient(HttpSuperDocsClient):
        def __init__(self): self.calls = []
        def _request(self, method, path, body=None, binary=False):
            self.calls.append((method, path, body, binary))
            return b"PKdemo" if binary else {"status": "in_progress"}
    client = RecordingClient()
    client.approve("session", "job", [ReviewDecision(change_id="c1", approved=False, feedback="conflicts")])
    client.export(html="<h1>Agreement</h1>", filename="agreement.docx")
    assert client.calls[0][2] == {"job_id": "job", "approved": False, "changes": [{"change_id": "c1", "approved": False, "feedback": "conflicts"}]}
    assert client.calls[1][2]["options"]["filename"] == "agreement"


def test_http_adapter_accepts_null_pending_changes_while_processing():
    class ProcessingClient(HttpSuperDocsClient):
        def __init__(self): pass
        def _request(self, method, path, body=None, binary=False):
            return {"status": "in_progress", "session_id": "session", "progress": 25, "metadata": {"pending_changes": None}, "result": None}
    job = ProcessingClient().get_job("job")
    assert job.status == "in_progress" and job.progress == 25 and job.proposals == []


def test_workflow_returns_to_review_for_second_proposal_batch(request_factory):
    class MultiBatchClient(FakeSuperDocsClient):
        def __post_init__(self):
            super().__post_init__(); self.approvals = 0
        def approve(self, session_id, job_id, decisions):
            self.approvals += 1
            if self.approvals == 1:
                second = self.jobs[job_id].proposals[0].model_copy(update={"change_id": "change_2", "new_html": "Contact the Creditor as soon as practical"})
                job = self.jobs[job_id].model_copy(update={"status": "awaiting_approval", "proposals": [second]})
                self.jobs[job_id] = job
                return job
            return super().approve(session_id, job_id, decisions)
    workflow = AgreementWorkflow(MultiBatchClient()); run = workflow.start(request_factory())
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)], timeout_seconds=0.1)
    assert run.state == Lifecycle.AWAITING_HUMAN and run.job.proposals[0].change_id == "change_2"
    workflow.review(run, [ReviewDecision(change_id="change_2", approved=True)], timeout_seconds=0.1)
    assert run.state == Lifecycle.FINAL_VERIFIED and [item.change_id for item in run.decisions] == ["change_1", "change_2"]


def test_workflow_ignores_stale_same_batch_after_approval(request_factory):
    class ApprovalRaceClient(FakeSuperDocsClient):
        def __post_init__(self):
            super().__post_init__(); self.polls = 0
        def approve(self, session_id, job_id, decisions):
            return self.jobs[job_id]
        def get_job(self, job_id):
            self.polls += 1
            if self.polls == 1:
                return self.jobs[job_id]
            job = self.jobs[job_id].model_copy(update={"status": "completed", "document_html": next(iter(self.documents.values()))})
            self.jobs[job_id] = job
            return job
    workflow = AgreementWorkflow(ApprovalRaceClient()); run = workflow.start(request_factory())
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)], timeout_seconds=1, poll_interval_seconds=0)
    assert run.state == Lifecycle.FINAL_VERIFIED and workflow.client.polls == 2


def test_missing_key_fails_before_any_external_request(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(SuperDocsUnauthorized, match="no external request was made"):
        HttpSuperDocsClient()


def test_timeout_names_preserved_recovery_state():
    class NeverCompletes:
        def get_job(self, job_id):
            return EditJob(job_id=job_id, session_id="session", status="in_progress", progress=95)
    with pytest.raises(SuperDocsTimeout, match="work and job id are preserved"):
        poll_job(NeverCompletes(), "job", terminal_statuses={"completed"}, timeout_seconds=0)


def test_export_failure_preserves_verified_document(request_factory):
    workflow = AgreementWorkflow(FakeSuperDocsClient(mode="export_failure")); run = workflow.start(request_factory())
    workflow.review(run, [ReviewDecision(change_id="change_1", approved=True)])
    before = run.final_html
    with pytest.raises(SuperDocsExportFailed, match="verified final HTML is preserved"):
        workflow.export(run)
    assert run.state == Lifecycle.FINAL_VERIFIED and run.final_html == before
