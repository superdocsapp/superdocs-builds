"""The card's own bar: 'no cross-contamination — lead A's details
provably never appear in lead B's document; blank note fields degrade
to honest generic sections, never invented specifics; the batch of N
inputs yields exactly N documents.'

Uses a FakeSuperDocsClient that records every instruction it was sent
and which session_id it was sent to, plus a simulated 'export' that
renders back exactly the substituted values (mirroring what a correctly
behaving SuperDocs edit would produce), so the verification step in
app/batch.py is exercised too, not bypassed. This lets the tests assert,
mechanically, that:
- every lead got its own session_id (no shared session to leak through)
- the instruction sent for lead X's document never contains a string
  that is unique to a *different* lead's record
- every one of the N leads produced exactly one output file
- the verification step finds no issues on a correctly "rendered" export
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.batch import run_batch
from app.superdocs_client import ChatResult, UploadInfo

FIXTURES = Path(__file__).parent.parent / "fixtures"


@dataclass
class FakeSuperDocsClient:
    """Every upload is recorded by the session_id the batch runner
    picked for that lead — mirroring the real client's behaviour of
    never reusing a session across leads."""

    uploads: list[str] = field(default_factory=list)  # session_ids, in order
    instructions_by_session: dict = field(default_factory=dict)

    def upload_document(self, content: bytes, filename: str, session_id: str) -> UploadInfo:
        self.uploads.append(session_id)
        return UploadInfo(session_id=session_id, chunks_count=1, version_id="v1")

    def edit_document(self, session_id: str, instruction: str, approval_mode=None) -> ChatResult:
        # Accumulates every turn sent to this session (batch.py now
        # sends several section-scoped turns per lead, not one big
        # instruction) so tests can still search the FULL set of
        # substitutions a lead received, not just the last turn.
        self.instructions_by_session[session_id] = (
            self.instructions_by_session.get(session_id, "") + instruction + "\n---\n"
        )
        return ChatResult(
            response_text="Filled.",
            updated_html="<div>ok</div>",
            changes_summary="filled sections",
        )

    def export_bytes(self, session_id: str, export_format: str, options=None) -> bytes:
        if export_format == "txt":
            # Simulates a correctly-behaving SuperDocs edit: renders back
            # exactly the substituted values from the instruction we
            # sent, so the batch's own verify_recap_text step (which
            # reads this "document") has something real to check against
            # rather than being silently skipped in tests.
            instruction = self.instructions_by_session.get(session_id, "")
            rendered = []
            for line in instruction.splitlines():
                if " -> " in line:
                    _, _, value = line.partition(" -> ")
                    rendered.append(value)
            return "\n".join(rendered).encode("utf-8")
        # Distinct, traceable "export content" per session for the final
        # delivery format, so a test could also check output files are
        # not byte-identical/duplicated.
        return f"EXPORTED CONTENT FOR {session_id}".encode()


@pytest.fixture
def fake_client() -> FakeSuperDocsClient:
    return FakeSuperDocsClient()


def test_batch_of_six_leads_produces_exactly_six_documents(tmp_path, fake_client):
    results = run_batch(
        FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client
    )
    assert len(results) == 6
    assert len(fake_client.uploads) == 6, "each lead must trigger its own fresh upload"
    assert len(set(fake_client.uploads)) == 6, "session_ids must not be reused across leads"

    output_files = list(tmp_path.glob("*.pdf"))
    assert len(output_files) == 6

    # And the verification step found nothing wrong on a correctly
    # "rendered" fake export — proves the batch's own honesty check
    # doesn't false-positive on well-formed output.
    assert all(not r.verification_issues for r in results), [
        (r.lead_id, r.verification_issues) for r in results
    ]


def test_every_lead_gets_its_own_session_never_shared(fake_client, tmp_path):
    run_batch(FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client)

    # 6 leads, 6 distinct session_ids, 6 distinct instruction payloads —
    # structurally impossible for two leads to share a document.
    assert len(fake_client.instructions_by_session) == 6


def test_no_cross_contamination_between_leads(fake_client, tmp_path):
    """The core assertion: search every OTHER lead's instruction text
    for any string that is unique to lead L006 (a distinctive company
    name and a distinctive detail from their notes). It must appear in
    exactly one instruction — L006's own — and nowhere else."""
    run_batch(FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client)

    distinctive_l006_strings = [
        "Cascade Materials Co.",
        "200-page supply agreement",
        "procurement team of 40",
    ]

    for marker in distinctive_l006_strings:
        matches = [
            session_id
            for session_id, text in fake_client.instructions_by_session.items()
            if marker in text
        ]
        assert len(matches) == 1, (
            f"'{marker}' (unique to lead L006) appeared in {len(matches)} "
            f"document instruction(s), expected exactly 1 — cross-contamination "
            f"detected in {matches}"
        )

    # And the reverse direction: L004's distinctive detail must not leak
    # into any other lead's instruction either.
    distinctive_l004_strings = ["Northstar Capital", "conflict-detection feature"]
    for marker in distinctive_l004_strings:
        matches = [
            session_id
            for session_id, text in fake_client.instructions_by_session.items()
            if marker in text
        ]
        assert len(matches) == 1, f"'{marker}' leaked into {matches}"


def test_blank_lead_never_receives_another_leads_specifics(fake_client, tmp_path):
    """L003 has almost no data. Its instruction must contain only its
    own name and the fixed honest-fallback strings — never a detail that
    belongs to any other lead in the same batch."""
    run_batch(FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client)

    l003_session_id = fake_client.uploads[2]  # third lead processed, in CSV order
    l003_instruction = fake_client.instructions_by_session[l003_session_id]

    assert "Sarah Kim" in l003_instruction
    other_leads_specifics = [
        "Meridian Logistics", "Blackwood Underwriting", "Northstar Capital",
        "Riverton Health Partners", "Cascade Materials Co.",
    ]
    for marker in other_leads_specifics:
        assert marker not in l003_instruction, (
            f"lead with almost no data still ended up with '{marker}' from "
            f"a different lead's record"
        )


