"""The whole path: inspection in, verified export out.

This is the card's own bar — "a sample report covering at least four inspection systems, each
with a finding, a severity label, and a photo, and confirm the exported report groups
everything correctly by system" — asserted rather than demonstrated. It runs offline against
the deterministic fake, so anyone can check the claim without a key or a cost.
"""

from __future__ import annotations

import pytest

from inspection_report import sample
from inspection_report.domain import catalogue
from inspection_report.render import pipeline, report
from inspection_report.superdocs.base import SuperDocsError
from inspection_report.superdocs.fake import FakeSuperDocsClient
from inspection_report.templates import binding, docx_html
from inspection_report.verify import exports as verify_exports

TEMPLATE = "templates/buyer_summary.docx"
SYSTEM_NAMES = [s.name for s in catalogue.systems()]


def format_html(name: str = "buyer_summary") -> str:
    """A shipped format, converted the way SuperDocs converts it.

    Formats are Word documents now, so a test reads one the same way the application does
    when the service is unreachable: through the converter, not off disk as text.
    """
    from pathlib import Path

    return docx_html.from_path(Path(f"templates/{name}.docx"))


@pytest.fixture
def built() -> tuple[pipeline.PipelineResult, object]:
    inspection = sample.sample_inspection()
    result = pipeline.build(
        inspection,
        format_html(),
        sample.sample_photo_data(),
        FakeSuperDocsClient(),
        session_id="test-session",
        settle_s=0.0,
    )
    return result, inspection


class TestTheCardsBar:
    def test_the_sample_covers_at_least_four_systems_with_finding_severity_and_photo(self) -> None:
        inspection = sample.sample_inspection()
        covered = {f.system_key for f in inspection.findings}
        assert len(covered) >= 4
        for finding in inspection.findings:
            assert finding.severity_key, "every finding carries a severity label"
            assert finding.photos, "every finding carries photo evidence"
            assert finding.observation.strip()

    @pytest.mark.parametrize("fmt", ["pdf", "docx"])
    def test_the_exported_report_groups_everything_by_system(
        self, built: tuple[pipeline.PipelineResult, object], fmt: str
    ) -> None:
        result, inspection = built
        report_card = verify_exports.verify(
            data=result.exports[fmt].content,
            fmt=fmt,
            inspection=inspection,  # type: ignore[arg-type]
        )
        assert report_card.passed, report_card.render()

    @pytest.mark.parametrize("fmt", ["pdf", "docx"])
    def test_every_photograph_is_in_the_exported_file(
        self, built: tuple[pipeline.PipelineResult, object], fmt: str
    ) -> None:
        result, inspection = built
        expected = inspection.photo_count()  # type: ignore[attr-defined]
        data = result.exports[fmt].content
        count = (
            len(verify_exports.images_in_docx(data))
            if fmt == "docx"
            else verify_exports.images_in_pdf(data)
        )
        assert count == expected


