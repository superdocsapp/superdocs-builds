from __future__ import annotations

from drift_check import report
from drift_check.pipeline import run_pipeline
from drift_check.providers.fixture import FixtureProvider


def _run_with_xss_payloads():
    source = (
        "# <script>alert(1)</script> Title\n\n"
        "## Section One\n"
        "The user must comply with <img src=x onerror=alert(2)> this clause.\n"
    )
    target = (
        "# <script>alert(1)</script> Titulo\n\n"
        "## Seccion Uno\n"
        "El usuario debe cumplir con <img src=x onerror=alert(2)> esta clausula.\n"
    )
    provider = FixtureProvider({1: "The user should comply with <script>alert(3)</script> this clause."})
    return run_pipeline(
        run_id="\"><script>alert(4)</script>",
        source_raw_text=source,
        target_raw_text=target,
        source_document_id="d",
        target_document_id="d-t",
        source_lang="en",
        target_lang="es",
        provider=provider,
    )


class TestHtmlEscaping:
    def test_no_raw_tag_survives_into_html_output(self) -> None:
        """Document content, back-translation text, and even the run_id are
        untrusted by construction and must never produce a live tag."""
        html_out = report.to_html(_run_with_xss_payloads())
        assert "<img src=x onerror" not in html_out
        assert "&lt;img src=x onerror" in html_out  # present, but inert
        assert not any(line.strip().startswith("<script>alert") for line in html_out.splitlines())

    def test_run_id_payload_is_escaped_not_executed(self) -> None:
        html_out = report.to_html(_run_with_xss_payloads())
        assert '"><script>alert(4)</script>' not in html_out
        assert "&lt;script&gt;alert(4)" in html_out or "&quot;&gt;&lt;script&gt;" in html_out

    def test_finding_still_detected_despite_markup_in_content(self) -> None:
        # Escaping shouldn't come at the cost of correctness — the genuine
        # modal drift in this same content must still be found.
        result = _run_with_xss_payloads()
        assert any(f.category.value == "modal_obligation_change" for f in result.findings)


class TestOversizedAndMalformedInput:
    def test_very_large_document_completes_without_hanging_or_crashing(self) -> None:
        many_sections = "\n\n".join(f"## Section {i}\nThe user must comply. " * 20 for i in range(200))
        source = "# Big Document\n\n" + many_sections
        provider = FixtureProvider({i: "The user must comply. " * 20 for i in range(1, 201)})
        result = run_pipeline(
            run_id="oversized", source_raw_text=source, target_raw_text=source,
            source_document_id="big", target_document_id="big-t", source_lang="en", target_lang="en",
            provider=provider,
        )
        assert result.metrics.sections_total == 200
        assert all(v.ok for v in result.integrity_verifications)

    def test_binary_garbage_input_does_not_crash_the_parser(self) -> None:
        from drift_check.parsing import parse_document

        garbage = "\x00\x01\x02## \ufffd\ufffd garbled heading\ntext with \x1b escape codes"
        doc = parse_document(garbage, document_id="d", language="en")
        assert doc.source_hash  # completed without raising

    def test_empty_string_input_does_not_crash(self) -> None:
        result = run_pipeline(
            run_id="empty", source_raw_text="", target_raw_text="", source_document_id="e",
            target_document_id="e-t", source_lang="en", target_lang="es", provider=FixtureProvider({}),
        )
        assert result.findings == []
        assert all(v.ok for v in result.integrity_verifications)
