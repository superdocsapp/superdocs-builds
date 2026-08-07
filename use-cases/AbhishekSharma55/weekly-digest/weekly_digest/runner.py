"""Arm A - the digest that is EDITED, week after week, never regenerated.

The loop is boring on purpose. What is not boring is what surrounds it:

* **Resume.** Kill the run at week 31 and restart it: weeks 1-31 are skipped,
  week 32 rejoins the same session id from `state.json`, and week 32's edit is
  computed from week 31's bytes on disk. `make run-a` is safe to run as many
  times as you like. The one deliberate exception is a kill *during* a week:
  that week runs again and costs one more operation, because a week nobody
  verified is a week that is not done.
* **Budget.** Every week checks the cap before it spends. Hitting the cap is
  a clean stop with a resumable state, not a crash.
* **Evidence.** Every week writes four artefacts: the full HTML, the exported
  Markdown (free), the API's own change list, and an independent verdict
  derived from the bytes. Weeks 1..N can be diffed by anyone afterwards
  without touching the API again.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from superdocs_kit import OpsBudget, SuperDocs, sha, text_diff, verify_surgical
from superdocs_kit.errors import BudgetExceeded, QuotaExhausted

from .document import ARCHIVE_SECTION, STANDING_SECTIONS, archive_plan, seed_html
from .prompts import weekly_instruction
from .verify import WeekReport, check_week, drift_table

# Model settings, measured rather than chosen - and the history matters more
# than the values.
#
# When the weekly instruction DESCRIBED the target ("replace all bullets with
# exactly these four"), the default tier applied step 2 and silently dropped
# steps 1, 3, 4 and 5, four weeks running (bugs.md B9). The obvious fix was a
# bigger model, and 'pro'/'deep' did fix it - at ~195s a week instead of ~43s.
#
# The better fix was to stop being ambiguous. Once the factual sections are
# handed over as literal HTML (see document.py: bullets_html), the DEFAULT tier
# gets every step right and does it 4.5x faster. Measured on the same input
# document that had failed four times: bullets, "what is next", risk rows and
# alternating shading all exact.
#
# So attempt 1 is cheap and fast. Escalation is what the repair is for: a week
# that fails verification is retried on the strongest settings. Paying for the
# strongest model on every one of 52 weeks to cover a failure rate in the low
# single digits is the wrong trade, and tier does not change what SuperDocs
# bills either way - so this buys latency, not money.
MODEL_TIER = "core"
THINKING_DEPTH = "balanced"
REPAIR_MODEL_TIER = "pro"
REPAIR_THINKING_DEPTH = "deep"


@dataclass
class WeekRecord:
    week: int
    ops: int
    seconds: float
    api_changed_chunks: list[str]
    measured_changed_chunks: list[str]
    unintended_chunks: list[str]
    byte_identical_chunks: int
    doc_bytes: int
    doc_sha: str
    invariants_ok: bool
    invariant_failures: list[str] = field(default_factory=list)
    api_summary: str = ""
    attempts: int = 1
    repaired: bool = False
    rolled_back: bool = False
    first_attempt_failures: list[str] = field(default_factory=list)


class DigestRun:
    def __init__(
        self,
        *,
        weeks: list[dict],
        out_dir: Path,
        budget: OpsBudget,
        client: SuperDocs,
        session_id: str,
        log: Callable[[str], None] = print,
    ) -> None:
        self.weeks = weeks
        self.out = Path(out_dir)
        self.budget = budget
        self.client = client
        self.log = log
        # The session id is minted ONCE per run and kept in state.json, so a
        # resumed run rejoins its own session and a fresh run never inherits a
        # stale one. Re-using a session id that already holds an older version
        # of the document is what triggers bugs.md B8 (the document comes back
        # duplicated, or tripled). Costing a fresh session nothing, this is the
        # cheap half of that defence; the client owning the document is the
        # other half.
        state_path = Path(out_dir) / "state.json"
        prior = json.loads(state_path.read_text()) if state_path.exists() else {}
        self.session_id = prior.get("session_id") or f"{session_id}-{uuid.uuid4().hex[:10]}"
        (self.out / "html").mkdir(parents=True, exist_ok=True)
        (self.out / "md").mkdir(parents=True, exist_ok=True)
        (self.out / "diff").mkdir(parents=True, exist_ok=True)
        self.state_path = self.out / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.records: list[WeekRecord] = [
            WeekRecord(**r) for r in self.state.get("records", [])
        ]

    # ------------------------------------------------------------------
    def _save_state(self) -> None:
        self.state["session_id"] = self.session_id
        self.state["records"] = [asdict(r) for r in self.records]
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)  # atomic: a kill mid-write cannot corrupt state

    def _html_path(self, week: int) -> Path:
        return self.out / "html" / f"week-{week:02d}.html"

    def _read_html(self, week: int) -> str:
        p = self._html_path(week)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # ------------------------------------------------------------------
    def seed(self) -> str:
        """Week 1: upload the document verbatim. No model, no drift, free."""
        if self._html_path(1).exists() and self.state.get("seeded"):
            self.log("week 01  seeded already - skipping")
            return self._read_html(1)
        html = seed_html(self.weeks[0])
        up = self.client.upload_document(
            filename="nebula-drift-weekly-digest.html",
            content=html,
            session_id=self.session_id,
            return_html=True,
        )
        # Week 1 on disk is the SERVER's parse (which carries the chunk ids),
        # not our upload string. HTML export strips chunk ids (bugs.md B5), so
        # the upload's own return_html is the only free source of them.
        stored = up.get("html") or html
        self._html_path(1).write_text(stored, encoding="utf-8")
        self._export(1)
        rep = check_week(stored, self.weeks[0])
        self.records = [WeekRecord(
            week=1, ops=0, seconds=0.0, api_changed_chunks=[], measured_changed_chunks=[],
            unintended_chunks=[], byte_identical_chunks=0, doc_bytes=len(stored),
            doc_sha=sha(stored), invariants_ok=rep.ok,
            invariant_failures=[c.name for c in rep.failures], api_summary="seed upload",
        )]
        self.state["seeded"] = True
        self._save_state()
        self.log(f"week 01  seeded  {len(stored):>6}B  invariants={'ok' if rep.ok else rep.failures}")
        return stored

    def _export(self, week: int) -> None:
        """Exports are free, so every week gets a human-readable snapshot.

        A failed export must not fail the run: the document is fine, we just
        lost a convenience artefact. Degrade, log, continue.
        """
        try:
            md = self.client.export_text(session_id=self.session_id, fmt="markdown")
            (self.out / "md" / f"week-{week:02d}.md").write_text(md, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.log(f"  week {week}: markdown export unavailable ({type(exc).__name__})")

    # NOTE. There is deliberately no _restore() that re-uploads the document.
    # The first version had one, and it produced the ugliest failure of the
    # build: after a rollback, the next chat turn came back with the ENTIRE
    # document duplicated - two H1s, two of every section (bugs.md B8). I could
    # not reproduce it on a small document, which is exactly why the design
    # changed rather than the workaround growing.
    #
    # THE CLIENT OWNS THE DOCUMENT OF RECORD. Every week's turn re-asserts the
    # last known-good HTML via `document_html`, which the API defines as a
    # verbatim load. The server is the editor; the last good bytes live here.
    # That costs nothing (a verbatim load is not a billable edit - the ledger
    # proves it, every week still charges exactly one operation) and it removes
    # the whole class of "my state and the server's state disagree" bugs: after
    # a crash, a rollback, or a resumed run, week N is computed from week N-1's
    # bytes on disk and nothing else.
    #
    # What it costs, stated honestly: we stop exercising the server's own
    # cross-turn document persistence, which is a real feature of the product,
    # and every request carries the document (5-20 KB here). For a document
    # that outgrew a request body you would invert this - keep server state and
    # reconcile - and the trade would flip.

    # ------------------------------------------------------------------
    def run(self, upto: int) -> list[WeekRecord]:
        self.seed()
        done = {r.week for r in self.records}
        for week_rec in self.weeks[1:upto]:
            n = week_rec["week"]
            if n in done:
                continue
            label = f"w{n:02d}"
            # Resume granularity is one week, and it is driven by state.json
            # (weeks whose document was saved AND verified), not by the ledger.
            # The ledger is the money record; state is the work record. If we
            # are killed after paying for week 7 but before verifying it, week 7
            # runs again and costs one more operation - deliberately, because a
            # week nobody verified is a week that is not done. One operation is
            # the right price for that guarantee, and the double charge is
            # visible in the ledger rather than hidden.
            try:
                self.budget.check(label, 2)  # attempt + possible repair
            except BudgetExceeded as exc:
                self.log(f"\nSTOPPING CLEANLY at week {n}: {exc}")
                break
            try:
                self._run_week(week_rec)
            except QuotaExhausted as exc:
                self.log(f"\nSTOPPING CLEANLY at week {n}: {exc}")
                break
            self._save_state()
        self._write_reports()
        return self.records


    def _archived_after(self, week: int) -> set[int]:
        """Which weeks the archive should hold once week N's edit has landed.

        Each successful week K files ONE row: the week before it. So the set is
        every K-1 for the weeks K < N that were published, plus N-1 for the week
        about to land. A week that was rolled back never filed its row, so
        demanding {1..N-1} unconditionally would make the invariant impossible
        to satisfy for the rest of the year after a single bad week - the check
        would be measuring the past instead of the present.
        """
        archived = {
            r.week - 1 for r in self.records
            if r.week >= 2 and r.week < week and not r.rolled_back
        }
        return archived | {week - 1}

    def _run_week(self, week: dict) -> None:
        """One week. Attempt, verify from the bytes, and repair if it drifted.

        The repair path exists because a five-section edit occasionally comes
        back with a destroyed table and a success message (bugs.md B2/B3). It
        is not a retry-on-exception - nothing throws. It is a retry on
        *evidence*: the thirteen invariants are re-derived from the document
        and only they decide whether the week is good.

        Repair is one extra operation and it is charged, logged and reported
        like any other. Escalating a model failure to a second, differently
        primed attempt IS the fallback; rolling back to the last good document
        is the fallback's fallback, so the digest can never end a week corrupt.
        """
        n = week["week"]
        prev = self.weeks[n - 2]
        before = self._read_html(n - 1)
        plan = archive_plan(n)
        instruction = weekly_instruction(week, plan, prev, before_html=before)
        intended = list(STANDING_SECTIONS) + ([ARCHIVE_SECTION] if plan.add_row_for_week else [])
        status_chunks = self._status_chunk_ids(before)
        published = self._archived_after(n)

        started = time.monotonic()
        total_ops = 0
        attempts = 0
        first_failures: list[str] = []
        after = before
        res = None
        rep = None
        unintended: list[str] = []

        for attempt in range(1, 3):
            attempts = attempt
            # Every attempt re-asserts the last known-good document verbatim,
            # so one operation both guarantees the starting state and does the
            # week's work. See the note above _run_week's class about why the
            # client, not the session, holds the document of record.
            res = self.client.chat(
                session_id=self.session_id,
                message=instruction,
                label=f"w{n:02d}" if attempt == 1 else f"w{n:02d}-repair",
                response_mode="full",
                document_html=before,
                model_tier=MODEL_TIER if attempt == 1 else REPAIR_MODEL_TIER,
                thinking_depth=THINKING_DEPTH if attempt == 1 else REPAIR_THINKING_DEPTH,
                timeout=900,
            )
            total_ops += res.ops_charged
            after = res.updated_html or after
            verdict = verify_surgical(before, after, expected_sections=intended)
            unintended = [c for c in verdict.unintended if c not in status_chunks]
            rep = check_week(after, week, published)
            if rep.ok and not unintended:
                break
            if attempt == 1:
                first_failures = [c.name for c in rep.failures] + (
                    ["unintended section changed"] if unintended else []
                )
                # Keep the corrupted output. A failure we cannot look at later
                # is a failure we cannot report, and bug reports need bytes.
                bad = self.out / "failed-attempts"
                bad.mkdir(exist_ok=True)
                (bad / f"week-{n:02d}-attempt-1.html").write_text(after, encoding="utf-8")
                (bad / f"week-{n:02d}-instruction.txt").write_text(instruction, encoding="utf-8")
                self.log(
                    f"week {n:02d}  attempt 1 FAILED verification "
                    f"({', '.join(first_failures)}) - reloading last good doc and retrying"
                )

        rolled_back = False
        if rep is not None and (not rep.ok or unintended):
            self.log(f"week {n:02d}  repair did not hold - rolling back to week {n - 1}")
            # No server call: next week re-asserts this HTML as document_html.
            after = before
            rolled_back = True

        self._html_path(n).write_text(after, encoding="utf-8")
        self._export(n)
        verdict = verify_surgical(before, after, expected_sections=intended)
        (self.out / "diff" / f"week-{n:02d}.diff").write_text(
            text_diff(
                (self.out / "md" / f"week-{n - 1:02d}.md").read_text(encoding="utf-8")
                if (self.out / "md" / f"week-{n - 1:02d}.md").exists() else "",
                (self.out / "md" / f"week-{n:02d}.md").read_text(encoding="utf-8")
                if (self.out / "md" / f"week-{n:02d}.md").exists() else "",
                label_a=f"week-{n - 1:02d}", label_b=f"week-{n:02d}",
            ),
            encoding="utf-8",
        )

        self.records.append(WeekRecord(
            week=n, ops=total_ops, seconds=round(time.monotonic() - started, 2),
            api_changed_chunks=sorted(res.changed_chunk_ids) if res else [],
            measured_changed_chunks=sorted(verdict.detail["modified"] + verdict.detail["added"]),
            unintended_chunks=unintended,
            byte_identical_chunks=verdict.unchanged_count,
            doc_bytes=len(after), doc_sha=sha(after),
            invariants_ok=bool(rep and rep.ok and not unintended),
            invariant_failures=[c.name for c in rep.failures] if rep else [],
            api_summary=res.changes_summary if res else "",
            attempts=attempts, repaired=attempts > 1 and not rolled_back,
            rolled_back=rolled_back, first_attempt_failures=first_failures,
        ))
        flag = "ROLLED BACK" if rolled_back else ("repaired" if attempts > 1 else "ok")
        self.log(
            f"week {n:02d}  {total_ops} op  {round(time.monotonic() - started, 1):5.1f}s  "
            f"{len(after):>6}B  changed={len(verdict.detail['modified'])+len(verdict.detail['added']):>2}  "
            f"untouched={verdict.unchanged_count:>3}  unintended={len(unintended)}  {flag}"
        )

    @staticmethod
    def _status_chunk_ids(html: str) -> set[str]:
        """Chunks before the first H2 - title block and status line."""
        from superdocs_kit.docdiff import chunk_map

        cut = html.find("<h2")
        head = html[:cut] if cut > 0 else html
        return set(chunk_map(head))

    # ------------------------------------------------------------------
    def _write_reports(self) -> None:
        reports = []
        for rec in self.records:
            html = self._read_html(rec.week)
            if html:
                reports.append(check_week(html, self.weeks[rec.week - 1],
                                          self._archived_after(rec.week)))
        (self.out / "drift-report.md").write_text(
            "# Drift report - arm A (edited in place)\n\n"
            "Every row is an independent re-derivation from that week's document\n"
            "bytes. Nothing here is taken from the API's own summary.\n\n"
            + drift_table(reports)
            + "\n\n## Unintended section changes, week by week\n\n"
            + "| Week | sections the API said it changed | sections that actually changed "
              "| unintended | byte-identical sections |\n|---|---|---|---|---|\n"
            + "\n".join(
                f"| {r.week} | {len(r.api_changed_chunks)} | {len(r.measured_changed_chunks)} "
                f"| {len(r.unintended_chunks)}{'' if not r.unintended_chunks else ' ' + str(r.unintended_chunks[:3])} "
                f"| {r.byte_identical_chunks} |"
                for r in self.records[1:]
            )
            + "\n",
            encoding="utf-8",
        )
        (self.out / "records.json").write_text(
            json.dumps([asdict(r) for r in self.records], indent=2), encoding="utf-8"
        )