class TestEveryShippedFormat:
    """Each format is exercised, not just the one the demo happens to default to.

    They differ on purpose: the repair-priority list shows no photograph in its worked
    example, so what the verifier holds it to is read from the format rather than assumed.
    """

    @pytest.mark.parametrize("name", ["buyer_summary", "full_technical", "repair_priority"])
    @pytest.mark.parametrize("fmt", ["pdf", "docx"])
    def test_it_renders_exports_and_groups_by_system(self, name: str, fmt: str) -> None:
        template = format_html(name)
        inspection = sample.sample_inspection()
        result = pipeline.build(
            inspection,
            template,
            sample.sample_photo_data(),
            FakeSuperDocsClient(),
            session_id=f"fmt-{name}",
            polish=False,
            settle_s=0.0,
        )
        card = verify_exports.verify(
            data=result.exports[fmt].content,
            fmt=fmt,
            inspection=inspection,
            expect_photos=binding.carries_photos(template, SYSTEM_NAMES),
        )
        assert card.passed, card.render()

    def test_a_format_whose_example_shows_no_photograph_carries_none(self) -> None:
        template = format_html("repair_priority")
        assert not binding.carries_photos(template, SYSTEM_NAMES)
        inspection = sample.sample_inspection()
        result = pipeline.build(
            inspection,
            template,
            sample.sample_photo_data(),
            FakeSuperDocsClient(),
            session_id="fmt-none",
            polish=False,
            settle_s=0.0,
        )
        assert verify_exports.images_in_docx(result.exports["docx"].content) == []

    def test_a_format_that_never_shows_a_finding_says_what_to_fix(self) -> None:
        """Without a worked example there is nothing to repeat per finding."""
        broken = "".join(f"<h1>{name}</h1><p>[findings]</p>" for name in SYSTEM_NAMES)
        with pytest.raises(binding.TemplateError) as exc:
            report.render(sample.sample_inspection(), broken)
        assert "never shows how a finding is recorded" in str(exc.value)

    def test_a_format_missing_a_system_names_the_one_it_lacks(self) -> None:
        """Every catalogue system needs a section: silence reads as "not inspected"."""
        missing = SYSTEM_NAMES[:-1]
        broken = "<p>[severity label]: [location]</p><p>[observation]</p>" + "".join(
            f"<h1>{name}</h1><p>[findings]</p>" for name in missing
        )
        with pytest.raises(binding.TemplateError) as exc:
            report.render(sample.sample_inspection(), broken)
        assert SYSTEM_NAMES[-1] in str(exc.value)

    def test_a_system_section_with_nowhere_to_put_findings_says_so(self) -> None:
        broken = "<p>[severity label]: [location]</p><p>[observation]</p>" + "".join(
            f"<h1>{name}</h1><p>text</p>" for name in SYSTEM_NAMES
        )
        with pytest.raises(binding.TemplateError) as exc:
            report.render(sample.sample_inspection(), broken)
        assert "[findings]" in str(exc.value)


class TestTheRailHoldsAllTheWayToTheFile:
    def test_certifying_rewrites_are_refused(
        self, built: tuple[pipeline.PipelineResult, object]
    ) -> None:
        result, _ = built
        assert result.rail_refusals >= 1, "the sample is chosen to provoke refusals"
        assert any(p.approved for p in result.proposals), "well-behaved rewrites still land"

    def test_a_refused_rewrite_leaves_the_inspectors_own_words_in_the_report(
        self, built: tuple[pipeline.PipelineResult, object]
    ) -> None:
        result, inspection = built
        refused = [p for p in result.proposals if p.refused_by_rail]
        assert refused
        text = verify_exports.text_of_docx(result.exports["docx"].content)
        for proposal in refused:
            bad = pipeline._text_of(proposal.diff.new_html)
            assert bad not in text, "a refused rewrite reached the exported document"
        # And the original survives: the GFCI note is the one the fake certifies about.
        gfci = next(f for f in inspection.findings if "GFCI" in f.observation)  # type: ignore[attr-defined]
        assert gfci.observation in text

    def test_no_photo_url_travels_inside_the_document(
        self, built: tuple[pipeline.PipelineResult, object]
    ) -> None:
        result, _ = built
        text = verify_exports.text_of_docx(result.exports["docx"].content)
        assert "superdocs-document-images" not in text


class TestDeterminism:
    def test_rendering_twice_gives_identical_bytes(self) -> None:
        """Structure comes from code, so the same inspection always renders the same."""
        template = format_html()
        a = report.render(sample.sample_inspection(), template)
        b = report.render(sample.sample_inspection(), template)
        assert a == b

    def test_findings_are_ordered_most_urgent_first_within_a_system(self) -> None:
        """The Electrical section holds a safety_concern and a monitor, in that order."""
        inspection = sample.sample_inspection()
        html = report.render(inspection, format_html())

        # Read the document as blocks rather than matching markup: a heading carries the
        # format's own runs, so `<h1>Electrical</h1>` is not what the HTML says, and the
        # finding shape is the firm's to change. Anchor on the heading *text* instead —
        # every system is also named in the "what was inspected" sentence, so the heading
        # is the only reliable boundary.
        blocks = binding.parse_blocks(html)
        start = next(i for i, b in enumerate(blocks) if b.is_heading and b.text == "Electrical")
        end = next((i for i in range(start + 1, len(blocks)) if blocks[i].is_heading), len(blocks))
        section = " ".join(b.text for b in blocks[start:end])

        prompt_at = section.find("Recommend prompt evaluation")
        monitor_at = section.find("Monitor")
        assert prompt_at >= 0, section[:400]
        assert monitor_at >= 0, section[:400]
        assert prompt_at < monitor_at


