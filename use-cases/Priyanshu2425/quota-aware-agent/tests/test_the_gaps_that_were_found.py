"""The nine things this build claimed and did not do.

Each test here is named for the claim, not for the function, because each one
was a gap between what the README said and what the code did. They are kept in
one file so the next reader can see the class of mistake rather than nine
unrelated regressions: **every one of them is the agent believing a number, or
a state, that it had not actually established.**
"""

from __future__ import annotations

import base64
import socket
import urllib.error

import pytest

from quota_aware_agent import QuotaAwareAgent, Step, SuperDocsClient
from quota_aware_agent import mcp_server as m
from quota_aware_agent.budget import Change, estimate
from quota_aware_agent.client import (SuperDocsError, TransportFailure,
                                      provably_never_sent)
from quota_aware_agent.idempotency import OperationLedger, State, operation_key
from quota_aware_agent.policy import Policy, StopReason
from tests.fake import FakeSuperDocs

DOC = b"<h1>x</h1>"


def agent(fake, **kw):
    return QuotaAwareAgent(SuperDocsClient(fake, sleep=lambda s: None), **kw)


@pytest.fixture
def mcp_fake(monkeypatch):
    def _make(**kw):
        f = FakeSuperDocs(**kw)
        monkeypatch.setattr(m, "_client",
                            lambda: SuperDocsClient(f, sleep=lambda s: None))
        return f
    return _make


@pytest.fixture(autouse=True)
def _ledger_in_a_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "LEDGER_PATH", str(tmp_path / "operations.jsonl"))


# -- 1. the price of several small edits ------------------------------------

def test_each_step_is_its_own_request_so_each_one_costs_at_least_an_operation():
    """Four five-section edits are four requests, not twenty pooled sections.

    Pooled, they price as one operation and bill as four — so the agent reports
    "it fits", starts, and runs out partway through somebody's document. That is
    the failure this whole build exists to prevent, arriving through its own
    arithmetic.
    """
    small = [Change(f"s{i}", sections=5) for i in range(4)]
    assert estimate(small, batched=True) == 1     # one request, twenty sections
    assert estimate(small, batched=False) == 4    # four requests, one each
    assert QuotaAwareAgent.BATCHED is False


def test_the_plan_it_quotes_is_the_plan_it_can_afford_to_finish():
    """It must never finish a run in a state its own opening sentence ruled out."""
    fake = FakeSuperDocs(remaining=3, sections_per_edit=5)
    report = agent(fake, policy=Policy(reserve=1)).run(
        "sess", "f.html", DOC, [Step(f"s{i}", f"do {i}", 5) for i in range(4)])

    assert "would cost about 4 operation(s)" in report.lines[1]
    assert report.completed == ["s0", "s1"]
    assert report.deferred == ["s2", "s3"]
    # Named up front as deferred, not discovered at the reserve floor mid-run.
    assert report.stop_reason is StopReason.COMPLETED


# -- 2 & 3. a failure that may still have been billed -----------------------

def test_a_call_that_may_have_been_billed_is_never_marked_repeatable(tmp_path):
    """A read timeout means the request went out and the answer never came back.

    Marking it FAILED makes it repeatable, and repeating it is the double
    billing the ledger exists to prevent.
    """
    class TimesOut(FakeSuperDocs):
        def request(self, method, path, **kw):
            if path == "/v1/chat/async":
                raise TimeoutError("the read timed out")
            return super().request(method, path, **kw)

    path = tmp_path / "ops.jsonl"
    a = agent(TimesOut(remaining=50), policy=Policy(reserve=1),
              ledger=OperationLedger(path))
    with pytest.raises(TimeoutError):
        a.run("sess", "f.html", DOC, [Step("s0", "do thing", 5)])

    record = OperationLedger(path).get(operation_key("sess", "s0", "do thing", 5))
    assert record.state is State.IN_FLIGHT
    assert not record.repeatable


