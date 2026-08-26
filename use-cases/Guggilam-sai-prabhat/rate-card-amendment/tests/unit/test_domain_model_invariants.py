"""Cross-cutting invariants required of every extracted fact."""

from __future__ import annotations

import pytest

from src.domain.models import ExtractionMethod, SourceCitation
from src.pipeline import analyze_contract


def test_source_citation_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        SourceCitation(
            document_id="doc",
            source_span="span",
            confidence=1.5,
            extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
        )


def test_every_citation_declares_a_deterministic_or_model_method(
    repo_root, expected_cases, reference_date
):
    for case in expected_cases:
        analysis = analyze_contract(str(repo_root / case["contract_file"]), reference_date)
        for citation in analysis.eligibility.citations:
            assert citation.extraction_method in (
                ExtractionMethod.DETERMINISTIC_RULE,
                ExtractionMethod.MODEL_REASONING,
                ExtractionMethod.FIXTURE_RECORDED,
            )


def test_rules_module_never_imports_a_model_client():
    # Deterministic rules must execute independently of model reasoning:
    # nothing under src/rules should import an LLM/model client module.
    import ast
    import pathlib

    rules_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "rules"
    banned_substrings = ("anthropic", "openai", "model_client", "llm")

    for path in rules_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for alias in node.names:
                    names.append(alias.name)
                for name in names:
                    lowered = name.lower()
                    assert not any(b in lowered for b in banned_substrings), (
                        f"{path} imports {name}, which suggests model reasoning "
                        "leaking into the deterministic rules layer"
                    )


def test_unsupported_notice_period_remains_null_not_guessed(
    repo_root, expected_cases, reference_date
):
    case = next(
        c
        for c in expected_cases
        if c["case_id"] == "case_05_ambiguous_requires_human_escalation"
    )
    analysis = analyze_contract(str(repo_root / case["contract_file"]), reference_date)
    assert analysis.notice.notice_period_days is None
    assert case["notice_period_days"] is None