class TestIdempotentPhotoUploads:
    def test_the_same_photograph_is_never_uploaded_twice(self) -> None:
        """Uploads cost money, so identity is content and a re-run re-spends nothing."""
        inspection = sample.sample_inspection()
        client = FakeSuperDocsClient()
        photo_data = sample.sample_photo_data()

        first_up, first_reused = pipeline.upload_photos(inspection, photo_data, client)
        assert first_up == inspection.photo_count()
        assert first_reused == 0

        # A crash and re-run: the same photographs, already known by content hash.
        known = {p.sha256: p.remote_url for f in inspection.findings for p in f.photos}
        again = sample.sample_inspection()
        second_up, second_reused = pipeline.upload_photos(again, photo_data, client, known=known)
        assert second_up == 0, "a re-run paid to upload photographs again"
        assert second_reused == again.photo_count()


def test_a_system_with_no_findings_says_so_rather_than_going_missing() -> None:
    """Silence about a system reads as "not inspected". It has to say what it found."""
    inspection = sample.sample_inspection()
    inspection.findings = [f for f in inspection.findings if f.system_key == "roof"]
    html = report.render(inspection, format_html())
    for system in catalogue.systems():
        assert system.name in html
    assert report.NOTHING_OBSERVED in html


class TestAFinishedReportSurvivesLosingItsSession:
    """A report that is already signed off must stay exportable.

    The session is where the document lives on SuperDocs' side, and a session does not
    outlive everything: the process restarts, the service forgets it, someone exports the
    report again weeks later. None of that loses anything — the findings, the approved
    wording and the photograph URLs are all in our own record — so the document is rebuilt
    from there rather than the export failing on finished work.

    Found by using the interface: restarting the API left an exported inspection unable to
    export, with SuperDocs' own "no document loaded" message shown to the inspector.
    """

    def _finished(self) -> tuple[object, FakeSuperDocsClient]:
        inspection = sample.sample_inspection()
        client = FakeSuperDocsClient()
        pipeline.build(
            inspection,
            format_html(),
            sample.sample_photo_data(),
            client,
            session_id="recover-me",
            settle_s=0.0,
        )
        return inspection, client

    def test_the_export_rebuilds_and_still_verifies(self) -> None:
        inspection, client = self._finished()
        client.sessions.clear()  # the restart

        export, rebuilt = pipeline.export_recovering_session(
            client,
            inspection,  # type: ignore[arg-type]
            format_html(),
            session_id="recover-me",
            fmt="docx",
            filename="recovered",
            expected=["something that is no longer pending"],
            settle_s=0.0,
        )
        assert rebuilt is True
        card = verify_exports.verify(
            data=export.content,
            fmt="docx",
            inspection=inspection,  # type: ignore[arg-type]
        )
        assert card.passed, card.render()

    def test_the_approved_wording_is_still_in_the_rebuilt_file(self) -> None:
        """The rebuild renders from what was approved, not from the inspector's shorthand."""
        inspection, client = self._finished()
        approved = [f for f in inspection.findings if f.plain_language]  # type: ignore[attr-defined]
        assert approved, "the sample is chosen so some rewrites are approved"
        client.sessions.clear()

        export, _ = pipeline.export_recovering_session(
            client,
            inspection,  # type: ignore[arg-type]
            format_html(),
            session_id="recover-me",
            fmt="docx",
            filename="recovered",
            expected=[],
            settle_s=0.0,
        )
        text = verify_exports.text_of_docx(export.content)
        for finding in approved:
            assert finding.plain_language in text

    def test_a_live_session_is_not_rebuilt(self) -> None:
        """The recovery is for a lost session only; it must not fire on the normal path."""
        inspection, client = self._finished()
        _, rebuilt = pipeline.export_recovering_session(
            client,
            inspection,  # type: ignore[arg-type]
            format_html(),
            session_id="recover-me",
            fmt="docx",
            filename="normal",
            expected=[],
            settle_s=0.0,
        )
        assert rebuilt is False

    def test_an_unrelated_failure_is_not_swallowed(self) -> None:
        """Only "no document loaded" is recoverable. Everything else must still surface."""
        inspection, _ = self._finished()

        class Broken(FakeSuperDocsClient):
            def export(self, **kwargs: object) -> object:
                raise SuperDocsError("upstream is on fire")

        with pytest.raises(SuperDocsError) as exc:
            pipeline.export_recovering_session(
                Broken(),
                inspection,  # type: ignore[arg-type]
                format_html(),
                session_id="recover-me",
                fmt="docx",
                filename="boom",
                expected=[],
                settle_s=0.0,
            )
        assert "on fire" in str(exc.value)


