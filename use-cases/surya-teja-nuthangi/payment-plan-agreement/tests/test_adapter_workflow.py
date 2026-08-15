import json

import pytest

from payment_plan_agreement.models import ReviewDecision
from payment_plan_agreement.superdocs import EditJob, FakeSuperDocsClient, HttpSuperDocsClient, SuperDocsMalformedProposal, parse_proposal, poll_job
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
