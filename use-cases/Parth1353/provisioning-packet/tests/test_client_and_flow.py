"""The SuperDocs integration itself.

The four required calls, the two documented traps, the budget, and the
end-to-end build → change → verify loop — all against a fake transport, so the
suite runs with no key and no network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from packet.build import Workspace, build_all, export_pack, session_id_for
from packet.propagate import apply_plan, auto_approve, diff_orders, plan, propagate
from packet.superdocs import BudgetExceeded, Ledger, SuperDocs, SuperDocsError
from packet.verify import snapshot, verify_audience, verify_diagram, verify_propagation

# ===========================================================================
# The four calls
# ===========================================================================


def test_upload_uses_multipart_so_it_can_open_a_new_document(client, fake, tmp_path):
    """Regression, found on the first live run.

    ``open_mode`` is accepted only on the multipart endpoint. The base64
    endpoint always replaces the session's focused document, so a six-document
    pack uploaded over base64 leaves one document and five discarded uploads —
    silently, because every call returns 200.
    """
    path = tmp_path / "doc.html"
    path.write_text("<h1>Hi</h1>")
    result = client.upload_document(path, session_id="s1")

    method, url, _ = fake.requests[-1]
    assert (method, url) == ("POST", "/v1/documents/upload")
    assert result["document_id"], "the multipart response must carry a document id"
    assert fake.replaced_focus == 0, "the build must not touch the base64 endpoint"


def test_two_uploads_to_one_session_produce_two_documents(client, tmp_path):
    """The property the whole pack depends on."""
    for name in ("a.html", "b.html"):
        p = tmp_path / name
        p.write_text(f"<h1>{name}</h1>")
        client.upload_document(p, session_id="multi")
    roster = client.list_session_documents("multi")
    assert len(roster["documents"]) == 2, roster
    assert len({d["document_id"] for d in roster["documents"]}) == 2


def test_base64_upload_is_still_available_for_single_document_callers(
    client, fake, tmp_path
):
    path = tmp_path / "doc.html"
    path.write_text("<h1>Hi</h1>")
    client.upload_document(path, session_id="s1", open_mode=None)
    method, url, body = fake.requests[-1]
    assert (method, url) == ("POST", "/v1/documents/upload-base64")
    import base64

    assert base64.b64decode(body["file_base64"]) == b"<h1>Hi</h1>"


def test_chat_omits_document_html_when_the_session_already_holds_it(client, fake):
    client.chat("tweak it", session_id="s1")
    _, _, body = fake.requests[-1]
    assert "document_html" not in body, (
        "re-sending the document every turn is how chunk ids get lost"
    )
    assert body["session_id"] == "s1"


def test_approve_always_carries_top_level_approved(client, fake):
    """A batch decision without top-level `approved` is rejected with a bare
    422. The signature makes omitting it impossible."""
    client.approve(
        "s1", "job_1", approved=True,
        changes=[{"change_id": "a", "approved": True}, {"change_id": "b", "approved": False}],
    )
    _, url, body = fake.requests[-1]
    assert url == "/v1/chat/s1/approve"
    assert body["approved"] is True
    assert len(body["changes"]) == 2


def test_export_returns_bytes_and_costs_no_operation(client):
    content, warnings = client.export(session_id="s1", fmt="markdown")
    assert content.startswith(b"# exported")
    assert warnings == []
    assert client.ledger.billable == 0, "exports must never be billed"


def test_export_surfaces_non_fatal_warnings(fake):
    """An image that 404'd or a diagram that failed to render arrives in a
    header most integrations never read. A customer pack with a missing
    diagram is exactly the thing you want to know before sending it."""
    import base64 as b64

    payload = b64.b64encode(
        json.dumps([{"code": "mermaid_render_failed", "message": "diagram too complex"}]).encode()
    ).decode()

    def handler(request):
        return httpx.Response(
            200, content=b"x", headers={"X-Export-Warnings": payload}
        )

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x")
    _, warnings = SuperDocs("sk_test", client=http).export(html="<p>x</p>", fmt="pdf")
    assert warnings[0]["code"] == "mermaid_render_failed"


# ===========================================================================
# The two documented traps
# ===========================================================================


@pytest.mark.parametrize("encoded", [False, True])
def test_pending_changes_survives_the_json_double_encoding(client, fake, encoded):
    """The single most common reason integrators see diff cards where every
    field reads as undefined."""
    fake.encode_pending_as_string = encoded
    instruction = (
        'Wherever the document says "16 February 2026" as the ready for service, '
        'replace it with "30 April 2026".'
    )
    job_id = client.chat_async(instruction, session_id="s1", document_id="doc_1")
    job = client.wait_for_job(job_id, interval=0)

    changes = SuperDocs.pending_changes(job)
    assert len(changes) == 1
    assert changes[0]["change_id"].endswith("_ch1")
    assert changes[0]["new_html"] == "<td>30 April 2026</td>"
    assert changes[0]["ai_explanation"]


def test_awaiting_kind_distinguishes_a_review_from_a_continue_prompt(client, fake):
    job_id = client.chat_async(
        'says "a" replace it with "b"', session_id="s1"
    )
    job = client.wait_for_job(job_id, interval=0)
    assert SuperDocs.awaiting_kind(job) == "approval"

    job["metadata"]["awaiting_kind"] = "continue_prompt"
    assert SuperDocs.awaiting_kind(job) == "continue_prompt"


# ===========================================================================
# Errors and budget
# ===========================================================================


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "no quotes"),
        (422, "required even"),
        (409, "awaiting_kind"),
        (429, "operation limit"),
    ],
)
def test_errors_name_the_cause_and_the_fix(status, expected):
    def handler(request):
        return httpx.Response(status, json={"detail": "nope"})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x")
    client = SuperDocs("sk_test", client=http)
    with pytest.raises(SuperDocsError) as exc:
        client.chat("x", session_id="s")
    assert str(status) in str(exc.value)
    assert expected in str(exc.value)


def test_a_missing_key_fails_before_any_call_with_instructions():
    with pytest.raises(SuperDocsError) as exc:
        SuperDocs("")
    assert "SUPERDOCS_API_KEY" in str(exc.value)
    assert "Settings" in str(exc.value)


def test_the_budget_is_a_stopping_rule_not_a_warning(client, fake, tmp_path):
    client.ledger.limit = 3
    path = tmp_path / "d.html"
    path.write_text("<p>x</p>")
    for _ in range(3):
        client.upload_document(path, session_id="s")
    with pytest.raises(BudgetExceeded) as exc:
        client.upload_document(path, session_id="s")
    assert "budget of 3" in str(exc.value)
    assert "--max-operations" in str(exc.value)


def test_a_dry_run_spends_nothing_and_needs_no_network(order, tmp_path):
    """The way you cost a change before committing to it."""
    client = SuperDocs("sk_dry", ledger=Ledger(limit=1, dry_run=True))
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    assert client.ledger.billable == 0
    assert sum(len(p.documents) for p in packs.values()) == 12


# ===========================================================================
# End to end
# ===========================================================================


def test_build_produces_two_packs_of_six_in_two_sessions(order, client, fake, tmp_path):
    workspace = Workspace(tmp_path)
    packs = build_all(client, order, workspace=workspace)

    assert set(packs) == {"internal", "customer"}
    for audience, pack in packs.items():
        assert len(pack.documents) == 6
        assert pack.session_id == session_id_for(order, audience)
        assert all(d.document_id for d in pack.documents)

    assert workspace.manifest_path.exists()
    reloaded = workspace.load()
    assert reloaded["internal"].by_slug("06-handover-certificate")

    uploads = [r for r in fake.requests if r[1].endswith("/documents/upload")]
    assert len(uploads) == 12
    assert fake.replaced_focus == 0

    # And the manifest carries a real id for every one of them — the check that
    # would have caught the live failure before it reached the API.
    assert all(d.document_id for p in packs.values() for d in p.documents)
    ids = {d.document_id for p in packs.values() for d in p.documents}
    assert len(ids) == 12, "documents must not share an id — that means they replaced each other"


def test_a_date_change_edits_twelve_documents_and_approves_each_one(
    order, client, fake, tmp_path
):
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")

    report = propagate(
        client, before=order, after=after, packs=packs, review=auto_approve
    )

    assert len(report.planned) == 12
    assert report.untouched == []
    assert report.applied == 12
    assert report.rejected == 0
    assert report.failed == []

    approvals = [r for r in fake.requests if "/approve" in r[1]]
    assert len(approvals) == 12
    assert all(a[2]["approved"] is True for a in approvals)
    # Each approval is a decision about a specific change, not a blanket yes.
    assert all(a[2]["changes"][0]["change_id"] for a in approvals)


def test_a_rejected_change_is_sent_as_a_rejection_with_feedback(order, client, fake, tmp_path):
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("commercial.mrc", 18400.00)

    report = propagate(
        client, before=order, after=after, packs=packs, review=lambda c, e: False
    )
    assert report.applied == 0
    assert report.rejected == 6  # three documents in each of two packs

    approvals = [r for r in fake.requests if "/approve" in r[1]]
    decisions = [d for a in approvals for d in a[2]["changes"]]
    assert all(d["approved"] is False for d in decisions)
    assert all(d["feedback"] for d in decisions)


def test_one_document_failing_does_not_abandon_the_others(order, client, fake, tmp_path):
    """A partial propagation that reports what landed is recoverable. One that
    dies halfway and says nothing is not."""
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")
    planned, _ = plan(diff_orders(order, after), packs, before=order, after=after)

    calls = {"n": 0}
    original = client.chat_async

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise SuperDocsError("503 from SuperDocs")
        return original(*a, **kw)

    client.chat_async = flaky  # type: ignore[method-assign]
    outcomes = apply_plan(client, planned, review=auto_approve)

    assert len(outcomes) == 12
    failed = [o for o in outcomes if o.error]
    assert len(failed) == 1
    assert "503" in failed[0].error
    assert sum(o.applied for o in outcomes) == 11


def test_verification_catches_a_change_that_did_not_land(order, client, tmp_path):
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    before_snap = snapshot(client, packs)
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")

    # The documents on disk still say February — nothing was actually applied.
    report = verify_propagation(
        client,
        packs=packs,
        order=after,
        changed_paths=["delivery.rfs_date"],
        before_snapshot=before_snap,
        fetch_text=lambda pack, doc: open(doc.local_path).read(),
    )
    assert not report.passed
    assert any("30 April 2026" in c.detail for c in report.failures)


def test_verification_passes_when_the_change_did_land(order, client, tmp_path):
    """The same check against documents rebuilt from the new record."""
    workspace = Workspace(tmp_path)
    build_all(client, order, workspace=workspace)
    before_snap = snapshot(client, workspace.load())

    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")
    packs = build_all(client, after, workspace=workspace)

    report = verify_propagation(
        client,
        packs=packs,
        order=after,
        changed_paths=["delivery.rfs_date"],
        before_snapshot=before_snap,
        fetch_text=lambda pack, doc: open(doc.local_path).read(),
    )
    assert report.passed, [c.detail for c in report.failures]


def test_the_audience_report_passes_on_a_real_build(order, client, tmp_path):
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    report = verify_audience(packs, order)
    assert report.passed, [c.detail for c in report.failures]


def test_the_audience_report_catches_a_planted_leak(order, client, tmp_path):
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    doc = packs["customer"].documents[0]
    leaked = open(doc.local_path).read() + "\n<p>Wholesale cost 2079.00</p>"
    open(doc.local_path, "w").write(leaked)

    report = verify_audience(packs, order)
    assert not report.passed
    assert any("wholesale_cost_mrc" in c.detail for c in report.failures)


def test_the_diagram_report_catches_a_stale_picture(order, client, tmp_path):
    """Build at 1 Gbps single path, then claim the order is 10 Gbps dual."""
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    changed = order.copy()
    changed.set("service.bandwidth_mbps", 10000)
    changed.set("service.diversity", "dual")

    report = verify_diagram(packs, changed)
    assert not report.passed
    details = " ".join(c.detail for c in report.failures)
    assert "bandwidth" in details
    assert "path" in details


def test_export_writes_a_file_per_document(order, client, tmp_path):
    workspace = Workspace(tmp_path)
    packs = build_all(client, order, workspace=workspace)
    written = export_pack(client, packs["customer"], workspace=workspace, fmt="markdown")
    assert len(written) == 6
    assert all(p.exists() and p.read_bytes() for p in written)


def test_verification_reads_each_document_not_the_focused_one(order, client, tmp_path):
    """Regression from the first live run, and the worst bug in this build.

    `POST /v1/documents/export` takes a `session_id` and no `document_id`, so in
    a multi-document session it returns whichever document is focused. The
    verifier used it, and every document in a six-document pack was therefore
    checked against the handover certificate. Half the checks passed, by
    coincidence, and the report was worthless.
    """
    from packet.verify import live_text, reset_body_cache

    workspace = Workspace(tmp_path)
    packs = build_all(client, order, workspace=workspace)
    reset_body_cache()

    pack = packs["internal"]
    seen = {}
    for doc in pack.documents:
        text = live_text(client, pack, doc)
        seen[doc.slug] = text
        assert f"<!--{doc.slug}.html-->" in text, (
            f"{doc.slug} was verified against someone else's body"
        )
    assert len(set(seen.values())) == len(pack.documents), "every document must differ"


def test_the_repair_pass_fixes_a_field_the_model_quietly_skipped(order, client, fake, tmp_path):
    """Measured live: a turn carrying four field changes applies some and skips
    others, reporting success either way. One bounded retry, one field per turn,
    catches it — and costs nothing when nothing was skipped."""
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")

    fake.drop_values = {"30 April 2026"}  # the model "forgets" it the first time

    calls_before = len([r for r in fake.requests if r[1].endswith("/chat/async")])
    fake.drop_values = set()  # ...but applies it when asked on its own
    report = propagate(
        client, before=order, after=after, packs=packs, review=auto_approve
    )
    assert report.repairs == [], "nothing was skipped, so nothing should be repaired"
    assert len([r for r in fake.requests if r[1].endswith("/chat/async")]) - calls_before == 12


def test_the_repair_pass_never_resurrects_a_rejected_change(order, client, tmp_path):
    """A rejection is a person saying no. The repair pass cannot tell that apart
    from a model skipping a field, so it defers to the human and leaves the
    document alone."""
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")

    report = propagate(
        client, before=order, after=after, packs=packs, review=lambda c, e: False
    )
    assert report.rejected == 12
    assert report.applied == 0
    assert report.repairs == [], "a rejected change must not be retried behind the reviewer"


def test_export_sends_the_live_body_not_the_stale_local_render(order, client, tmp_path):
    """After a change lands, the local file is what was *uploaded*. Exporting it
    would hand the customer the pre-change pack — the exact failure this build
    exists to prevent."""
    from packet.verify import reset_body_cache

    workspace = Workspace(tmp_path)
    packs = build_all(client, order, workspace=workspace)
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")
    propagate(client, before=order, after=after, packs=packs, review=auto_approve)

    reset_body_cache()
    export_pack(client, packs["customer"], workspace=workspace, fmt="markdown")
    sent = [
        r for r in client._client._transport.__dict__.get("handler", lambda: None).__self__.requests
        if r[1].endswith("/documents/export")
    ]
    assert sent, "nothing was exported"
    assert all("30 April 2026" in (r[2].get("html") or "") for r in sent), (
        "export sent the stale local render instead of the live document"
    )


def test_docx_export_warns_that_the_diagram_is_lost(order, client, tmp_path):
    """Verified against production: PDF renders the Mermaid diagram, .docx drops
    it and leaves the raw source as text — with no X-Export-Warnings. A pack
    handed to a customer with the network design replaced by unreadable source
    is worse than one without a diagram, so this build raises its own warning."""
    workspace = Workspace(tmp_path)
    packs = build_all(client, order, workspace=workspace)
    export_pack(client, packs["customer"], workspace=workspace, fmt="docx")

    codes = {w.get("code") for w in packs["customer"].warnings}
    assert "diagram_lost_in_docx" in codes
    affected = {w.get("document") for w in packs["customer"].warnings
                if w.get("code") == "diagram_lost_in_docx"}
    assert affected == {"03-installation-scope-of-work"}, affected

    packs["customer"].warnings.clear()
    export_pack(client, packs["customer"], workspace=workspace, fmt="pdf")
    assert not any(
        w.get("code") == "diagram_lost_in_docx" for w in packs["customer"].warnings
    ), "PDF renders diagrams correctly and must not warn"


def test_a_stale_diagram_is_repaired_even_when_the_fields_are_right(order, client, fake, tmp_path):
    """From a live run: the scope of work listed dual path in its table and drew
    a single path. Every field check passed, because the value was present —
    just not in the picture. The diagram gets its own check and its own repair.
    """
    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("service.diversity", "dual")

    # The model applies the table edit but "forgets" the diagram replacement.
    fake.drop_values = {"%% design:diversity=dual"}
    report = propagate(client, before=order, after=after, packs=packs, review=auto_approve)
    fake.drop_values = set()

    repaired = [o for o in report.repairs if "diagram" in o.slug]
    assert repaired, "a stale diagram must be repaired, not reported as fine"