class TestWhoseWordsTrippedTheRail:
    """The export separates a claim the system produced from one the inspector wrote.

    Found by using the interface: an inspector typing "valley flashing is safe … will last
    another 20 years" got a report marked `verified: fail`, one screen after being told their
    wording is kept exactly as written. Both halves matter — the promise to the inspector,
    and the fact that a failure nobody can resolve is a failure everybody learns to ignore,
    which is how a genuinely generated claim would slide past.
    """

    def _export(self, inspection: object) -> bytes:
        client = FakeSuperDocsClient()
        result = pipeline.build(
            inspection,  # type: ignore[arg-type]
            format_html(),
            sample.sample_photo_data(),
            client,
            session_id="whose-words",
            polish=False,
            settle_s=0.0,
        )
        return result.exports["docx"].content

    def test_the_inspectors_own_claim_is_reported_and_does_not_fail_the_export(self) -> None:
        inspection = sample.sample_inspection()
        inspection.findings = inspection.findings[:1]
        inspection.findings[
            0
        ].observation = "valley flashing is safe and will last another 20 years"
        card = verify_exports.verify(
            data=self._export(inspection),
            fmt="docx",
            inspection=inspection,
            expect_photos=False,
        )
        named = {c.name: c for c in card.checks}
        assert card.passed, card.render()
        attributed = named["the inspector's own wording carries claims (kept as written)"]
        assert "is safe" in attributed.detail
        assert named["no certification language the system produced"].passed

    def test_a_claim_the_inspector_did_not_write_still_fails(self) -> None:
        """The attribution must not become a hole. A rewrite is not the inspector's words."""
        inspection = sample.sample_inspection()
        inspection.findings = inspection.findings[:1]
        inspection.findings[0].observation = "flashing gap at chimney"
        # What an approved-but-bad rewrite would put in the document.
        inspection.findings[
            0
        ].plain_language = "The flashing is safe and fully compliant with current standards."
        card = verify_exports.verify(
            data=self._export(inspection),
            fmt="docx",
            inspection=inspection,
            expect_photos=False,
        )
        named = {c.name: c for c in card.checks}
        assert not named["no certification language the system produced"].passed
        assert not card.passed, "a generated claim must still fail the export"


class TestTheEvidenceCannotGoMissingQuietly:
    """A report that loses its photographs must not verify as fine.

    The photo check used to count against photographs that had *reached the service*, so an
    inspection holding eight whose uploads never happened exported with none and the check
    said "0 embedded, 0 expected — PASS". The bookkeeping was right and the report was wrong.
    """

    def test_recorded_but_unembedded_photographs_fail_the_export(self) -> None:
        inspection = sample.sample_inspection()
        result = pipeline.build(
            inspection,
            format_html(),
            {},  # no bytes to upload, so nothing reaches the document
            FakeSuperDocsClient(),
            session_id="no-photos",
            polish=False,
            settle_s=0.0,
        )
        card = verify_exports.verify(
            data=result.exports["docx"].content, fmt="docx", inspection=inspection
        )
        photo_check = next(c for c in card.checks if "photograph" in c.name)
        assert not photo_check.passed, "a report that lost its evidence verified as fine"
        assert "8 recorded" in photo_check.detail
        assert "never reached the service" in photo_check.detail

    def test_a_format_that_carries_no_photographs_is_still_fine(self) -> None:
        """The tightened check must not start failing the repair list, which has none."""
        inspection = sample.sample_inspection()
        template = format_html("repair_priority")
        result = pipeline.build(
            inspection,
            template,
            sample.sample_photo_data(),
            FakeSuperDocsClient(),
            session_id="no-photo-format",
            polish=False,
            settle_s=0.0,
        )
        card = verify_exports.verify(
            data=result.exports["docx"].content,
            fmt="docx",
            inspection=inspection,
            expect_photos=binding.carries_photos(template, SYSTEM_NAMES),
        )
        assert card.passed, card.render()


