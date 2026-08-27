"""Report formats are registered with SuperDocs and the report is built from what it returns.

The point of these tests is to make "we use the templates surface" falsifiable. The strongest
one is in ``TestDegradation``: delete the format from the account and the round trip stops
working. A surface that is really load-bearing breaks when you take it away.

This is where the build changed shape. Formats used to be HTML marked up with
``<!-- region:system -->`` comments, and the round trip could never complete, because upload
parses a document into chunks and drops HTML comments — so the markers the binder needed were
gone by the time the document came back. Formats are Word documents now, marked with
bracketed tokens a person types, and those survive. The tests that recorded the old failure
have been replaced by tests that the round trip actually happens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from inspection_report import sample
from inspection_report.domain import catalogue
from inspection_report.render import report as render_report
from inspection_report.superdocs.fake import FakeSuperDocsClient
from inspection_report.templates import binding, registry

TEMPLATE_DIR = Path("templates")


@pytest.fixture
def client() -> FakeSuperDocsClient:
    return FakeSuperDocsClient()


def _minimal_format(marker: str) -> Any:
    """The smallest thing that is still a readable format: a worked example and six sections."""
    from docx import Document

    doc = Document()
    doc.add_paragraph(f"[firm name] {marker}")
    doc.add_paragraph("[property address] — [inspector] — [date of inspection]")
    doc.add_heading("How each finding is recorded", level=1)
    doc.add_paragraph("[severity label]: [location]")
    doc.add_paragraph("[observation]")
    doc.add_paragraph("[recommendation]")
    doc.add_heading("What was inspected", level=1)
    doc.add_paragraph("[systems inspected]")
    for system in catalogue.systems():
        doc.add_heading(system.name, level=1)
        doc.add_paragraph("[findings]")
    return doc


class TestRegistration:
    def test_every_shipped_format_is_registered(self, client: FakeSuperDocsClient) -> None:
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        assert set(formats) == {p.stem for p in TEMPLATE_DIR.glob("*.docx")}
        assert len(client.list_templates()) == len(formats)

    def test_registering_twice_uploads_nothing_new(self, client: FakeSuperDocsClient) -> None:
        """Idempotent: a restart must not fill the account with duplicate formats."""
        registry.ensure_registered(client, TEMPLATE_DIR)
        before = {t.id for t in client.list_templates()}
        registry.ensure_registered(client, TEMPLATE_DIR)
        assert {t.id for t in client.list_templates()} == before

    def test_an_edited_format_registers_as_a_new_version(
        self, client: FakeSuperDocsClient, tmp_path: Path
    ) -> None:
        """A changed format must not redefine the one existing reports were built from."""
        d = tmp_path / "templates"
        d.mkdir()
        target = d / "house.docx"
        _minimal_format("v1").save(str(target))
        first = registry.ensure_registered(client, d)["house"]

        _minimal_format("v2").save(str(target))
        second = registry.ensure_registered(client, d)["house"]

        assert first.content_sha != second.content_sha
        assert first.name != second.name
        assert len(client.list_templates()) == 2, "the earlier version must still exist"


class TestTheRoundTripActuallyHappens:
    """The format really does come back from SuperDocs, and the report is built on it.

    A `.docx` format survives registration and loading with its structure intact — measured
    against the live service, and mirrored here by the fake. That is what makes the templates
    surface load-bearing rather than called once so it can be mentioned.
    """

    def test_the_format_comes_back_from_the_service(self, client: FakeSuperDocsClient) -> None:
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        _, from_service = registry.materialise(client, formats["buyer_summary"], session_id="s1")
        assert from_service is True, "the report was not built from what SuperDocs returned"

    def test_what_comes_back_is_readable_as_a_format(self, client: FakeSuperDocsClient) -> None:
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        html, _ = registry.materialise(client, formats["buyer_summary"], session_id="s1")
        fmt = binding.read_format(html, [s.name for s in catalogue.systems()])
        assert len(fmt.system_slots) == len(catalogue.systems())
        assert fmt.finding_shape.carries_photos

    def test_the_standing_text_survives_the_round_trip(self, client: FakeSuperDocsClient) -> None:
        """The firm's own wording is the reason for having a format at all."""
        from inspection_report.templates import authoring

        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        html, _ = registry.materialise(client, formats["buyer_summary"], session_id="s1")
        assert authoring.PREAMBLE[:60] in html
        assert authoring.LIMITS[:60] in html

    def test_a_report_renders_from_the_returned_skeleton(self, client: FakeSuperDocsClient) -> None:
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        html, _ = registry.materialise(client, formats["buyer_summary"], session_id="s1")
        report_html = render_report.render(sample.sample_inspection(), html)
        assert "14 Alder Lane" in report_html
        assert "Recommend prompt evaluation" in report_html

    def test_the_worked_example_never_reaches_the_report(self, client: FakeSuperDocsClient) -> None:
        """It is scaffolding for whoever authors the format, not part of a buyer's report."""
        from inspection_report.templates import authoring

        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        html, _ = registry.materialise(client, formats["buyer_summary"], session_id="s1")
        report_html = render_report.render(sample.sample_inspection(), html)
        assert authoring.EXAMPLE_HEADING not in report_html
        assert "[observation]" not in report_html

    def test_the_cache_answers_the_second_time(self, client: FakeSuperDocsClient) -> None:
        """One operation per format version, not per report."""
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        cache: dict[str, str] = {}
        first, first_from_service = registry.materialise(
            client, formats["buyer_summary"], session_id="s1", cache=cache
        )
        second, second_from_service = registry.materialise(
            client, formats["buyer_summary"], session_id="s2", cache=cache
        )
        assert first_from_service is True
        assert second_from_service is False, "the second report paid for the format again"
        assert first == second


class TestDegradation:
    def test_an_unreachable_service_still_produces_a_report(
        self, client: FakeSuperDocsClient
    ) -> None:
        """An inspector who walked a property gets their report out even if SuperDocs is down.

        What must never happen is claiming the round trip occurred when it did not — hence
        the flag, which the caller reports rather than swallowing.
        """
        formats = registry.ensure_registered(client, TEMPLATE_DIR)
        fmt = formats["buyer_summary"]
        client.templates.clear()
        client.template_bytes.clear()

        html, from_service = registry.materialise(client, fmt, session_id="s1")
        assert from_service is False
        # The local copy is still a whole format, so the report is complete — only its
        # provenance differs, and the caller is told.
        report_html = render_report.render(sample.sample_inspection(), html)
        assert "14 Alder Lane" in report_html

    def test_a_document_that_is_not_the_format_is_refused(
        self, client: FakeSuperDocsClient, tmp_path: Path
    ) -> None:
        """A skeleton that cannot group a report is not accepted as one."""
        from docx import Document

        d = tmp_path / "t"
        d.mkdir()
        doc = Document()
        doc.add_heading("Not a report format at all", level=1)
        doc.add_paragraph("Just some prose.")
        doc.save(str(d / "broken.docx"))

        fmt = registry.ensure_registered(client, d)["broken"]
        _, from_service = registry.materialise(client, fmt, session_id="s1")
        assert from_service is False, "an unusable skeleton was accepted as the format"
