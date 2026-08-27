from __future__ import annotations

import json
from pathlib import Path

from .html_units import extract_units
from .models import CorpusCase


class CorpusValidationError(ValueError):
    pass


def load_corpus(corpus_path: Path) -> list[CorpusCase]:
    cases: list[CorpusCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(corpus_path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = CorpusCase.model_validate_json(line)
        except Exception as exc:  # Pydantic includes the precise field path.
            raise CorpusValidationError(f"Invalid label on line {line_number}: {exc}") from exc
        if case.case_id in seen_ids:
            raise CorpusValidationError(f"Duplicate case_id: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise CorpusValidationError("Corpus is empty")
    return cases


def validate_corpus(corpus_path: Path, document_root: Path) -> list[str]:
    errors: list[str] = []
    cases = load_corpus(corpus_path)
    for case in cases:
        document_path = (document_root / case.document).resolve()
        try:
            document_path.relative_to(document_root.resolve())
        except ValueError:
            errors.append(f"{case.case_id}: document escapes corpus directory")
            continue
        if not document_path.is_file():
            errors.append(f"{case.case_id}: missing document {case.document}")
            continue
        try:
            document_ids = set(extract_units(document_path.read_text()))
        except ValueError as exc:
            errors.append(f"{case.case_id}: {exc}")
            continue
        for scope in case.acceptable_scopes:
            unknown = (scope.expected_change_ids | scope.protected_ids) - document_ids
            if unknown:
                errors.append(
                    f"{case.case_id}/{scope.scope_id}: unknown chunk IDs {sorted(unknown)}"
                )
    return errors


def write_jsonl(path: Path, records: list[dict]) -> None:
    payload = "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n"
    path.write_text(payload)