class TestTheRewritePassNeverSeesPhotographs:
    """The review runs on a photograph-free document, and the photographs go back for export.

    On the live service the review pass was unreliable on this report while the photographs
    were in it — three runs, 0, 0 and 1 of the eight marked notes rewritten — and reliable
    without them. A minimal synthetic document does not reproduce that consistently, so the
    photographs are not established as the cause; what is established is that this shape of
    document was unreliable and this change made it reliable. The fake cannot show any of it,
    because it filters proposals to marked paragraphs itself, which is exactly why these
    assertions are about the *document* rather than about the fake's behaviour.
    """

    def _prepared(self) -> tuple[FakeSuperDocsClient, object]:
        inspection = sample.sample_inspection()
        client = FakeSuperDocsClient()
        pipeline.prepare(
            inspection,
            format_html(),
            sample.sample_photo_data(),
            client,
            session_id="review-session",
        )
        return client, inspection

    def test_the_document_sent_for_review_carries_no_photographs(self) -> None:
        client, _ = self._prepared()
        assert "<img" not in client.sessions["review-session"].html

    def test_the_findings_are_all_still_there_to_be_reviewed(self) -> None:
        client, inspection = self._prepared()
        html = client.sessions["review-session"].html
        assert html.count(binding.NOTE_CLASS) == len(inspection.findings)  # type: ignore[attr-defined]

    @staticmethod
    def _final_html(client: FakeSuperDocsClient, session_id: str) -> str:
        """The document the export is actually taken from, not the one that was reviewed."""
        finals = [k for k in client.sessions if k.startswith(f"{session_id}-final-")]
        assert len(finals) == 1, f"expected one finished document, found {finals}"
        return client.sessions[finals[0]].html

    def test_the_photographs_are_back_in_the_document_that_gets_exported(self) -> None:
        inspection = sample.sample_inspection()
        client = FakeSuperDocsClient()
        pipeline.build(
            inspection,
            format_html(),
            sample.sample_photo_data(),
            client,
            session_id="export-session",
            settle_s=0.0,
        )
        embedded = self._final_html(client, "export-session").count("<img")
        assert embedded == inspection.photo_count()

    def test_the_exported_document_carries_the_approved_wording(self) -> None:
        inspection = sample.sample_inspection()
        client = FakeSuperDocsClient()
        pipeline.build(
            inspection,
            format_html(),
            sample.sample_photo_data(),
            client,
            session_id="wording-session",
            settle_s=0.0,
        )
        approved = [f for f in inspection.findings if f.plain_language]
        assert approved, "the sample is chosen so some rewrites are approved"
        html = self._final_html(client, "wording-session")
        for finding in approved:
            assert report.escape(finding.plain_language) in html

    def test_dropping_the_photographs_changes_nothing_else(self) -> None:
        """Only the pictures come out. Every word the reviewer reads is the same."""
        inspection = sample.sample_inspection()
        # Photographs only render once they have been uploaded and carry a URL.
        pipeline.upload_photos(
            inspection, sample.sample_photo_data(), FakeSuperDocsClient(), known=None
        )
        tpl = format_html()
        with_photos = report.render(inspection, tpl)
        without = report.render(inspection, tpl, include_photos=False)
        assert "<img" in with_photos and "<img" not in without
        for finding in inspection.findings:
            assert report.escape(finding.prose()) in without
