"""An agent that checks its allowance before planning, sizes the work to fit,
and degrades in plain language instead of failing halfway.

The shape of the problem, from the docs rather than from optimism:

  You cannot read your balance on demand. `/v1/users/me/usage` and `/limits`
  reject `sk_` keys with a 401. The agent-key path is `GET /v1/agents/whoami`
  once at the start, and after that the `usage` block that rides on every chat
  response. So the balance is authoritative at the start and after each call,
  and an *estimate* in between. `Balance.authoritative` carries that
  distinction so a report can never present a stale number as a live read.

The consequence worth naming: this agent does not "check remaining allowance"
continuously. It reads it, plans against it, and re-reads it as a side effect
of every call it makes. That is the strongest guarantee the platform allows,
and the report says which number it used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .budget import Balance, BudgetGuard, Change, Plan, estimate
from .client import (QuotaExhausted, RationExhausted, SuperDocsClient,
                     provably_never_sent)
from .idempotency import OperationLedger, State, operation_key
from .policy import Policy, StopReason, WhenItDoesNotFit
from .receipt import Receipt


@dataclass
class Step:
    """One unit of requested work: an edit instruction plus how many document
    sections it is expected to touch. Sections are what SuperDocs bills on --
    one operation per 25 sections edited -- so the plan is priced in sections
    and reported in operations."""
    step_id: str
    instruction: str
    sections: int
    severity: str = "medium"

    def as_change(self) -> Change:
        return Change(row_id=self.step_id, sections=self.sections, severity=self.severity)


@dataclass
class Report:
    """What the agent did, in the words it would say to a person."""
    balance_at_start: Balance | None = None
    balance_at_end: Balance | None = None
    planned: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    #: Steps an earlier run already paid for. Not repeated, and not billed.
    already_applied: list[str] = field(default_factory=list)
    #: Steps an earlier run started and whose outcome nobody ever learned.
    #: Neither repeated nor forgotten -- a person has to look at the document.
    needs_a_person: list[str] = field(default_factory=list)
    ops_spent: int = 0
    stopped_because: str = ""
    stop_reason: StopReason = StopReason.COMPLETED
    export_warnings: list = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    receipt: Receipt = field(default_factory=Receipt)

    def say(self, line: str) -> None:
        self.lines.append(line)

    def stop(self, reason: StopReason, line: str = "") -> None:
        """Stopping is a rule firing, not a number running out. Recording which
        rule is what lets somebody argue with it instead of raising it."""
        self.stop_reason = reason
        self.stopped_because = reason.explain()
        if line:
            self.say(line)

    def reconciliation(self) -> str:
        """Whether the line items agree with the allowance. Named, not hidden."""
        return self.receipt.reconcile(self.balance_at_start,
                                      self.balance_at_end).explanation

    def plain_language(self) -> str:
        out = list(self.lines)
        if self.already_applied:
            out.append(
                f"Already done by an earlier run, and not repeated: "
                f"{', '.join(self.already_applied)}. You were not charged again."
            )
        if self.needs_a_person:
            out.append(
                f"Started by an earlier run and never confirmed: "
                f"{', '.join(self.needs_a_person)}. These were not retried, "
                "because retrying might be charged twice and might apply the "
                "same edit twice. Open the document and check them."
            )
        if self.deferred:
            out.append(
                f"Left undone: {', '.join(self.deferred)}. "
                "These were not started, so nothing is half-applied."
            )
        if self.balance_at_end:
            out.append(f"Allowance now: {self.balance_at_end}.")
        return "\n".join(out)


class QuotaAwareAgent:
    """Reads the allowance, plans to fit it, and stops on the platform's signal.

    The stopping rule, stated once so it is not scattered:
      1. `quota_exhausted` from any response -- the platform's own signal, and
         the only authoritative one. Stop immediately.
      2. The reserve floor -- never spend the last `reserve` operations, so
         there is always enough left to export the work already done.
      3. `max_steps` -- the small-sample bound. Loops need a stopping rule.
    """

    def __init__(self, client: SuperDocsClient, guard: BudgetGuard | None = None,
                 policy: Policy | None = None,
                 ledger: OperationLedger | None = None) -> None:
        self._c = client
        self._g = guard or BudgetGuard()
        self._p = policy or Policy()
        # In memory unless a caller hands over a path. A ledger that forgets
        # when the process dies is no use for the failure it exists for, so the
        # CLI and the MCP server both give it a file.
        self._ledger = ledger or OperationLedger()

    @property
    def policy(self) -> Policy:
        return self._p

    def unresolved_operations(self) -> list[dict]:
        """Calls a previous run started and never learned the outcome of.

        Surfaced, never cleaned up. Deciding between "pay again" and "leave the
        work undone" is somebody's money and somebody's document, so it is
        reported and a person resolves it with `ledger.resolve`.
        """
        return [{"key": r.key, "step_id": r.step_id, "session_id": r.session_id}
                for r in self._ledger.unresolved()]

    def budget_hint(self) -> dict:
        """The allowance, in a shape a calling agent can plan against.

        An underused technique in the cost-governance literature and an obvious
        one once stated: an agent that knows what is left can decide earlier,
        summarise instead of re-reading, or escalate before it runs out. This
        rides back on every tool result rather than needing its own call --
        which matters here, because a call to find out is not free everywhere
        and asking is itself a decision an agent should not have to make.
        """
        balance = self._g.remaining()
        ration = self._g.ration
        hint = {
            "remaining_operations": balance.ops,
            "authoritative": balance.authoritative,
            "as_of": balance.as_of,
            "reserve": self._p.reserve,
            "spendable_on_new_edits": self._p.spendable(balance.ops),
            "exhausted": self._g.exhausted,
            "policy": self._p.describe(),
            "note": (
                "Authoritative at whoami and after every response that carried a "
                "usage block; inferred in between, and it says which. Exports "
                "are free, which is why the reserve costs you nothing."
            ),
        }
        if self._g.exhausted:
            # Which ceiling stopped us, because the two have different remedies.
            hint["exhausted_because"] = self._g.exhausted_because
        if ration is not None:
            # Only present when a second ceiling is actually in play. An agent
            # planning against `remaining_operations` needs to know that number
            # may be the ration rather than the account, or it will read a small
            # number as "buy more allowance" when the answer is "use your own
            # key, or come back after 00:00 UTC".
            hint["daily_ration"] = {
                "remaining_calls": ration.ops,
                "resets_at": ration.as_of,
                "source": ration.limited_by,
                "binding": balance is ration,
                "note": (
                    "Counted in charged calls, not in SuperDocs operations, and "
                    "never confirmed by the lender — it is an estimate until a "
                    "refusal proves otherwise. Set SUPERDOCS_API_KEY to remove "
                    "this ceiling entirely."
                ),
            }
        return hint

    def settled(self, session_id: str, steps: list[Step]) -> tuple[
            list[Step], list[str], list[str]]:
        """Split requested work by what an earlier run already did with it.

        Returns (still to do, already applied, started and never confirmed).

        This exists so a plan and a run cannot disagree. Pricing work that an
        earlier run already paid for quotes a number nobody will be charged,
        and an agent deciding what it can afford against that number is being
        told the wrong thing by the tool whose entire job is telling it the
        right thing.
        """
        to_do: list[Step] = []
        applied: list[str] = []
        unconfirmed: list[str] = []
        for step in steps:
            record = self._ledger.get(operation_key(
                session_id, step.step_id, step.instruction, step.sections))
            if record.state is State.APPLIED:
                applied.append(step.step_id)
            elif record.state is State.IN_FLIGHT:
                unconfirmed.append(step.step_id)
            else:
                to_do.append(step)
        return to_do, applied, unconfirmed

    # -- planning ---------------------------------------------------------
    def read_allowance(self) -> Balance:
        """The one moment the number is authoritative before any work begins."""
        # A second ceiling, if the transport is lending us somebody else's key
        # under a daily ration. Opened here rather than in the constructor
        # because this is where the allowance is established, and the two are
        # one question -- "how much may I spend?" -- with two answers that both
        # have to be true. whoami is free on both sides, so this costs nothing.
        ration = getattr(self._c, "daily_ration", None)
        if ration is not None:
            self._g.open_ration(ration)
        r = self._c.whoami()
        if r.usage.get("quota_exhausted") or getattr(self._c, "quota_exhausted", False):
            # whoami is free and is not refused by exhaustion, but the signal it
            # carries is the authoritative one and has to reach the planner.
            self._g.mark_exhausted()
        remaining, resets_at = self._balance_from_whoami(r.body)
        if remaining is None:
            # Never invent a balance. An unknown allowance is planned as zero,
            # which degrades to doing nothing and saying why -- loudly, because
            # the alternative failure is the dangerous one: a build that reads
            # nothing, plans against nothing, does nothing, and looks like a
            # pass. It is not silent here; `fit` says there are no operations
            # available to spend and the run reports having started nothing.
            return self._g.seed_from_whoami(0)
        return self._g.seed_from_whoami(int(remaining), as_of=resets_at)

    @staticmethod
    def _balance_from_whoami(body: dict) -> tuple[int | None, str]:
        """The remaining allowance, whichever shape whoami answered in.

        Three shapes are real and the field name is not stable across them:

          * `quota.remaining` -- what both the origin and the relay actually
            return, verified live 2026-08-27. This is the one that matters.
          * `remaining_operations` -- the flat form named in the API docs.
          * `usage.monthly_remaining` -- the field that rides on chat responses,
            in case whoami ever answers in the same vocabulary as everything
            else.

        Read as a list rather than as one field because the cost of guessing
        wrong is not an error. It is `None`, which becomes a balance of zero,
        which becomes a plan that fits nothing and a run that does nothing and
        exits 0 -- an agent that quietly did not work looks exactly like an
        agent with an empty allowance. The relay's key is not an agent account
        (`is_agent_account: false`), so the shape it answers in is somebody
        else's decision, not ours.
        """
        quota = body.get("quota") or {}
        usage = body.get("usage") or {}
        for value, resets_at in (
            (quota.get("remaining"), quota.get("resets_at")),
            (body.get("remaining_operations"), body.get("resets_at")),
            (usage.get("monthly_remaining"), usage.get("resets_at")),
        ):
            if value is not None:
                return int(value), str(resets_at or "")
        return None, ""

    #: Each step is its own `POST /v1/chat/async`, so each one bills at least
    #: one operation. Pooling their sections and dividing by 25 -- which is
    #: right for a publisher that sends one request -- under-prices an agent
    #: that sends several, and an under-priced plan is an agent starting work
    #: it cannot finish. Named here so the planner and `_run_step` cannot drift
    #: apart about what a step costs.
    BATCHED = False

    def plan(self, steps: list[Step]) -> Plan:
        """Price the work and fit it to what is left, under the policy."""
        budget = self._p.spendable(self._g.remaining().ops)
        steps, _bit = self._p.bound(steps)
        plan = self._g.fit([s.as_change() for s in steps], remaining=budget,
                           batched=self.BATCHED)
        if (plan.publish and plan.defer
                and self._p.when_it_does_not_fit is WhenItDoesNotFit.REFUSE):
            # A caller who would rather have nothing than a subset said so.
            return Plan(publish=[], defer=plan.publish + plan.defer,
                        rationale=StopReason.REFUSED_PARTIAL.explain(),
                        batched=self.BATCHED)
        return plan

    # -- execution --------------------------------------------------------
    def run(self, session_id: str, filename: str, content: bytes, steps: list[Step],
            export_format: str = "docx") -> Report:
        """Read the allowance, size the work, do what fits, and say what it did.

        The order is the load-bearing part and it is why this reads as four
        steps rather than one block: the allowance is read *before* anything is
        planned, the plan is priced *before* anything is uploaded, and the export
        runs even when the run stopped early — because it is free, which is what
        the reserve exists to guarantee.
        """
        report = Report(receipt=Receipt(session_id=session_id))

        start = self._read_and_report_allowance(report)
        steps = self._apply_sample_bound(steps, report)
        # Priced only over work nobody has paid for yet. What an earlier run
        # settled is named in the report, not quoted as a cost.
        steps = self._set_aside_what_earlier_runs_settled(session_id, steps, report)
        if not steps and (report.already_applied or report.needs_a_person):
            # Nothing left to do because an earlier run did it, not because it
            # would not fit. Reporting that as "nothing fits" would send a
            # caller off to buy allowance it does not need.
            return self._nothing_left_to_do(session_id, export_format, start, report)
        plan = self._price(steps, report)
        if not plan.publish:
            return self._did_not_start(plan, report)

        # Free per the docs, so it is not priced -- and it happens only after
        # everything that could refuse has refused.
        self._c.upload(session_id, filename, content)
        report.say(f"Uploaded {filename}.")

        self._work(session_id, plan, {s.step_id: s for s in steps}, report)
        return self._export(session_id, export_format, start, report)

    # -- the steps of a run, each one its own decision ----------------------
    def _read_and_report_allowance(self, report: Report) -> Balance:
        start = self.read_allowance()
        report.balance_at_start = start
        report.say(f"Starting allowance: {start}.")
        return start

    def _apply_sample_bound(self, steps: list[Step], report: Report) -> list[Step]:
        bounded, bit = self._p.bound(steps)
        if bit:
            report.say(
                f"Small-sample mode: running {self._p.max_steps} of {len(steps)} "
                "requested steps."
            )
        return bounded

    def _set_aside_what_earlier_runs_settled(
            self, session_id: str, steps: list[Step], report: Report) -> list[Step]:
        to_do, applied, unconfirmed = self.settled(session_id, steps)
        for step_id in applied:
            report.already_applied.append(step_id)
            report.say(f"'{step_id}': an earlier run already applied this. "
                       "Not repeated, and not billed again.")
        for step_id in unconfirmed:
            report.needs_a_person.append(step_id)
            report.say(
                f"'{step_id}': an earlier run started this and never learned "
                "whether it finished. Not retried — that might be charged twice "
                "and might apply the same edit twice.")
        return to_do

    def _price(self, steps: list[Step], report: Report) -> Plan:
        plan = self.plan(steps)
        report.planned = [c.row_id for c in plan.publish]
        report.deferred = [c.row_id for c in plan.defer]
        needed = estimate([s.as_change() for s in steps], batched=self.BATCHED)
        report.say(
            f"The full request would cost about {needed} operation(s). "
            + ("It fits." if plan.complete else plan.rationale)
        )
        return plan

    def _nothing_left_to_do(self, session_id: str, export_format: str,
                            start: Balance, report: Report) -> Report:
        """Every requested step was settled by an earlier run.

        Nothing is billed, and the export still runs, because the point of a
        rerun after a crash is to walk away with the file.
        """
        report.stop(
            StopReason.STARTED_AND_UNKNOWN if report.needs_a_person
            else StopReason.ALREADY_APPLIED,
            "Nothing was sent: every requested step was settled by an earlier "
            "run. You were not charged again.",
        )
        try:
            return self._export(session_id, export_format, start, report)
        except Exception as e:
            # The session may not exist on this key any more. Say which,
            # rather than turning a rerun into a crash.
            report.say(
                f"The export could not be made for session '{session_id}': {e}. "
                "Nothing was billed. Open the session in SuperDocs and export "
                "from there.")
            report.balance_at_end = self._g.remaining()
            return report

    def _did_not_start(self, plan: Plan, report: Report) -> Report:
        """Nothing uploaded, nothing billed, and no half-edited document."""
        refused = plan.rationale == StopReason.REFUSED_PARTIAL.explain()
        report.stop(
            StopReason.REFUSED_PARTIAL if refused else StopReason.NOTHING_FITS,
            "Did not start: "
            + ("only part of the work fits, and this policy refuses a partial "
               "run rather than deliver a subset."
               if refused else
               "none of the requested work fits inside the remaining allowance.")
            + " Nothing was uploaded and nothing was billed.",
        )
        report.balance_at_end = self._g.remaining()
        return report

    def _work(self, session_id: str, plan: Plan, by_id: dict[str, Step],
              report: Report) -> None:
        """Each fitted step: instruct, wait, approve — unless it is already done."""
        for change in plan.publish:
            step = by_id[change.row_id]
            key = operation_key(session_id, step.step_id, step.instruction,
                                step.sections)
            if self._already_settled(key, step, report):
                continue

            try:
                self._run_step(session_id, step, report, key)
            except RationExhausted as e:
                # A different ceiling from the one below, with a different
                # remedy, so it is never folded into it. The relay refused this
                # call outright: nothing was sent upstream and nothing was
                # billed by either the relay or SuperDocs.
                self._g.ration_exhausted()
                report.stop(StopReason.RATION_EXHAUSTED)
                report.deferred.append(step.step_id)
                report.say(
                    f"Stopped at '{step.step_id}': {e}. The step was not "
                    "started, so nothing is half-applied.")
                return
            except QuotaExhausted:
                report.stop(StopReason.QUOTA_EXHAUSTED)
                report.deferred.append(step.step_id)
                report.say(
                    f"Stopped during '{step.step_id}': SuperDocs reported the "
                    "allowance exhausted. That request still completed; nothing "
                    "further was attempted."
                )
                return
            if self._reserve_reached(plan, step, report):
                return

    def _already_settled(self, key: str, step: Step, report: Report) -> bool:
        """Has this exact call already been paid for, or already been sent?

        SuperDocs has no idempotency on billable writes, so a rerun after a
        crash would otherwise be charged again for work already in the document.
        """
        prior = self._ledger.get(key)
        if prior.state is State.APPLIED:
            report.already_applied.append(step.step_id)
            report.say(
                f"'{step.step_id}': an earlier run already applied this. "
                "Not repeated, and not billed again."
            )
            return True
        if prior.state is State.IN_FLIGHT:
            report.needs_a_person.append(step.step_id)
            report.say(
                f"'{step.step_id}': an earlier run started this and never "
                "learned whether it finished. Not retried — that might be "
                "charged twice and might apply the same edit twice."
            )
            return True
        return False

    def _reserve_reached(self, plan: Plan, step: Step, report: Report) -> bool:
        if self._g.remaining().ops > self._p.reserve:
            return False
        remaining_ids = [
            c.row_id for c in plan.publish
            if c.row_id not in report.completed and c.row_id != step.step_id
        ]
        if remaining_ids:
            report.stop(StopReason.RESERVE_FLOOR)
            report.deferred.extend(remaining_ids)
            report.say(
                f"Stopped after '{step.step_id}': holding back the last "
                f"{self._p.reserve} operation(s) so the work already done "
                "can still be exported."
            )
        return True

    def _export(self, session_id: str, export_format: str, start: Balance,
                report: Report) -> Report:
        """Free, so it always runs — including after stopping early. That is the
        whole reason the reserve is worth holding."""
        exported = self._c.export(session_id, export_format)
        report.export_warnings = self._c.export_warnings(exported)
        report.say(f"Exported the document as {export_format} (exports are free).")
        if report.export_warnings:
            report.say(
                f"The export completed with {len(report.export_warnings)} "
                "non-fatal warning(s), listed in the report -- the file is usable."
            )
        report.balance_at_end = self._g.remaining()
        report.ops_spent = max(0, (start.ops if start else 0) - report.balance_at_end.ops)
        return report

    def _run_step(self, session_id: str, step: Step, report: Report,
                  key: str | None = None) -> None:
        key = key or operation_key(session_id, step.step_id, step.instruction,
                                   step.sections)
        # Written BEFORE the call goes out. If the process dies between these
        # two lines the ledger says "started, outcome unknown", which is the
        # truth; writing it afterwards would leave no trace of a call that was
        # charged.
        self._ledger.begin(key, session_id=session_id, step_id=step.step_id)
        try:
            started = self._c.edit(session_id, step.instruction)
        except Exception as e:
            # Which of these two it is decides whether a rerun repeats the call.
            # "It failed" is not enough information to answer that, so it is
            # never the answer recorded: only a failure that PROVES the request
            # never reached SuperDocs is marked repeatable. Everything else --
            # a read timeout, a 5xx from a gateway, a dropped connection -- may
            # have been accepted and billed, and is recorded as started and
            # unconfirmed so a person looks at it instead of a retry paying
            # for it twice.
            if provably_never_sent(e):
                self._ledger.failed(
                    key, f"the edit call was rejected before it was billed: {e}")
            else:
                self._ledger.never_learned(
                    key, f"the edit call did not return, and may have been "
                         f"accepted and billed: {e}")
            raise
        self._reconcile(started, report, billable_ops=estimate([step.as_change()]),
                        step_id=step.step_id, call="edit")
        job_id = started.body.get("job_id")
        if not job_id:
            self._ledger.applied(key, note="no job id returned")
            report.say(f"'{step.step_id}': no job id returned; nothing applied.")
            return

        waited = self._c.poll_job(
            job_id,
            on_wait=lambda s, status: report.say(
                f"'{step.step_id}': still {status} after {s:.0f}s -- processing, not stalled."
            ) if s and s % 60 == 0 else None,
        )
        self._reconcile(waited, report, step_id=step.step_id, call="poll")

        if waited.body.get("status") == "awaiting_approval":
            changes = self._pending(waited)
            decisions = [{"change_id": c.get("change_id"), "approved": True} for c in changes]
            if decisions:
                approved = self._c.approve(session_id, job_id, decisions)
                self._reconcile(approved, report, step_id=step.step_id,
                                call="approve")
                report.say(f"'{step.step_id}': approved {len(decisions)} proposed change(s).")

                # Approval is ASYNCHRONOUS. The approve call returns ok, then
                # the job resumes and applies the change. Exporting before it
                # reaches a terminal state returns the document as it was --
                # HTTP 200, a valid file, and the edit silently missing. Verified
                # against the live API on 2026-08-19.
                settled = self._c.poll_job(job_id, deadline_s=300, interval_s=2)
                self._reconcile(settled, report, step_id=step.step_id,
                                call="poll")
                if settled.body.get("status") != "completed":
                    report.say(
                        f"'{step.step_id}': the job ended as "
                        f"'{settled.body.get('status')}' rather than completed; the "
                        "approved change may not have been applied."
                    )
        self._ledger.applied(key, job_id=str(job_id))
        report.completed.append(step.step_id)

    @staticmethod
    def _pending(job: dict | object) -> list[dict]:
        """One implementation, in the client, shared by both builds."""
        from .client import pending_changes

        return pending_changes(job.body if hasattr(job, "body") else job)

    #: The calls a lender charges its ration for: the chat instruction and the
    #: re-edit an approval asks for. Deliberately the same set of paths the
    #: relay bills (`client.relay_charges_for`) rather than the set SuperDocs
    #: bills, because the two ceilings count different things -- SuperDocs
    #: counts operations per 25 sections, a lender counts calls proxied.
    RATIONED_CALLS = {"edit", "approve"}

    def _reconcile(self, response, report: Report, billable_ops: int = 0,
                   step_id: str = "", call: str = "") -> None:
        if call in self.RATIONED_CALLS:
            # Counted whether or not a usage block came back: the ration is a
            # count of calls, and this call happened.
            self._g.spend_ration(1)
        usage = response.usage
        if not usage:
            # A billable call that returned no usage block leaves us guessing.
            # Guess, and say that we are guessing.
            if billable_ops:
                self._g.assume_spent(billable_ops)
            if call:
                report.receipt.record(
                    step_id, call, billable=bool(billable_ops),
                    ops_charged=None, ops_estimated=billable_ops,
                    balance=self._g.remaining(),
                    note=("no usage block came back, so this line is what we "
                          "believe rather than what was stated")
                    if billable_ops else "",
                )
            return
        self._g.reconcile(
            ops_charged=int(usage.get("ops_charged", 0)),
            monthly_remaining=usage.get("monthly_remaining"),
            quota_exhausted=bool(usage.get("quota_exhausted", False)),
        )
        if call:
            report.receipt.record(
                step_id, call, billable=bool(billable_ops),
                ops_charged=int(usage.get("ops_charged", 0)),
                ops_estimated=billable_ops, balance=self._g.remaining(),
            )
