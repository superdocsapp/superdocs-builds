import pytest

from superdocs.client import OperationBudget, SuperDocsClient
from superdocs.errors import BudgetExceeded, NotConfigured


def make_client(replies, max_ops=5):
    calls = []

    def transport(method, path, body):
        calls.append({"method": method, "path": path, "body": body})
        return replies.pop(0) if replies else {}

    client = SuperDocsClient("sk_test_fixture", OperationBudget(max_ops), transport)
    return client, calls


def test_a_placeholder_key_is_refused_with_the_fix_named():
    with pytest.raises(NotConfigured, match="\\.env"):
        SuperDocsClient("sk_your_key_here", OperationBudget(5))


def test_upload_sends_file_base64_never_content_base64():
    client, calls = make_client([{}])
    client.upload_document("notice.md", "text", "session-1")
    body = calls[0]["body"]
    assert "file_base64" in body
    assert "content_base64" not in body


def test_deciding_changes_always_carries_top_level_approved_true():
    client, calls = make_client([{}])
    client.decide_changes(
        "session-1", "job-1", [{"change_id": "c1", "approved": False}]
    )
    assert calls[0]["body"]["approved"] is True
    assert calls[0]["body"]["job_id"] == "job-1"


def test_an_attachment_upload_carries_the_file_and_the_session():
    client, calls = make_client([{}])
    client.upload_attachment("02-support-letter.md", b"letter text", "session-1")
    body = calls[0]["body"]
    assert calls[0]["path"] == "/attachments/upload-base64"
    assert body["session_id"] == "session-1"
    assert "file_base64" in body


def test_spent_operations_are_counted_from_the_servers_usage_fields():
    client, _ = make_client(
        [{"usage": {"ops_charged": 2}}, {"usage": {"was_billable": True}}, {}]
    )
    client.send_edit_instruction("s", "edit", "core")
    client.send_edit_instruction("s", "edit", "core")
    client.verify_key()
    assert client.budget.spent == 3


def test_the_budget_stops_the_next_billable_call_not_the_current_one():
    client, calls = make_client([{"usage": {"ops_charged": 5}}])
    client.send_edit_instruction("s", "edit", "core")
    with pytest.raises(BudgetExceeded, match="MAX_OPS_PER_RUN"):
        client.send_edit_instruction("s", "edit again", "core")
    assert len(calls) == 1


def test_a_billable_call_that_reports_no_usage_still_costs_one_operation():
    # /chat/async bills but returns no usage block, so counting only what
    # the server reports would leave the cap permanently unreachable
    client, _ = make_client([{"job_id": "j1"}])
    client.send_edit_instruction("s", "edit", "core")
    assert client.budget.spent == 1


def test_a_reported_zero_charge_stays_zero_and_is_never_floored_to_one():
    client, _ = make_client(
        [{"response": "verdict", "usage": {"ops_charged": 0, "was_billable": False}}]
    )
    client.ask("s", "judge this", "core")
    assert client.budget.spent == 0


def test_a_free_endpoint_without_usage_is_never_floored():
    client, _ = make_client([{"total_ready": 1, "total_processing": 0}, {}, {}])
    client.attachment_status("s")
    client.get_job("j1")
    client.upload_document("skeleton.md", "text", "s")
    assert client.budget.spent == 0


def test_a_reported_charge_of_two_counts_two():
    client, _ = make_client([{"usage": {"ops_charged": 2}}])
    client.send_edit_instruction("s", "edit", "core")
    assert client.budget.spent == 2


def test_the_servers_own_remaining_count_is_kept_when_it_arrives():
    client, _ = make_client(
        [{"response": "verdict", "usage": {"ops_charged": 1, "monthly_remaining": 46}}]
    )
    client.ask("s", "judge this", "core")
    assert client.budget.remaining == 46


def test_an_active_promotion_is_the_remaining_count_not_the_monthly_plan():
    # a promotional grant is the bucket actually drawn down; reporting the
    # untouched monthly figure beside it would mislead
    client, _ = make_client(
        [
            {
                "response": "verdict",
                "usage": {
                    "ops_charged": 0,
                    "monthly_remaining": 500,
                    "promotions": [{"name": "grant", "ops_remaining": 9998}],
                },
            }
        ]
    )
    client.ask("s", "judge this", "core")
    assert client.budget.remaining == 9998


def test_a_budget_can_start_from_what_earlier_commands_of_the_run_spent():
    client, _ = make_client([{"usage": {"ops_charged": 1}}])
    client.budget.spent = 2
    client.send_edit_instruction("s", "edit", "core")
    assert client.budget.spent == 3


def test_free_calls_are_never_blocked_by_a_spent_budget():
    client, _ = make_client([{"usage": {"ops_charged": 5}}, {"sessions": []}])
    client.send_edit_instruction("s", "edit", "core")
    assert client.verify_key() == {"sessions": []}
