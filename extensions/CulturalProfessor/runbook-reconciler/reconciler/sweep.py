"""One pass over the estate: read, extract, check, record, account.

The stages are named and timed because behaviour ten of the brief asks a run to
report what it spent and where the time went. They are also the unit of resume:
each one is idempotent, so a run killed anywhere can be started again and the
only cost is repeating the stage that was in flight.

**Nothing in this module spends a paid operation.** That is not an accident of
the current implementation, it is the design: the deterministic layers run to
completion first, and the SuperDocs path in `edit.py` is entered only for
findings that survived them and that a human approved. A sweep over an estate
with no drift makes no API call at all, and `test_zero_spend.py` asserts the
zero rather than this docstring claiming it.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from reconciler.check.coverage import Coverage, check_coverage
from reconciler.check.vertical import Check, check_page, load_checks
from reconciler.claims import Claim, Finding
from reconciler.config import Config
from reconciler.confluence.local import LocalSource, PageRef
from reconciler.estate import Estate
from reconciler.extract.patterns import extract_claims
from reconciler.extract.storage import Document
from reconciler.register import Register


@dataclass
class SweepResult:
    run_id: str
    claims: list[Claim] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    stages: dict[str, float] = field(default_factory=dict)
    operations: int = 0
    #: True when the sweep was narrowed to some pages, so no coverage number was
    #: computed. Reported rather than silently showing zeros.
    coverage_skipped: bool = False

    @property
    def contradictions(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict == "contradicts"]

    @property
    def unverifiable(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict == "unverifiable"]

    @property
    def agreements(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict == "agrees"]

    def summary_line(self) -> str:
        pages = len({f.page_id for f in self.contradictions if f.page_id})
        return (
            f"{len(self.contradictions)} findings across {pages} runbooks · "
            f"{len(self.agreements)} claims verified · "
            f"{len(self.unverifiable)} could not be checked · "
            f"{self.operations} paid operations"
        )


class Sweep:
    """A run, with its stage accounting attached.

    Takes its page source as an argument rather than constructing one, because
    the corpus and Confluence Cloud are interchangeable here and the whole
    pipeline should not be able to tell which it is talking to.
    """

    def __init__(
        self,
        config: Config,
        register: Register,
        source: LocalSource | None = None,
        checks: list[Check] | None = None,
    ) -> None:
        self.config = config
        self.register = register
        self.source = source or LocalSource(
            config.runbook_source or Path("fixtures/runbooks"), config.runbook_label
        )
        self.checks = checks if checks is not None else load_checks(config.checks_path)

    @contextmanager
    def _stage(self, result: SweepResult, name: str, operations: int = 0) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            result.stages[name] = round(elapsed, 4)
            self.register.record_stage(result.run_id, name, elapsed, operations)

    def run(self, mode: str = "check", page_ids: list[str] | None = None) -> SweepResult:
        run_id = self.register.start_run(mode=mode)
        result = SweepResult(run_id=run_id)

        with self._stage(result, "read-ground-truth"):
            estate = Estate.load(self.config)

        with self._stage(result, "read-runbooks"):
            # Two lists, and conflating them was a real bug. `pages` is what
            # gets checked; `all_pages` is what "does this runbook_url resolve"
            # is answered against. Narrowing a sweep to one page must not make
            # every other page look deleted -- `rr check --pages 1008` reported
            # six alerts as having dead links, on an estate where none did.
            all_pages = self.source.pages()
            pages = [p for p in all_pages if not page_ids or p.page_id in page_ids]
            documents = {page.page_id: self.source.read(page.page_id) for page in pages}

        with self._stage(result, "extract-claims"):
            per_page = {
                page_id: extract_claims(document) for page_id, document in documents.items()
            }
            result.claims = [claim for claims in per_page.values() for claim in claims]
            self.register.upsert_claims(result.claims)

        with self._stage(result, "check-claims"):
            for page_id, claims in per_page.items():
                result.findings.extend(check_page(page_id, claims, estate, self.checks))

        with self._stage(result, "check-coverage"):
            # Coverage is a property of the whole estate, so a sweep narrowed to
            # some pages does not compute a partial one -- it computes none.
            #
            # The first attempt filtered the page list and got this wrong in the
            # worst available way: `rr check --pages 1008` reported six alerts as
            # having dead runbook links, because every page it had not been asked
            # to read looked deleted. A coverage number that changes depending on
            # what you asked to check is not a coverage number, and reporting one
            # is exactly the bluffing this project exists to avoid.
            result.coverage_skipped = bool(page_ids)
            if not page_ids:
                result.coverage = check_coverage(
                    estate=estate,
                    pages=all_pages,
                    page_text={page_id: doc_text(doc) for page_id, doc in documents.items()},
                    orphan_pages=tuple(
                        sorted(
                            {f.page_id for f in result.findings if "orphan" in f.tags if f.page_id}
                        )
                    ),
                    dead_dashboard_links=sum(
                        1
                        for f in result.findings
                        if f.kind == "link" and f.verdict == "contradicts"
                    ),
                )
                result.findings.extend(result.coverage.findings)

        with self._stage(result, "record"):
            self.register.upsert_findings(result.findings)

        self.register.finish_run(run_id)
        return result


def doc_text(document: Document) -> str:
    """Everything a page says, for the "is this alert documented anywhere" join."""
    return "\n".join(block.text for block in document.blocks)


def pages_of(source: LocalSource) -> list[PageRef]:
    return source.pages()


__all__ = ["Sweep", "SweepResult", "doc_text"]
