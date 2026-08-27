"""Not paying twice for the same edit after a run was interrupted.

Grounded in the documentation rather than in optimism: **SuperDocs has no
idempotency on billable writes.** There is no idempotency key on
`POST /v1/chat/async`, so the same edit instruction sent twice is two
operations and, quite possibly, the same change applied twice. Nothing below us
prevents that, which means the only place it can be prevented is here.

From the research, the failure this exists for, in the words of somebody it
happened to: *"I reran it from nineteen. But I got the boundary wrong — I think
I redid two or three that were already done. Paid for those twice."*

Three states, and the third is the interesting one:

  ``applied``    the call completed and we saw it complete. Never repeated.
  ``in flight``  we sent the call and the process died before we learned the
                 outcome. **Also never repeated** — and reported, because it
                 needs a person. Retrying might be charged twice and might
                 apply the same edit twice; skipping might leave the work
                 undone. There is no safe automatic answer, and inventing one
                 would be this build guessing with somebody's money.
  ``unknown``    never attempted. Do it.

The ledger is content-addressed on what the call *is* — session, step,
instruction and size — rather than on a caller-supplied id, because the caller
who got the boundary wrong was working from ids they assigned themselves.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class State(str, Enum):
    UNKNOWN = "unknown"
    IN_FLIGHT = "in_flight"
    APPLIED = "applied"
    FAILED = "failed"


@dataclass(frozen=True)
class Record:
    key: str
    state: State
    session_id: str = ""
    step_id: str = ""
    ops_charged: int | None = None
    job_id: str = ""
    note: str = ""

    @property
    def repeatable(self) -> bool:
        """Whether sending this call again is safe.

        `FAILED` is repeatable because a call that failed before it was accepted
        was not charged. `IN_FLIGHT` is not, and that is the whole point.
        """
        return self.state in (State.UNKNOWN, State.FAILED)


def operation_key(session_id: str, step_id: str, instruction: str,
                  sections: int) -> str:
    """A stable name for one billable call.

    Over what the call *does*, so a rerun that renumbers its steps still
    recognises work it already paid for. The session is included because the
    same instruction against a different document is a different operation.
    """
    h = hashlib.sha256()
    for part in (session_id, step_id, instruction.strip(), str(sections)):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


class OperationLedger:
    """What this account has already been charged for, and what is unresolved.

    Backed by a file when given one, because the failure it exists for is a
    process that died — a ledger that lives only in memory forgets exactly when
    it is needed. Appended to rather than rewritten, so a second death during a
    write cannot lose earlier lines.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._records: dict[str, Record] = {}
        if self._path and self._path.exists():
            self._load()

    # -- reads -------------------------------------------------------------
    def get(self, key: str) -> Record:
        return self._records.get(key, Record(key=key, state=State.UNKNOWN))

    def records(self) -> list[Record]:
        return list(self._records.values())

    def unresolved(self) -> list[Record]:
        """Calls that were started and whose outcome was never learned.

        These are what a person has to look at. They are surfaced rather than
        cleaned up, because cleaning them up means choosing between paying twice
        and leaving work undone, and that is not our choice to make.
        """
        return [r for r in self._records.values() if r.state is State.IN_FLIGHT]

    # -- writes ------------------------------------------------------------
    def begin(self, key: str, *, session_id: str = "", step_id: str = "") -> Record:
        """Written *before* the call goes out. That ordering is the guarantee.

        If it were written afterwards, a process that died mid-call would leave
        no trace of the call at all, and the rerun would repeat it — which is
        the exact failure this module exists to prevent.
        """
        return self._put(Record(key=key, state=State.IN_FLIGHT,
                                session_id=session_id, step_id=step_id))

    def applied(self, key: str, *, ops_charged: int | None = None,
                job_id: str = "") -> Record:
        prior = self.get(key)
        return self._put(Record(key=key, state=State.APPLIED,
                                session_id=prior.session_id, step_id=prior.step_id,
                                ops_charged=ops_charged, job_id=job_id))

    def failed(self, key: str, note: str = "") -> Record:
        """The call was never accepted, so it was never charged.

        Only for failures that *prove* the request never reached the platform.
        A failure that merely means we never heard the answer is a different
        thing and must stay `IN_FLIGHT` -- see `never_learned`.
        """
        prior = self.get(key)
        return self._put(Record(key=key, state=State.FAILED,
                                session_id=prior.session_id,
                                step_id=prior.step_id, note=note))

    def never_learned(self, key: str, note: str = "") -> Record:
        """The call may have been accepted, and we never found out.

        A read timeout, a dropped connection mid-response, a 5xx from a gateway
        that had already passed the request on: in every one of those the edit
        may be applied and the operation may be charged. Marking them `FAILED`
        makes them repeatable, and repeating them is the double-billing this
        module exists to prevent -- so they stay `IN_FLIGHT` and are reported
        to a person, exactly like a run that died mid-call.
        """
        prior = self.get(key)
        return self._put(Record(
            key=key, state=State.IN_FLIGHT, session_id=prior.session_id,
            step_id=prior.step_id, job_id=prior.job_id,
            note=note or "the call was sent and its outcome was never learned",
        ))

    def resolve(self, key: str, *, applied: bool, note: str = "") -> Record:
        """A person looked at the document and told us what happened."""
        prior = self.get(key)
        return self._put(Record(
            key=key, state=State.APPLIED if applied else State.FAILED,
            session_id=prior.session_id, step_id=prior.step_id,
            job_id=prior.job_id,
            note=note or "resolved by a person after an interrupted run",
        ))

    # -- storage -----------------------------------------------------------
    def _put(self, record: Record) -> Record:
        self._records[record.key] = record
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**asdict(record),
                                     "state": record.state.value}) + "\n")
        return record

    def _load(self) -> None:
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                raw["state"] = State(raw["state"])
                # Later lines win: the file is an append-only log, so the last
                # word about a key is the current one.
                self._records[raw["key"]] = Record(**raw)
            except (ValueError, TypeError, KeyError):
                # A half-written final line is what an interrupted run leaves
                # behind. Skipping it loses nothing a complete line did not
                # already say; refusing to open the file would lose everything.
                continue
