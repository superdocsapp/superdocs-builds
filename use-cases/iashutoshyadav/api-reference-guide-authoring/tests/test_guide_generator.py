from app.guide_generator import apply_guide_revision, generate_getting_started_guide, request_guide_revision
from app.superdocs_client import FakeSuperDocsClient


def test_generates_a_numbered_guide_from_a_feature_description():
    client = FakeSuperDocsClient()

    guide = generate_getting_started_guide(
        client,
        "Sign up for an account. Create an API key in Settings. Install the SDK with pip install widgets-sdk. "
        "Call client.create_widget to make your first widget.",
        session_id="guide-1",
    )

    assert "1." in guide
    assert "Sign up for an account" in guide
    assert "Call client.create_widget" in guide


def test_each_sentence_becomes_its_own_numbered_step():
    client = FakeSuperDocsClient()

    guide = generate_getting_started_guide(
        client, "Step one happens. Step two happens. Step three happens.", session_id="guide-2",
    )

    assert "1. Step one happens." in guide
    assert "2. Step two happens." in guide
    assert "3. Step three happens." in guide


def test_a_revision_request_proposes_a_real_change_and_pauses_for_approval():
    """Real gap found auditing this build against the round's own stated minimum contract (upload, chat,
    approve, export): approve_change/chat_with_approval were fully implemented in the client but never
    called anywhere in the app. This is the human-in-the-loop revision path that exercises them for real."""
    client = FakeSuperDocsClient()
    generate_getting_started_guide(client, "Step one happens.", session_id="guide-3")

    job = request_guide_revision(client, "guide-3", "Add a troubleshooting section")

    assert job.status == "awaiting_approval"
    assert len(job.pending_changes) == 1
    change = job.pending_changes[0]
    assert change.ai_explanation and "Add a troubleshooting section" in change.ai_explanation
    assert change.old_html != change.new_html
    assert "Add a troubleshooting section" in change.new_html


def test_approving_a_revision_applies_it_and_exports_the_result():
    client = FakeSuperDocsClient()
    generate_getting_started_guide(client, "Step one happens.", session_id="guide-4")
    job = request_guide_revision(client, "guide-4", "Add a troubleshooting section")
    change = job.pending_changes[0]

    result = apply_guide_revision(
        client, "guide-4", job.job_id, change.change_id, approved=True,
    )

    assert "Add a troubleshooting section" in result


def test_rejecting_a_revision_leaves_the_guide_unchanged():
    client = FakeSuperDocsClient()
    original = generate_getting_started_guide(client, "Step one happens.", session_id="guide-5")
    job = request_guide_revision(client, "guide-5", "Add a troubleshooting section")
    change = job.pending_changes[0]

    result = apply_guide_revision(
        client, "guide-5", job.job_id, change.change_id, approved=False, reason="not needed",
    )

    assert result == original
    assert "Add a troubleshooting section" not in result