def test_a_call_that_provably_never_arrived_is_repeatable(tmp_path):
    """The other half of the same distinction. A refused connection was not
    billed, and refusing to retry it would strand work for no reason."""
    class Refused(FakeSuperDocs):
        def request(self, method, path, **kw):
            if path == "/v1/chat/async":
                raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))
            return super().request(method, path, **kw)

    path = tmp_path / "ops.jsonl"
    a = agent(Refused(remaining=50), policy=Policy(reserve=1),
              ledger=OperationLedger(path))
    with pytest.raises(urllib.error.URLError):
        a.run("sess", "f.html", DOC, [Step("s0", "do thing", 5)])

    record = OperationLedger(path).get(operation_key("sess", "s0", "do thing", 5))
    assert record.state is State.FAILED
    assert record.repeatable


def test_the_default_answer_about_a_failure_is_that_we_do_not_know():
    """Conservative on purpose: the cost of being wrong is not symmetric."""
    assert provably_never_sent(urllib.error.URLError(ConnectionRefusedError()))
    assert provably_never_sent(urllib.error.URLError(socket.gaierror()))
    assert provably_never_sent(SuperDocsError(422, {}))      # rejected, unbilled
    assert not provably_never_sent(SuperDocsError(502, {}))  # gateway; unknown
    assert not provably_never_sent(TimeoutError())
    assert not provably_never_sent(RuntimeError("something else"))
    assert provably_never_sent(TransportFailure("x", never_sent=True))


# -- 4. the free call the reserve is a promise about ------------------------

class _SaysExhaustedOnEveryResponse(FakeSuperDocs):
    """The allowance is gone before the run starts, and the platform says so on
    everything — including the calls that do not cost anything."""

    def request(self, method, path, **kw):
        r = super().request(method, path, **kw)
        r.body.setdefault("usage", {})["quota_exhausted"] = True
        return r


class _RunsOutMidRunAndSaysSoOnTheExportToo(FakeSuperDocs):
    """The sequence that actually happens: room at whoami, exhausted after the
    first edit, and the exhaustion still being reported on the free export."""

    def request(self, method, path, **kw):
        r = super().request(method, path, **kw)
        if path == "/v1/documents/export" and self._edits:
            r.body.setdefault("usage", {})["quota_exhausted"] = True
        return r


def test_an_exhausted_allowance_never_blocks_the_export_it_promised():
    """The reserve's whole argument is 'you always end up with a file'.

    Exports are free, so an exhausted allowance has no business refusing one —
    and a guarantee that breaks at the moment it is needed is not a guarantee
    but a sentence in a README.
    """
    fake = _RunsOutMidRunAndSaysSoOnTheExportToo(
        remaining=2, exhaust_after=1, sections_per_edit=25)
    report = agent(fake, policy=Policy(reserve=0)).run(
        "sess", "f.html", DOC, [Step("a", "first", 25), Step("b", "second", 25)])

    assert report.stop_reason is StopReason.QUOTA_EXHAUSTED
    assert ("POST", "/v1/documents/export") in fake.calls
    assert any("Exported the document" in l for l in report.lines)


def test_the_exhaustion_signal_reaches_the_planner_even_off_a_free_call():
    """whoami is free and is not refused by exhaustion — but what it reports
    still has to change what the agent does next, or the signal was cosmetic.
    Nothing is uploaded, so there is nothing to export and nothing to clean up."""
    fake = _SaysExhaustedOnEveryResponse(remaining=5, sections_per_edit=25)
    a = agent(fake, policy=Policy(reserve=0))
    a.read_allowance()
    plan = a.plan([Step("a", "first", 25)])

    assert plan.publish == []
    assert "the allowance is exhausted" in plan.rationale


# -- 5. the plan and the ledger --------------------------------------------