def test_partial_batch_failure_still_produces_results_for_the_working_leads(fake_client, tmp_path):
    """One lead's upload fails; the other five must still produce
    documents — a single bad lead can't take down the whole batch."""

    real_upload = fake_client.upload_document
    call_count = {"n": 0}

    def flaky_upload(content, filename, session_id):
        call_count["n"] += 1
        if call_count["n"] == 4:  # fail on the 4th lead (L004)
            raise RuntimeError("simulated upstream failure")
        return real_upload(content, filename, session_id)

    fake_client.upload_document = flaky_upload

    results = run_batch(
        FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client
    )

    assert len(results) == 5
    ok_ids = {"L001", "L002", "L003", "L005", "L006"}
    assert {r.lead_id for r in results} == ok_ids


def test_max_leads_caps_the_batch_without_erroring(fake_client, tmp_path):
    results = run_batch(
        FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, fake_client, max_leads=2
    )
    assert len(results) == 2
    assert {r.lead_id for r in results} == {"L001", "L002"}


def test_targeted_cleanup_pass_only_re_requests_the_specific_leftover_fields(tmp_path):
    """Simulates the model getting 6 of 7 fields right on the first pass
    but missing discussion_section — the targeted cleanup pass built in
    app/batch.py must ask for exactly that field, not redo all 7, and
    must recover within the SAME attempt (no fresh-session retry
    needed) since the cleanup pass alone fixed it."""

    @dataclass
    class MissesDiscussionOnceClient(FakeSuperDocsClient):
        rendered_once_for: set = field(default_factory=set)

        def export_bytes(self, session_id, export_format, options=None):
            if export_format != "txt":
                return super().export_bytes(session_id, export_format, options)
            instruction = self.instructions_by_session.get(session_id, "")
            rendered = []
            for line in instruction.splitlines():
                if " -> " not in line:
                    continue
                token_part, _, value = line.partition(" -> ")
                if "discussion_section" in token_part and session_id not in self.rendered_once_for:
                    # Simulate: the FIRST time discussion_section is sent
                    # for this session, pretend the edit dropped it.
                    self.rendered_once_for.add(session_id)
                    continue
                rendered.append(value)
            return "\n".join(rendered).encode("utf-8")

    client = MissesDiscussionOnceClient()
    results = run_batch(
        FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, client, max_leads=1
    )

    result = results[0]
    assert result.attempts == 1, (
        "should recover within the same attempt via the cleanup pass — "
        "no fresh-session retry should have been needed"
    )
    assert result.verification_issues == []

    full_instruction = client.instructions_by_session[result.session_id]
    assert full_instruction.count("{{discussion_section}}") == 2, (
        "one normal turn + one targeted cleanup turn for the field that was missed"
    )
    assert full_instruction.count("{{lead_name}}") == 1, (
        "lead_name was correct on the first try — the cleanup pass must not re-touch it"
    )


def test_a_bad_export_that_drops_a_field_is_flagged_not_silently_shipped(tmp_path):
    """If SuperDocs' edit somehow failed to substitute correctly on
    every attempt, the verification step must catch it — proving the
    honesty check isn't just decorative."""

    @dataclass
    class BrokenExportClient(FakeSuperDocsClient):
        def export_bytes(self, session_id, export_format, options=None):
            if export_format == "txt":
                # Simulates a broken render: placeholder never resolved,
                # on every attempt (including the retry).
                return b"Lead: {{lead_name}}, {{lead_company}}\nWHAT WE DISCUSSED\n(missing)"
            return b"final bytes"

    client = BrokenExportClient()
    results = run_batch(FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, client)

    assert len(results) == 6
    assert all(r.verification_issues for r in results), "a broken render must be flagged, not silently shipped"
    assert any("unresolved placeholder" in issue for r in results for issue in r.verification_issues)
    assert all(r.attempts == 2 for r in results), "a persistent failure must exhaust both attempts"


def test_a_transient_failure_is_recovered_by_the_automatic_retry(tmp_path):
    """The bug found running live: one lead's first attempt can fail
    verification while a fresh second attempt succeeds. The retry must
    actually recover and ship the corrected document, not just log a
    warning and give up after one try."""

    @dataclass
    class FlakyThenGoodClient(FakeSuperDocsClient):
        def export_bytes(self, session_id, export_format, options=None):
            if export_format == "txt":
                if session_id.endswith("L001-priya_nair"):
                    # First attempt for L001: broken, nothing substituted.
                    return b"{{lead_name}} {{lead_company}} (nothing substituted)"
                # The retry session (name ends in -retry2) and every
                # other lead's first attempt: render correctly, as the
                # base FakeSuperDocsClient already does.
                return super().export_bytes(session_id, export_format, options)
            return super().export_bytes(session_id, export_format, options)

    client = FlakyThenGoodClient()
    results = run_batch(FIXTURES / "leads.csv", FIXTURES / "recap_template.txt", tmp_path, client)

    l001 = next(r for r in results if r.lead_id == "L001")
    assert l001.attempts == 2, "should have retried once after the first attempt failed verification"
    assert l001.verification_issues == [], "the retry should have produced a clean document"
    assert l001.session_id.endswith("-retry2")

    # Every other lead succeeded on the first attempt, untouched by L001's flakiness.
    others = [r for r in results if r.lead_id != "L001"]
    assert all(r.attempts == 1 for r in others)
    assert all(not r.verification_issues for r in others)
