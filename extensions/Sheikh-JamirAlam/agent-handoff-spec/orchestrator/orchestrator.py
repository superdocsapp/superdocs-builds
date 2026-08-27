import json
import os
import re
from difflib import SequenceMatcher
from html import unescape
from dataclasses import dataclass, field
from pathlib import Path

from agents import DocumentState, MathCheckAgent, SpellingFixAgent
from validator import ActionDiff, ValidationResult, validate_action


@dataclass
class OrchestrationResult:
    document: DocumentState
    validations: list[ValidationResult] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return all(validation.accepted for validation in self.validations)


class Orchestrator:
    def __init__(self, spelling_agent: SpellingFixAgent | None = None,
                 math_agent: MathCheckAgent | None = None,
                 mutation_adapter=None, session_id: str | None = None,
                 approval_mode: str = "approve_all", document_fetcher=None,
                 section_extractor=None, spelling_sections: list[str] | None = None,
                 math_section: str = "pricing_table",
                 notes_section: str = "notes") -> None:
        self.spelling_sections = spelling_sections or [notes_section]
        self.math_section = math_section
        self.notes_section = notes_section
        self.spelling_agent = spelling_agent or SpellingFixAgent(
            protected_section=math_section)
        self.math_agent = math_agent or MathCheckAgent(
            pricing_section=math_section, next_section=notes_section)
        self.mutation_adapter = mutation_adapter
        self.session_id = session_id
        self.approval_mode = approval_mode
        self.document_fetcher = document_fetcher
        self.section_extractor = section_extractor

    def run(
        self,
        document: DocumentState,
        initial_envelope: dict,
        spelling_replacements: dict[str, dict[str, str]],
        log_path: str | Path | None = None,
    ) -> OrchestrationResult:
        self._current_document = document
        trace: list[dict] = []
        validations: list[ValidationResult] = []
        initial_target_sections = list(
            initial_envelope["scope"]["target_sections"])

        spelling_result = self.spelling_agent.process(
            initial_envelope, document, spelling_replacements
        )
        spelling_validation = validate_action(
            initial_envelope,
            ActionDiff(
                document.document_id,
                self.spelling_agent.agent_id,
                self.spelling_agent.agent_id,
                self.spelling_agent.action_name,
                frozenset(spelling_result.changed_sections),
            ),
        )
        validations.append(spelling_validation)
        trace.append(self.trace_entry(initial_envelope, spelling_validation, self.spelling_agent.agent_id,
                                      spelling_result.changed_sections))
        if not spelling_validation.accepted:
            return self.finish(document, validations, trace, log_path)

        self.apply_changes(document, spelling_result.changed_sections)
        self.remote_commit(spelling_result.changed_sections)
        self._refresh_document(document, spelling_result.changed_sections)
        document.review_state = spelling_result.next_envelope.review_state
        next_envelope = spelling_result.next_envelope.model_dump(mode="json")
        math_result = self.math_agent.process(next_envelope, document)
        math_validation = validate_action(
            next_envelope,
            ActionDiff(
                document.document_id,
                self.math_agent.agent_id,
                self.math_agent.agent_id,
                self.math_agent.action_name,
                frozenset(math_result.changed_sections),
            ),
        )
        validations.append(math_validation)
        trace.append(self.trace_entry(next_envelope, math_validation, self.math_agent.agent_id,
                                      math_result.changed_sections))
        if not math_validation.accepted:
            return self.finish(document, validations, trace, log_path)

        self.apply_changes(document, math_result.changed_sections)
        self.remote_commit(math_result.changed_sections)
        self._refresh_document(document, math_result.changed_sections)
        document.review_state = math_result.next_envelope.review_state
        final_envelope = math_result.next_envelope.model_dump(mode="json")
        final_target_sections = ([self.notes_section]
                                 if self.notes_section in document.sections
                                 else initial_target_sections)
        final_envelope["scope"] = {
            "action": "final spelling review",
            "target_sections": final_target_sections,
        }
        final_envelope["restrictions"] = {
            "forbidden_sections": [self.math_section],
            "forbidden_actions": ["verify totals"],
        }
        final_result = self.spelling_agent.process(
            final_envelope, document, spelling_replacements)
        final_validation = validate_action(
            final_envelope,
            ActionDiff(document.document_id, self.spelling_agent.agent_id,
                       self.spelling_agent.agent_id, "final spelling review",
                       frozenset(final_result.changed_sections)),
        )
        validations.append(final_validation)
        trace.append(self.trace_entry(final_envelope, final_validation, self.spelling_agent.agent_id,
                                      final_result.changed_sections))
        if not final_validation.accepted:
            return self.finish(document, validations, trace, log_path)
        self.apply_changes(document, final_result.changed_sections)
        self.remote_commit(final_result.changed_sections)
        document.review_state = final_result.next_envelope.review_state
        return self.finish(document, validations, trace, log_path)

    def _refresh_document(
        self,
        document: DocumentState,
        committed_changes: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        if self.document_fetcher is None or self.mutation_adapter is None:
            return
        verbose = os.getenv("SUPERDOCS_VERBOSE", "").lower() in {
            "1", "true", "yes", "on"}
        committed_changes = committed_changes or {}
        refreshed = self.document_fetcher.fetch(
            document.document_id, self.section_extractor)
        if verbose:
            stale_sections = [
                section for section, (before, _) in committed_changes.items()
                if refreshed.sections.get(section) == before
            ]
            print(
                f"[Orchestrator] refresh committed={list(committed_changes)} "
                f"stale={stale_sections}"
            )
        document.review_state = refreshed.review_state
        document.sections = refreshed.sections
        document.chunks = refreshed.chunks
        if verbose:
            for section, value in document.sections.items():
                print(
                    f"[Orchestrator] canonical section={section!r} value={value!r}")

    def export(self, format: str = "docx", options: dict | None = None,
               output_path: str | Path | None = None) -> dict:
        if self.mutation_adapter is None or self.session_id is None:
            raise RuntimeError(
                "a mutation adapter and session_id are required for export")
        return self.mutation_adapter.export(self.session_id, format, options, output_path)

    def remote_commit(self, changes: dict[str, tuple[str, str]]) -> None:
        verbose = bool(getattr(self.mutation_adapter, "verbose", False))
        if self.mutation_adapter is None or self.session_id is None:
            if verbose:
                print(
                    "[SuperDocs] write-back skipped: mutation adapter or session_id is missing")
            return
        if not changes:
            if verbose:
                print("[SuperDocs] write-back skipped: agent produced an empty diff")
            return
        expected_chunks = {}
        for section, (before, _) in changes.items():
            candidates = self.changed_chunks(
                before, changes[section][1],
                self._current_document.chunks.get(section, []))
            if candidates:
                expected_chunks[section] = candidates
        if verbose:
            print(f"[SuperDocs] committing sections: {sorted(changes)}")
        instructions = "\n".join(
            self.fragment_instructions(section, before, after)
            for section, (before, after) in changes.items()
        )
        response = self.mutation_adapter.edit(
            self.session_id, instructions, self.approval_mode)
        approval_required = bool(
            response.get("document_changes", {}).get("requires_approval")
        ) if isinstance(response, dict) else False
        response_to_verify = response
        if self.approval_mode == "ask_every_time" or approval_required:
            if approval_required:
                document_changes = response.get("document_changes", {})
                job_id = document_changes.get("job_id")
                pending_changes = document_changes.get("pending_changes") or []
                approvals = [
                    {"change_id": item["change_id"], "approved": True}
                    for item in pending_changes
                    if item.get("change_id")
                ]
                if not job_id or not approvals:
                    raise RuntimeError(
                        "SuperDocs requested approval but returned no job_id or pending changes"
                    )
                if verbose:
                    print(
                        f"[SuperDocs] response requires approval; approving "
                        f"{len(approvals)} pending changes automatically"
                    )
                response_to_verify = self.mutation_adapter.approve(
                    self.session_id,
                    job_id=job_id,
                    approved=True,
                    changes=approvals,
                )
                # The approval endpoint returns only an acknowledgment. Keep
                # the original pending diffs as the verification response.
                response_to_verify = {
                    "document_changes": {"chunk_diffs": pending_changes}
                }
            else:
                self.mutation_adapter.approve(self.session_id, approved=True)
        self.verify_remote_response(
            response_to_verify, changes, expected_chunks)

    @staticmethod
    def changed_chunks(before: str, after: str,
                       chunks: list[dict[str, str]]) -> list[dict[str, str]]:
        changed_ranges: list[tuple[int, int]] = []
        for tag, old_start, old_end, _, _ in SequenceMatcher(
                None, before, after, autojunk=False).get_opcodes():
            if tag != "equal":
                changed_ranges.append((old_start, old_end))
        result = []
        for chunk in chunks:
            start = before.find(chunk["text"])
            if start < 0:
                continue
            end = start + len(chunk["text"])
            if any(start < changed_end and changed_start < end
                   for changed_start, changed_end in changed_ranges):
                result.append(chunk)
        return result

    @staticmethod
    def verify_remote_response(response, changes, expected_chunks) -> None:
        diffs = (response.get("document_changes", {}).get("chunk_diffs", [])
                 if isinstance(response, dict) else [])
        if not expected_chunks:
            return
        returned = {diff.get("chunk_id"): diff for diff in diffs}
        for section, targets in expected_chunks.items():
            for target in targets:
                diff = returned.get(target["chunk_id"])
                if diff is None:
                    raise RuntimeError(
                        f"guarded edit refused: SuperDocs changed the wrong chunk for {section}")
                old_html = re.sub(r"<[^>]+>", "", diff.get("old_html", ""))
                if target["text"] not in unescape(old_html):
                    raise RuntimeError(
                        "guarded edit refused: returned old chunk is not the fetched target")

    @staticmethod
    def fragment_instructions(section: str, before: str, after: str) -> str:
        if before == after:
            return f"No changes are required in section {section}."
        label = section.replace("-", " ").replace("_", " ").title()
        old = " ".join(before.split())
        new = " ".join(after.split())
        return (
            f"For section {label}, find the text {old!r} and update exactly "
            f"with {new!r}."
        )

    def run_from_server(self, fetcher, document_id: str,
                        initial_envelope: dict,
                        spelling_replacements: dict[str, dict[str, str]],
                        log_path: str | Path | None = None) -> OrchestrationResult:
        document = fetcher.fetch(document_id)
        if initial_envelope.get("document_id") != document.document_id:
            raise ValueError(
                "initial envelope document_id does not match fetched document")
        return self.run(document, initial_envelope, spelling_replacements, log_path)

    @staticmethod
    def apply_changes(document: DocumentState, changes: dict[str, tuple[str, str]]) -> None:
        for section, (before, after) in changes.items():
            if document.sections.get(section) != before:
                raise RuntimeError(
                    f"document changed while action was pending: {section}")
            document.sections[section] = after

    @staticmethod
    def finish(document: DocumentState, validations: list[ValidationResult],
               trace: list[dict], log_path: str | Path | None) -> OrchestrationResult:
        result = OrchestrationResult(document, validations, trace)
        if log_path is not None:
            log_file = Path(log_path)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(json.dumps(trace, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def trace_entry(envelope: dict, validation: ValidationResult, agent_id: str,
                    changed_sections: dict[str, tuple[str, str]]) -> dict:
        return {
            "document_id": envelope["document_id"],
            "envelope_version": envelope.get("envelope_version", "1.0"),
            "issued_by": envelope["issued_by"],
            "received_by": agent_id,
            "review_state": envelope["review_state"],
            "changed_sections": sorted(changed_sections),
            "accepted": validation.accepted,
            "reason": validation.reason,
        }