def test_a_plan_does_not_quote_a_price_for_work_already_paid_for(mcp_fake):
    fake = mcp_fake(remaining=5, sections_per_edit=25)
    work = [{"id": "figures", "instruction": "Fix the figures.", "sections": 25},
            {"id": "footer", "instruction": "Tidy the footer.", "sections": 25}]

    m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                            "document_html": "<p>x</p>", "steps": work})

    plan = m.dispatch("plan_work", {"steps": work, "session_id": "s1"})
    assert plan["already_applied_by_an_earlier_run"] == ["figures", "footer"]
    assert plan["will_run"] == []
    assert plan["full_request_costs"] == 0
    assert plan["priced_against_the_ledger"] is True


def test_a_plan_without_a_session_says_it_assumed_a_clean_slate(mcp_fake):
    mcp_fake(remaining=5)
    plan = m.dispatch("plan_work", {"steps": [
        {"id": "a", "instruction": "Fix the figures.", "sections": 25}]})
    assert plan["priced_against_the_ledger"] is False
    assert "assumes none of these steps has been run before" in plan["pricing_note"]


def test_a_rerun_of_finished_work_is_not_reported_as_not_fitting(mcp_fake):
    """'Nothing fits' would send a caller off to buy allowance it does not need."""
    fake = mcp_fake(remaining=5, sections_per_edit=25)
    work = [{"id": "figures", "instruction": "Fix the figures.", "sections": 25}]
    m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                            "document_html": "<p>x</p>", "steps": work})

    again = m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                                    "document_html": "<p>x</p>", "steps": work})
    assert again["stop_reason"] == StopReason.ALREADY_APPLIED.value
    assert again["already_applied_by_an_earlier_run"] == ["figures"]
    assert again["receipt"]["operations_charged"] == 0
    # It still walks away with the file.
    assert ("POST", "/v1/documents/export") in fake.calls


# -- 6. the state the surface could enter and not leave ---------------------

def test_a_started_and_unconfirmed_step_can_be_closed_out_by_a_person(mcp_fake):
    fake = mcp_fake(remaining=5, sections_per_edit=25)
    led = OperationLedger(m.LEDGER_PATH)
    key = operation_key("s1", "figures", "Fix the figures.", 25)
    led.begin(key, session_id="s1", step_id="figures")

    work = [{"id": "figures", "instruction": "Fix the figures.", "sections": 25}]
    stuck = m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                                    "document_html": "<p>x</p>", "steps": work})
    assert stuck["started_and_never_confirmed"] == ["figures"]
    assert stuck["completed"] == []

    told = m.dispatch("resolve_operation", {
        "session_id": "s1", "step_id": "figures",
        "instruction": "Fix the figures.", "sections": 25, "applied": False,
        "note": "opened the document; the edit is not there"})
    assert told["resolved"] is True

    after = m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                                    "document_html": "<p>x</p>", "steps": work})
    assert after["completed"] == ["figures"]


def test_resolving_something_that_needs_no_resolution_says_so_rather_than_lying(mcp_fake):
    mcp_fake(remaining=5)
    out = m.dispatch("resolve_operation", {
        "session_id": "s1", "step_id": "figures",
        "instruction": "Fix the figures.", "sections": 25, "applied": True})
    assert out["resolved"] is False
    assert "nothing to resolve" in out["explanation"]


# -- 7. refusing a partial run, from the surface ----------------------------

def test_refusing_a_partial_run_is_reachable_from_the_surface(mcp_fake):
    fake = mcp_fake(remaining=2, sections_per_edit=25)
    work = [{"id": "figures", "instruction": "Fix the figures.", "sections": 25,
             "severity": "critical"},
            {"id": "footer", "instruction": "Tidy the footer.", "sections": 25,
             "severity": "low"}]

    out = m.dispatch("run_work", {"session_id": "s1", "filename": "f.html",
                                  "document_html": "<p>x</p>", "steps": work,
                                  "when_it_does_not_fit": "refuse"})
    assert out["stop_reason"] == StopReason.REFUSED_PARTIAL.value
    assert out["completed"] == []
    assert ("POST", "/v1/documents/upload") not in fake.calls

    plan = m.dispatch("plan_work", {"steps": work, "when_it_does_not_fit": "refuse"})
    assert plan["will_run"] == []


