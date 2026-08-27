from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from agents import GeminiDiffAdapter, MathCheckAgent, SpellingFixAgent
from orchestrator import OrchestrationResult, Orchestrator
from validator import ActionDiff, ValidationResult, validate_action
from superdocs_client import SuperDocsFetchAdapter, SuperDocsMutationAdapter


def initial_envelope(document_id: str = "INV-2026-0742",
                     spelling_sections: list[str] | None = None,
                     math_section: str = "items-and-pricing") -> dict:
    spelling_sections = spelling_sections or ["payment-terms"]
    first_spelling_section = spelling_sections[0]
    return {
        "document_id": document_id,
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": [first_spelling_section]},
        "restrictions": {
            "forbidden_sections": [math_section],
            "forbidden_actions": ["verify totals"],
        },
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime.now(timezone.utc),
    }


def run_fetched_rejection_demo(document_id: str, api_key: str, section_extractor,
                               log_path: str | Path = "logs/fetched-rejection-demo.json", *,
                               use_gemini: bool = False,
                               spelling_sections: list[str] | None = None,
                               math_section: str = "items-and-pricing",
                               verbose: bool = False) -> OrchestrationResult:
    load_dotenv()
    fetcher = SuperDocsFetchAdapter(api_key, verbose=verbose)
    try:
        document = fetcher.fetch(document_id, section_extractor)
        if use_gemini:
            model = GeminiDiffAdapter()
            orchestrator = Orchestrator(
                SpellingFixAgent(model, protected_section=math_section),
                MathCheckAgent(model, pricing_section=math_section),
                math_section=math_section,
                spelling_sections=spelling_sections)
        else:
            orchestrator = Orchestrator(
                math_section=math_section, spelling_sections=spelling_sections)

        trace: list[dict] = []
        validations: list[ValidationResult] = []
        first_envelope = initial_envelope(
            document.document_id, spelling_sections, math_section)
        spelling_result = orchestrator.spelling_agent.process(
            first_envelope, document, {})
        first_validation = validate_action(
            first_envelope,
            ActionDiff(document.document_id, "spelling-agent", "spelling-agent",
                       "fix spelling", frozenset(spelling_result.changed_sections)),
        )
        validations.append(first_validation)
        trace.append(orchestrator.trace_entry(
            first_envelope, first_validation, "spelling-agent",
            spelling_result.changed_sections))
        if not first_validation.accepted:
            return orchestrator.finish(document, validations, trace, log_path)

        orchestrator.apply_changes(document, spelling_result.changed_sections)
        document.review_state = spelling_result.next_envelope.review_state
        math_envelope = spelling_result.next_envelope.model_dump(mode="json")
        math_result = orchestrator.math_agent.process(math_envelope, document)

        # Intentional negative case: make Agent 2 report a Notes spelling edit, even though its envelope authorizes only the math section
        notes_before = document.sections.get("notes", "")
        notes_after = notes_before.replace("Emerjency", "Emergency", 1)
        if notes_after == notes_before:
            notes_after = notes_before.replace("Suppport", "Support", 1)
        malicious_result = replace(
            math_result,
            changed_sections={"notes": (notes_before, notes_after)},
        )
        rejection = validate_action(
            math_envelope,
            ActionDiff(document.document_id, "math-check-agent", "math-check-agent",
                       "verify totals", frozenset(malicious_result.changed_sections)),
        )
        validations.append(rejection)
        trace.append(orchestrator.trace_entry(
            math_envelope, rejection, "math-check-agent",
            malicious_result.changed_sections))
        return orchestrator.finish(document, validations, trace, log_path)
    finally:
        fetcher.close()


def run_fetched_demo(document_id: str, api_key: str, section_extractor,
                     log_path: str | Path = "logs/fetched-demo.json", *,
                     use_gemini: bool = False, session_id: str | None = None,
                     write_back: bool = False, approval_mode: str = "approve_all",
                     export_format: str | None = None,
                     spelling_sections: list[str] | None = None,
                     math_section: str = "pricing_table",
                     verbose: bool = False,
                     export_path: str | Path | None = None):
    load_dotenv()
    fetcher = SuperDocsFetchAdapter(api_key, verbose=verbose)
    mutation = None
    try:
        document = fetcher.fetch(document_id, section_extractor)
        if write_back:
            if session_id is None:
                session_id = fetcher.create_session(document.document_id)
            mutation = SuperDocsMutationAdapter(api_key, verbose=verbose)
        if use_gemini:
            model = GeminiDiffAdapter()
            orchestrator = Orchestrator(
                SpellingFixAgent(model, protected_section=math_section),
                MathCheckAgent(model, pricing_section=math_section), mutation,
                session_id, approval_mode, fetcher, section_extractor,
                spelling_sections, math_section)
        else:
            orchestrator = Orchestrator(mutation_adapter=mutation,
                                        session_id=session_id,
                                        approval_mode=approval_mode,
                                        document_fetcher=fetcher,
                                        section_extractor=section_extractor,
                                        spelling_sections=spelling_sections,
                                        math_section=math_section)
        result = orchestrator.run(
            document,
            initial_envelope(document.document_id,
                             spelling_sections, math_section),
            {},
            log_path,
        )
        if export_format is not None:
            if not result.accepted:
                raise RuntimeError("cannot export a rejected workflow")
            result.export = orchestrator.export(
                export_format, output_path=export_path)
        return result
    finally:
        fetcher.close()
        if mutation is not None:
            mutation.close()
