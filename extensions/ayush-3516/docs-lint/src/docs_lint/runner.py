"""The orchestrator: stages, decisions, budget, degradation and resumption.

The run moves through visible stages and announces what it decided at each one. Several of those
decisions change the path rather than decorating it:

* **skip** — the file is cached, or another run holds its lock
* **retry** — a transient failure, backed off inside the client
* **degrade** — SuperDocs is unreachable, so the run continues on local rules and says so
* **stop** — the operation budget is spent, so remaining files are skipped rather than half-checked
* **escalate** — proposals exist, so the file stops and waits for a human

Nothing here writes to a document. `check` produces findings; applying them is a separate step that
requires a `Decisions` object, and that is the only way anything reaches disk.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .cache import VerdictCache
from .config import Config, ConfigError
from .model import (
    FileResult,
    Finding,
    RunSummary,
    Severity,
    Verdict,
)
from .parser import parse_document
from .rules import run_local_rules
from .state import FileState, RunState, RunStore, Stage, content_sha
from .superdocs.client import SuperDocsClient
from .superdocs.errors import (
    SuperDocsAuthError,
    SuperDocsError,
    SuperDocsJobFailed,
    SuperDocsJobTimeout,
    SuperDocsSessionBusy,
)
from .superdocs.lint_pass import (
    STYLE_GUIDE_RULE,
    UNANCHORED_RULE,
    build_instruction,
    findings_from_job,
)
from .targets import Target

LOCAL_CHECK = "local"
SUPERDOCS_CHECK = "superdocs"


@dataclass(frozen=True)
class Event:
    """Something the run decided, emitted as it happens so progress is watchable."""

    stage: str
    action: str
    detail: str = ""
    path: str | None = None

    def __str__(self) -> str:
        where = f" {self.path}" if self.path else ""
        detail = f" — {self.detail}" if self.detail else ""
        return f"[{self.stage}] {self.action}{where}{detail}"


Observer = Callable[[Event], None]


def _ignore(_event: Event) -> None:
    return None


@dataclass
class Budget:
    """A hard ceiling on billed operations, enforced before each one is started."""

    limit: int
    spent: int = 0

    @property
    def exhausted(self) -> bool:
        return self.limit > 0 and self.spent >= self.limit

    def charge(self, ops: int) -> None:
        self.spent += ops


@dataclass
class Runner:
    """Runs a check over a set of targets, or resumes one that was interrupted."""

    config: Config
    store: RunStore
    cache: VerdictCache
    client: SuperDocsClient | None = None
    observe: Observer = _ignore
    #: Injected for tests so retry and poll loops do not really sleep.
    sleep: Callable[[float], None] = time.sleep
    _stage_times: dict[str, float] = field(default_factory=dict, init=False)

    # -- entry points ---------------------------------------------------------------

    def check(self, targets: Iterable[Target], *, notes: Iterable[str] = ()) -> RunSummary:
        """Run every stage over the given targets and return the summary."""
        targets = list(targets)
        state = RunState.new(
            mode="check",
            config_fingerprint=self.config.fingerprint(),
            files=tuple(
                FileState(path=t.relative, content_sha=content_sha(t.data)) for t in targets
            ),
        )
        for note in notes:
            state = state.with_degraded(note)
        self.store.save(state)
        self.observe(Event("select", "selected", f"{len(targets)} document(s)"))
        return self._run(state, {t.relative: t for t in targets})

    def resume(self, run_id: str, targets: Iterable[Target]) -> RunSummary:
        """Continue an interrupted run without redoing or re-buying finished work."""
        state = self.store.load(run_id)
        if state.config_fingerprint != self.config.fingerprint():
            raise ConfigError(
                f"Run {run_id} was made under a different configuration. "
                "Mixing verdicts from two rule sets would be dishonest; start a fresh run."
            )
        by_path = {t.relative: t for t in targets}
        remaining = state.unfinished
        self.observe(
            Event(
                "resume",
                "resuming",
                f"{len(remaining)} of {len(state.files)} document(s) unfinished, "
                f"{state.ops_charged} operation(s) already spent",
            )
        )
        return self._run(state, by_path)

    # -- the loop -------------------------------------------------------------------

    def _run(self, state: RunState, targets: dict[str, Target]) -> RunSummary:
        budget = Budget(limit=self.config.superdocs.budget_operations, spent=state.ops_charged)
        results: list[FileResult] = []

        for file_state in state.files:
            if file_state.stage.is_finished and file_state.verdict is not None:
                results.append(
                    FileResult(
                        path=file_state.path,
                        verdict=file_state.verdict,
                        findings=file_state.findings,
                        from_cache=file_state.from_cache,
                        seconds=file_state.seconds,
                        ops_charged=file_state.ops_charged,
                    )
                )
                continue

            target = targets.get(file_state.path)
            if target is None:
                state, result = self._finish(
                    state, file_state, Verdict.skipped("file is no longer present")
                )
                results.append(result)
                continue

            state, result = self._check_one(state, file_state, target, budget)
            results.append(result)

        summary = RunSummary(
            run_id=state.run_id,
            results=tuple(results),
            stage_seconds=dict(state.stage_seconds),
            ops_charged=sum(r.ops_charged for r in results),
            degraded=state.degraded,
        )
        self.store.save(state)
        return summary

    def _check_one(
        self, state: RunState, file_state: FileState, target: Target, budget: Budget
    ) -> tuple[RunState, FileResult]:
        started = time.monotonic()

        with self.store.lock_file(target.relative, run_id=state.run_id) as acquired:
            if not acquired:
                self.observe(
                    Event("lock", "skip", "another run holds this document", target.relative)
                )
                return self._finish(
                    state, file_state, Verdict.skipped("locked by another run"), seconds=0.0
                )

            cached = self.cache.get(target.relative, target.data)
            if cached is not None:
                self.observe(Event("cache", "hit", "unchanged since last run", target.relative))
                return self._finish(
                    state,
                    file_state,
                    cached.verdict,
                    findings=cached.findings,
                    from_cache=True,
                    seconds=time.monotonic() - started,
                )
            self.observe(Event("cache", "miss", "checking", target.relative))

            document = parse_document(target.relative, target.text)
            local_started = time.monotonic()
            local_findings = list(run_local_rules(document, self.config))
            state = state.with_stage_time(LOCAL_CHECK, time.monotonic() - local_started)
            self.observe(
                Event(
                    "rules",
                    "checked",
                    f"{len(local_findings)} local finding(s)",
                    target.relative,
                )
            )

            file_state = file_state.advanced(Stage.LOCAL_CHECKED, findings=tuple(local_findings))
            state = state.with_file(file_state)
            self.store.save(state)

            checks_run = [LOCAL_CHECK]
            findings = list(local_findings)
            ops = 0

            if self._superdocs_wanted():
                if budget.exhausted:
                    note = f"operation budget of {budget.limit} spent; local rules only"
                    self.observe(Event("budget", "stop", note, target.relative))
                    state = state.with_degraded(note)
                else:
                    state, extra, ops, checked = self._superdocs_pass(
                        state, file_state, target, document, budget
                    )
                    findings.extend(extra)
                    if checked:
                        checks_run.append(SUPERDOCS_CHECK)

            verdict = (
                Verdict.findings(checks_run=tuple(checks_run))
                if findings
                else Verdict.clean(checks_run=tuple(checks_run))
            )
            state, result = self._finish(
                state,
                file_state,
                verdict,
                findings=tuple(findings),
                ops_charged=ops,
                seconds=time.monotonic() - started,
            )
            self.cache.put(result, target.data)
            self.observe(
                Event("verdict", verdict.kind.value, f"{len(findings)} finding(s)", target.relative)
            )
            return state, result

    # -- the model pass -------------------------------------------------------------

    def _superdocs_wanted(self) -> bool:
        return bool(
            self.config.superdocs.enabled
            and self.client is not None
            and self.config.styleguide.path
        )

    def _superdocs_pass(
        self,
        state: RunState,
        file_state: FileState,
        target: Target,
        document,
        budget: Budget,
    ) -> tuple[RunState, list[Finding], int, bool]:
        """Upload, instruct, poll, and turn proposals into findings.

        Returns `(state, findings, ops_charged, checked)`. `checked` is False whenever the pass did
        not complete, so the caller never records SuperDocs among the checks that ran.
        """
        assert self.client is not None
        stage_started = time.monotonic()
        # One session per document: a job parked awaiting review holds its session against
        # everything else, so sharing one would make each document block the next (BUGS.md #8).
        session_id = file_state.session_id or f"docs-lint-{uuid.uuid4().hex[:12]}"

        try:
            styleguide_name = Path(self.config.styleguide.path or "styleguide.md").name
            upload = self.client.upload_document(
                Path(target.relative).name, target.data, session_id=session_id
            )
            chunk_ids = frozenset(upload.chunk_ids)

            file_state = file_state.advanced(Stage.UPLOADED, session_id=session_id)
            state = state.with_file(file_state)
            self.store.save(state)

            # Counted here, not from the job's own `result.usage`: that block only exists once a
            # job completes, and these jobs deliberately park at awaiting_approval. Counting at the
            # point of spend also keeps a reattached job from being charged to a second run.
            ops_spent_now = 0

            job_id = file_state.job_id
            if job_id is None:
                job_id = self.client.start_async_chat(
                    session_id=session_id,
                    message=build_instruction(styleguide_name),
                    document_html=upload.html,
                    approval_mode="ask_every_time",
                    model_tier=self.config.superdocs.model_tier,
                    thinking_depth=self.config.superdocs.thinking_depth,
                    window_id=state.run_id,
                )
                # Persisted before the first poll. A crash after this line costs nothing on resume;
                # a crash before it costs one operation. Hence the ordering.
                file_state = file_state.advanced(Stage.JOB_STARTED, job_id=job_id)
                state = state.with_file(file_state)
                self.store.save(state)
                ops_spent_now = 1
                budget.charge(1)
                self.observe(Event("superdocs", "instructed", f"job {job_id[:8]}", target.relative))
            else:
                self.observe(Event("superdocs", "reattached", f"job {job_id[:8]}", target.relative))

            job = self.client.poll_job(
                job_id,
                timeout=self.config.superdocs.job_timeout_seconds,
                poll_interval=self.config.superdocs.poll_interval_seconds,
            )

        except SuperDocsAuthError:
            # Never retried and never degraded past: a bad key will not fix itself, and continuing
            # would report a repository as locally clean when it was never really checked.
            raise
        except SuperDocsSessionBusy as exc:
            note = f"session busy: {exc}"
            self.observe(Event("superdocs", "skip", note, target.relative))
            state = state.with_degraded("a session was still busy; some documents were skipped")
            return state, [], 0, False
        except (SuperDocsJobTimeout, SuperDocsJobFailed) as exc:
            note = str(exc)
            self.observe(Event("superdocs", "failed", note, target.relative))
            state = state.with_degraded(f"{target.relative}: {note}")
            return state, [], 0, False
        except SuperDocsError as exc:
            note = f"SuperDocs unavailable ({exc}); local rules only"
            self.observe(Event("superdocs", "degrade", note, target.relative))
            state = state.with_degraded(note)
            return state, [], 0, False
        finally:
            state = state.with_stage_time(SUPERDOCS_CHECK, time.monotonic() - stage_started)

        outcome = findings_from_job(
            job,
            document=document,
            chunk_ids=chunk_ids,
            severity=self.config.severity_for(STYLE_GUIDE_RULE, Severity.WARNING),
            unanchored_severity=self.config.severity_for(UNANCHORED_RULE, Severity.WARNING),
        )

        # When the job did complete, the service's own figure is authoritative and may exceed one.
        # It is only trusted for a job this run started, so a reattached job is not billed twice.
        ops = outcome.ops_charged if (ops_spent_now and outcome.ops_charged) else ops_spent_now

        if outcome.refused:
            # Completed, billed, and produced nothing it could explain. Not a clean document.
            note = "SuperDocs could not act on the lint instruction"
            self.observe(Event("superdocs", "failed", note, target.relative))
            state = state.with_degraded(f"{target.relative}: {note}")
            return state, [], ops, False

        if outcome.discarded:
            self.observe(
                Event(
                    "superdocs",
                    "discarded",
                    f"{len(outcome.discarded)} proposal(s) pointed outside this document",
                    target.relative,
                )
            )

        if outcome.findings:
            self.observe(
                Event(
                    "gate",
                    "escalate",
                    f"{len(outcome.findings)} proposal(s) awaiting human review",
                    target.relative,
                )
            )
            file_state = file_state.advanced(Stage.AWAITING_REVIEW)
            state = state.with_file(file_state)
            self.store.save(state)

        return state, outcome.findings, ops, True

    # -- finishing ------------------------------------------------------------------

    def _finish(
        self,
        state: RunState,
        file_state: FileState,
        verdict: Verdict,
        *,
        findings: tuple[Finding, ...] = (),
        ops_charged: int = 0,
        seconds: float = 0.0,
        from_cache: bool = False,
    ) -> tuple[RunState, FileResult]:
        # Read the live record rather than trusting the caller's copy. The SuperDocs pass advances
        # and persists its own copy mid-flight (session id, job id), and writing a stale one over
        # the top would erase exactly the two fields that make a resume free and `apply` possible.
        current = state.file(file_state.path) or file_state
        updated = current.advanced(
            Stage.DONE,
            verdict=verdict,
            findings=findings,
            ops_charged=current.ops_charged + ops_charged,
            seconds=seconds,
            from_cache=from_cache,
        )
        state = state.with_file(updated)
        self.store.save(state)
        return state, FileResult(
            path=updated.path,
            verdict=verdict,
            findings=findings,
            from_cache=from_cache,
            seconds=seconds,
            ops_charged=updated.ops_charged,
        )
