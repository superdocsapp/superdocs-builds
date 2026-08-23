from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .alignment import align_chunk_ids, remap_case
from .approaches import direct_prompt, parse_search_chunk_ids, scoped_edit_prompt, search_prompt
from .budget import BudgetExceeded, OperationBudget, estimated_operations
from .html_units import changed_unit_ids
from .models import Approach, CorpusCase, InstructionType, RunResult
from .report import build_report
from .scorer import score_edit
from .superdocs_client import SuperDocsClient, SuperDocsOutcome


def select_cases(cases: list[CorpusCase], mode: str) -> list[CorpusCase]:
    if mode == "full":
        unreviewed = [case.case_id for case in cases if case.review_status.value != "approved"]
        if unreviewed:
            raise ValueError(
                "Full runs require independent second-review approval for every case; "
                f"unreviewed={unreviewed}"
            )
        return cases
    if mode != "small":
        raise ValueError("Run mode must be 'small' or 'full'")
    selected: list[CorpusCase] = []
    for instruction_type in InstructionType:
        match = next((case for case in cases if case.instruction_type == instruction_type), None)
        if match is None:
            raise ValueError(f"Corpus has no case for {instruction_type.value}")
        selected.append(match)
    return selected


def preflight_budget(cases: list[CorpusCase], approaches: set[Approach], operation_cap: int) -> int:
    estimate = estimated_operations(len(cases), {item.value for item in approaches})
    if estimate > operation_cap:
        raise BudgetExceeded(
            f"Planned run needs an estimated {estimate} operations, above the declared "
            f"cap of {operation_cap}. Reduce the corpus/approaches or explicitly raise the cap."
        )
    return estimate


def _actual_operations(outcome: SuperDocsOutcome) -> int:
    return outcome.operations_charged if outcome.operations_charged is not None else 1


async def _run_edit_call(
    *,
    client: SuperDocsClient,
    budget: OperationBudget,
    document_html: str | None,
    prompt: str,
    session_id: str,
) -> SuperDocsOutcome:
    budget.reserve(1)
    outcome = await client.edit_with_approval(
        document_html=document_html,
        message=prompt,
        session_id=session_id,
    )
    budget.reconcile(1, _actual_operations(outcome))
    return outcome


async def run_case(
    *,
    client: SuperDocsClient,
    budget: OperationBudget,
    case: CorpusCase,
    document_html: str,
    approach: Approach,
    run_id: str,
    export_root: Path | None = None,
) -> RunResult:
    started = time.perf_counter()
    search_chunk_ids: list[str] = []
    operations_before = budget.used
    session_id = f"edit-precision-{run_id}-{case.case_id}-{approach.value}"
    uploaded = await client.upload_document(
        filename=case.document,
        content=document_html.encode(),
        session_id=session_id,
    )
    required_ids = set().union(
        *(scope.expected_change_ids | scope.protected_ids for scope in case.acceptable_scopes)
    )
    chunk_id_map = align_chunk_ids(document_html, uploaded.html, required_ids)
    aligned_case = remap_case(case, chunk_id_map)

    if approach == Approach.DIRECT:
        outcome = await _run_edit_call(
            client=client,
            budget=budget,
            document_html=None,
            prompt=direct_prompt(case.instruction),
            session_id=session_id,
        )
    else:
        budget.reserve(1)
        search_outcome = await client.analyze(
            document_html=None,
            message=search_prompt(case.instruction),
            session_id=session_id,
        )
        budget.reconcile(1, _actual_operations(search_outcome))
        if search_outcome.updated_html:
            search_changes, _ = changed_unit_ids(uploaded.html, search_outcome.updated_html)
            if search_changes:
                raise ValueError(
                    "Search-scoped analysis unexpectedly edited the document; "
                    "the contaminated run was stopped before scoring"
                )
        search_chunk_ids = parse_search_chunk_ids(search_outcome.response_text)
        outcome = await _run_edit_call(
            client=client,
            budget=budget,
            document_html=None,
            prompt=scoped_edit_prompt(case.instruction, search_chunk_ids),
            session_id=session_id,
        )

    export_filename = f"{case.case_id}-{approach.value}.html"
    exported = await client.export_document(
        session_id=session_id,
        filename=export_filename,
        format="html",
    )
    if export_root is not None:
        export_root.mkdir(parents=True, exist_ok=True)
        (export_root / export_filename).write_bytes(exported.content)
    latency_ms = round((time.perf_counter() - started) * 1000)
    return RunResult(
        run_id=run_id,
        case_id=case.case_id,
        instruction_type=case.instruction_type,
        approach=approach,
        score=score_edit(aligned_case, uploaded.html, outcome.updated_html),
        latency_ms=latency_ms,
        operations_used=budget.used - operations_before,
        before_html=uploaded.html,
        after_html=outcome.updated_html,
        proposed_changes=outcome.proposed_changes,
        search_chunk_ids=search_chunk_ids,
        chunk_id_map=chunk_id_map,
        export_filename=export_filename,
        export_size_bytes=len(exported.content),
    )


async def run_evaluation(
    *,
    client: SuperDocsClient,
    cases: list[CorpusCase],
    document_root: Path,
    approaches: set[Approach],
    operation_cap: int,
    mode: str,
    export_root: Path | None = None,
) -> dict:
    selected = select_cases(cases, mode)
    preflight_budget(selected, approaches, operation_cap)
    budget = OperationBudget(operation_cap)
    run_id = uuid.uuid4().hex[:12]
    results: list[RunResult] = []
    for case in selected:
        document_html = (document_root / case.document).read_text()
        for approach in sorted(approaches, key=lambda item: item.value):
            results.append(
                await run_case(
                    client=client,
                    budget=budget,
                    case=case,
                    document_html=document_html,
                    approach=approach,
                    run_id=run_id,
                    export_root=export_root,
                )
            )
    return build_report(results, operation_cap=operation_cap, mode=mode)


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