def test_an_unknown_way_of_not_fitting_names_the_two_that_exist(mcp_fake):
    mcp_fake(remaining=5)
    with pytest.raises(ValueError, match="'degrade'"):
        m.dispatch("plan_work", {"steps": [], "when_it_does_not_fit": "explode"})


# -- 8. a caller who holds a real file --------------------------------------

def test_a_real_file_can_be_sent_as_bytes_not_only_as_html(mcp_fake):
    fake = mcp_fake(remaining=5, sections_per_edit=25)
    docx = b"PK\x03\x04 pretend this is a real docx"
    m.dispatch("run_work", {
        "session_id": "s1", "filename": "contract.docx",
        "document_base64": base64.b64encode(docx).decode(),
        "steps": [{"id": "a", "instruction": "Fix it.", "sections": 25}]})
    assert fake.uploaded == ["contract.docx"]


def test_two_documents_in_one_call_is_refused_rather_than_one_being_ignored(mcp_fake):
    mcp_fake(remaining=5)
    with pytest.raises(ValueError, match="not both"):
        m._document_bytes("<p>x</p>", base64.b64encode(b"x").decode())


def test_no_document_at_all_names_both_ways_to_give_one(mcp_fake):
    mcp_fake(remaining=5)
    with pytest.raises(ValueError, match="document_base64"):
        m._document_bytes("", "")


def test_bad_base64_is_named_as_bad_base64_not_as_a_failed_upload(mcp_fake):
    mcp_fake(remaining=5)
    with pytest.raises(ValueError, match="not valid base64"):
        m._document_bytes("", "this is not base64!!!")


# -- 9. the extension is what SuperDocs parses by ---------------------------

def test_a_filename_that_disagrees_with_its_bytes_is_refused_before_it_is_sent():
    """The live API chooses its parser from the extension alone.

    HTML uploaded as `report.docx` comes back `400 Invalid DOCX file: File is
    not a zip file` — a message that names neither the cause nor the fix, and
    arrives only after a round trip. Verified live 2026-08-20, which is also how
    this was found: the demo's own default filename was `contract.docx` holding
    HTML, so `--live` could never have worked.
    """
    from quota_aware_agent.client import check_upload_name

    with pytest.raises(ValueError, match="not a zip archive"):
        check_upload_name("report.docx", b"<h1>x</h1>")
    with pytest.raises(ValueError, match="do not begin with '%PDF'"):
        check_upload_name("report.pdf", b"<h1>x</h1>")
    with pytest.raises(ValueError, match="no file extension"):
        check_upload_name("report", b"<h1>x</h1>")

    # And the agreeing cases are not obstructed.
    check_upload_name("report.html", b"<h1>x</h1>")
    check_upload_name("report.docx", b"PK\x03\x04zip")
    check_upload_name("report.pdf", b"%PDF-1.7")


def test_the_mismatch_that_would_have_SUCCEEDED_is_refused_too():
    """`.txt` holding a .docx is accepted by the platform and parsed as literal
    text. A silent wrong answer is worse than a 400, so it is refused here."""
    from quota_aware_agent.client import check_upload_name

    with pytest.raises(ValueError, match="parsed as literal text"):
        check_upload_name("report.txt", b"PK\x03\x04zip")


def test_the_fake_refuses_the_same_upload_the_live_api_refuses():
    """A fake that accepts any filename is how this shipped unnoticed."""
    fake = FakeSuperDocs(remaining=50)
    r = fake.request("POST", "/v1/documents/upload",
                     files={"file": ("report.docx", b"<h1>x</h1>")},
                     data={"session_id": "s1"})
    assert r.status == 400
    assert "not a zip file" in r.body["detail"]
