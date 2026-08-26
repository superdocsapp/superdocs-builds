"""The checks that decide whether a refreshed document may be released.

These run after the edit, on the artefact that actually came back. A guard that only ran on the
plan would be checking intent, not outcome.
"""

from dataclasses import dataclass, field
from pathlib import Path

from fund_update.domain.documents import DocumentView, read_document
from fund_update.domain.fieldmap import FieldMap


@dataclass(slots=True)
class GuardResult:
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def merge(self, other: "GuardResult") -> "GuardResult":
        self.passed += other.passed
        self.failures += other.failures
        self.warnings += other.warnings
        return self


def check_protected_wording(before: DocumentView, after: DocumentView, fieldmap: FieldMap) -> GuardResult:
    """The card's hardest requirement: unchanged legal wording provably byte-identical."""
    result = GuardResult()
    old_hashes = before.protected_hashes(fieldmap)
    new_hashes = after.protected_hashes(fieldmap)

    expected = {rule.starts_with for rule in fieldmap.protected_for(before.name)}
    for opening in sorted(expected):
        old, new = old_hashes.get(opening), new_hashes.get(opening)
        if old is None:
            result.warnings.append(
                f"{before.name}: protected paragraph not found before the edit: {opening!r}"
            )
            continue
        if new is None:
            result.failures.append(f"{before.name}: protected paragraph disappeared: {opening!r}")
        elif old != new:
            result.failures.append(f"{before.name}: protected wording changed: {opening!r}")
        else:
            result.passed.append(f"{before.name}: byte-identical: {opening!r}")
    return result


def check_tables_did_not_reflow(before: DocumentView, after: DocumentView, fieldmap: FieldMap) -> GuardResult:
    """A table that gained a row has pushed the page. In a three-page KID that is a breach."""
    result = GuardResult()
    spec = fieldmap.documents[before.name]
    for table_name in spec.tables_must_not_reflow:
        old = before.find_table(table_name)
        new = after.find_table(table_name)
        if old is None or new is None:
            result.warnings.append(f"{before.name}: table '{table_name}' not found on both sides")
            continue
        if old.row_count != new.row_count:
            result.failures.append(
                f"{before.name}: table '{table_name}' went from {old.row_count} to "
                f"{new.row_count} rows; that reflows the page"
            )
        elif len(old.headers) != len(new.headers):
            result.failures.append(f"{before.name}: table '{table_name}' changed column count")
        else:
            result.passed.append(f"{before.name}: table '{table_name}' held its shape")
    return result


def check_page_budget(pdf_path: Path, document: str, fieldmap: FieldMap) -> GuardResult:
    """Authoritative page count, read from the exported PDF rather than estimated."""
    result = GuardResult()
    budget = fieldmap.documents[document].page_budget
    if budget is None:
        return result
    if not pdf_path.is_file():
        result.warnings.append(
            f"{document}: no PDF export to measure, so the {budget}-page budget is unverified"
        )
        return result
    try:
        from pypdf import PdfReader

        pages = len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:
        result.warnings.append(f"{document}: could not read the exported PDF ({exc})")
        return result

    if pages > budget:
        result.failures.append(f"{document}: exported to {pages} pages against a hard budget of {budget}")
    else:
        result.passed.append(f"{document}: {pages} page(s), within the {budget}-page budget")
    return result


def check_only_intended_values_moved(
    before: DocumentView, after: DocumentView, expected_new_values: set[str]
) -> GuardResult:
    """Catches collateral damage: a paragraph that changed without being asked to."""
    result = GuardResult()
    old_paras = {" ".join(p.split()) for p in before.paragraphs}
    new_paras = {" ".join(p.split()) for p in after.paragraphs}

    appeared = new_paras - old_paras
    vanished = old_paras - new_paras

    unexplained = [
        para
        for para in appeared
        if not any(value.split("|")[0].strip() in para for value in expected_new_values)
    ]
    if unexplained:
        result.failures.append(
            f"{before.name}: {len(unexplained)} paragraph(s) changed that no edit asked for, "
            f"first is {unexplained[0][:100]!r}"
        )
    else:
        result.passed.append(
            f"{before.name}: {len(appeared)} changed paragraph(s), all traceable to a requested edit"
        )
    if len(vanished) > len(appeared):
        result.failures.append(
            f"{before.name}: {len(vanished) - len(appeared)} paragraph(s) were removed outright"
        )
    return result


def _value_present(value: str, text: str) -> bool:
    """A composite like `Aurora Semiconductor | 5.2%` lives in two table cells, never as one string."""
    return all(part.strip() in text for part in value.split("|") if part.strip())


def check_intended_values_landed(after: DocumentView, expected: set[str]) -> GuardResult:
    """The guard the first live run proved was missing: every requested value is really there.

    Approved changes apply asynchronously, so an export taken too early is the untouched
    document. Every other guard passes on it, because nothing moved.
    """
    result = GuardResult()
    if not expected:
        return result
    text = after.searchable_text()
    absent = sorted(value for value in expected if not _value_present(value, text))
    if absent:
        result.failures.append(
            f"{after.name}: {len(absent)} of {len(expected)} requested value(s) are not in the "
            f"export: {', '.join(absent[:5])}"
        )
    else:
        result.passed.append(f"{after.name}: all {len(expected)} requested value(s) present")
    return result


def run_all(
    before_dir: Path,
    after_dir: Path,
    fieldmap: FieldMap,
    expected_by_document: dict[str, set[str]],
    pdf_dir: Path | None = None,
) -> dict[str, GuardResult]:
    results: dict[str, GuardResult] = {}
    for name, spec in fieldmap.documents.items():
        after_path = after_dir / spec.filename
        if not after_path.is_file():
            continue
        before = read_document(name, before_dir / spec.filename)
        after = read_document(name, after_path)

        result = GuardResult()
        result.merge(check_protected_wording(before, after, fieldmap))
        result.merge(check_tables_did_not_reflow(before, after, fieldmap))
        expected = expected_by_document.get(name, set())
        result.merge(check_intended_values_landed(after, expected))
        result.merge(check_only_intended_values_moved(before, after, expected))
        if pdf_dir is not None:
            result.merge(check_page_budget(pdf_dir / f"{name}.pdf", name, fieldmap))
        results[name] = result
    return results
