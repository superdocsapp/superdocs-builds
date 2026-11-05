"""Arm B - the control: regenerate the whole digest every week.

This is what a team does today. Copy last week's file, ask an AI to write
this week's version, paste it back. Every section is produced afresh.

Fairness rules, fixed before any number was collected:

* Same 52 weeks of input, same order, same facts.
* Same target document: same four sections, same table columns, same
  formatting brief (bordered table, shaded header, alternating rows).
* Same server, same billing meter. Cost is `usage.ops_charged`, read from
  the response, in both arms.
* Arm B is given the archive contents as input rather than being asked to
  remember them, because a regenerating system has no memory of the previous
  document. Withholding them would have made arm B produce a shorter document
  and won the comparison dishonestly.
* Each week of arm B runs in its own fresh session, because that is what
  "regenerated" means. Arm A runs in one session for all 52 weeks, because that
  is what "edited" means.
* Arm B is verified against the SAME fourteen invariants as arm A, and gets the
  SAME escalation budget when a week fails. Giving my own build a repair path
  and not giving one to the control would be rigging the measurement.

The one asymmetry, stated because it matters: arm A's per-week instruction is
shorter than arm B's (it names five targeted changes; arm B restates the whole
document). Both are prompt-side costs that SuperDocs does not bill for -
billing is per edited section, not per token - so it does not affect the
operations comparison. It does affect *your* token bill if you drive this with
your own model, and that is measured separately as `instruction_chars`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from superdocs_kit import OpsBudget, SuperDocs, sha
from superdocs_kit.errors import BudgetExceeded, QuotaExhausted

from .prompts import regenerate_instruction
from .runner import (MODEL_TIER, REPAIR_MODEL_TIER, REPAIR_THINKING_DEPTH,
                     THINKING_DEPTH)
from .verify import check_week


@dataclass
class RegenRecord:
    week: int
    ops: int
    seconds: float
    doc_bytes: int
    doc_sha: str
    sections_created: int
    instruction_chars: int
    api_summary: str = ""
    attempts: int = 1
    invariants_ok: bool = False
    invariant_failures: list = field(default_factory=list)


def archive_rows_for(weeks: list[dict], upto_week: int) -> list[dict]:
    """The archive arm B has to re-emit each week. Deterministic, identical in
    information content to what arm A's archive holds at the same week."""
    rows = []
    for w in weeks[: upto_week - 1]:
        rows.append({
            "week": f"Week {w['week']}",
            "dates": w["dates"],
            "shipped": "; ".join(w["shipped"])[:120],
            "risks": "; ".join(r["risk"] for r in w["risks"])[:90],
        })
    return list(reversed(rows))


class RegenerateRun:
    def __init__(
        self,
        *,
        weeks: list[dict],
        out_dir: Path,
        budget: OpsBudget,
        client: SuperDocs,
        run_id: str,
        log: Callable[[str], None] = print,
    ) -> None:
        self.weeks = weeks
        self.out = Path(out_dir)
        self.budget = budget
        self.client = client
        self.run_id = run_id
        self.log = log
        (self.out / "html").mkdir(parents=True, exist_ok=True)
        self.state_path = self.out / "records.json"
        self.records: list[RegenRecord] = (
            [RegenRecord(**r) for r in json.loads(self.state_path.read_text())]
            if self.state_path.exists() else []
        )

    def run(self, upto: int) -> list[RegenRecord]:
        done = {r.week for r in self.records}
        for week in self.weeks[:upto]:
            n = week["week"]
            label = f"regen-w{n:02d}"
            if n in done or self.budget.already_done(label):
                continue
            try:
                self.budget.check(label, 1)
            except BudgetExceeded as exc:
                self.log(f"\nSTOPPING CLEANLY at regen week {n}: {exc}")
                break
            instruction = regenerate_instruction(week, archive_rows_for(self.weeks, n))
            started = time.monotonic()
            total_ops = 0
            attempts = 0
            html = ""
            res = None
            rep = None

            # SYMMETRY WITH ARM A, and it is what makes the comparison fair.
            # Arm A verifies every week from the document bytes and, on failure,
            # spends a second operation retrying on stronger settings. Arm B gets
            # exactly the same treatment: same invariants, same escalation, same
            # accounting. Giving arm A a repair budget and not arm B would be
            # rigging the measurement in favour of my own build.
            #
            # It matters here. On the default tier, regenerating week 8 returned a
            # 1.2 KB document containing one of the four sections - a truncation
            # that grows more likely as the archive it has to re-emit grows. That
            # is a real cost of regenerating, and it is counted rather than hidden.
            for attempt in range(1, 3):
                attempts = attempt
                try:
                    res = self.client.chat(
                        session_id=f"{self.run_id}-regen-w{n:02d}-{uuid.uuid4().hex[:8]}",
                        message=instruction,
                        label=label if attempt == 1 else f"{label}-repair",
                        response_mode="full",
                        model_tier=MODEL_TIER if attempt == 1 else REPAIR_MODEL_TIER,
                        thinking_depth=(THINKING_DEPTH if attempt == 1
                                        else REPAIR_THINKING_DEPTH),
                        timeout=900,
                    )
                except QuotaExhausted as exc:
                    self.log(f"\nSTOPPING CLEANLY at regen week {n}: {exc}")
                    return self.records
                total_ops += res.ops_charged
                html = res.updated_html or html
                rep = check_week(html, week, published_weeks=set(range(1, n)))
                if rep.ok:
                    break
                if attempt == 1:
                    self.log(f"regen week {n:02d}  attempt 1 failed verification "
                             f"({len(rep.failures)} checks) - retrying on stronger settings")

            (self.out / "html" / f"week-{n:02d}.html").write_text(html, encoding="utf-8")
            self.records.append(RegenRecord(
                week=n, ops=total_ops, seconds=round(time.monotonic() - started, 2),
                doc_bytes=len(html), doc_sha=sha(html),
                sections_created=len(res.changes) if res else 0,
                instruction_chars=len(instruction),
                api_summary=res.changes_summary if res else "",
                attempts=attempts, invariants_ok=bool(rep and rep.ok),
                invariant_failures=[c.name for c in rep.failures] if rep else [],
            ))
            self._save()
            self.log(
                f"regen week {n:02d}  {total_ops} op  "
                f"{round(time.monotonic() - started, 1):5.1f}s  {len(html):>6}B  "
                f"attempts={attempts}  {'ok' if rep and rep.ok else 'INVALID'}"
            )
        return self.records

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in self.records], indent=2), encoding="utf-8")
        tmp.replace(self.state_path)
