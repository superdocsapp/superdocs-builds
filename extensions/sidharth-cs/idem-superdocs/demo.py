#!/usr/bin/env python3
"""Hands-on walkthrough. No API key, no network, no test framework.

Run it and watch what the library does. Every scenario below is a real failure
shape from production, and the fake server counts what it actually did, so the
numbers are measured rather than narrated.

    python3 demo.py            # all scenarios
    python3 demo.py 3          # just scenario 3
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "python"))

from idem import (
    Idempotent, OutcomeUnknown, Policy, RetriesExhausted,
    TerminalFailure, UnknownPolicy, Verdict,
)

W = shutil.get_terminal_size((80, 20)).columns - 2


class Server:
    """A pretend SuperDocs that keeps score of what it really did."""

    def __init__(self):
        self.edits = 0
        self.jobs = {}

    def chat_async(self, key, *, fail=None):
        if fail == "conflict":
            raise err("HTTPStatusError", status=409)
        if fail == "connect":
            raise err("ConnectTimeout", sent=False)
        if fail == "server":
            raise err("HTTPStatusError", status=503)
        self.edits += 1                       # <- the billable, document-changing bit
        job = f"job-{self.edits}"
        self.jobs[job] = {"job_id": job, "status": "completed", "key": key}
        if fail == "timeout":
            raise err("ReadTimeout")          # applied, then the answer vanished
        return self.jobs[job]

    def find(self, key):
        return next((j for j in self.jobs.values() if j["key"] == key), None)


def err(name, *, status=None, sent=True):
    e = type(name, (Exception,), {})(f"{name}")
    e.status, e.sent = status, sent
    return e


def new():
    d = Path(tempfile.mkdtemp())
    return Server(), Idempotent(d / "ops.db", Policy.load("policy.json"), sleep=lambda s: None)


def head(n, title, why):
    print(f"\n\033[1m{n}. {title}\033[0m\n   {why}\n   {'─' * (W - 3)}")


def do(label, fn):
    try:
        print(f"   {label:<46} → {str(fn())[:60]}")
    except Exception as e:
        print(f"   {label:<46} \033[33m→ refused: {type(e).__name__}\033[0m")


def score(server, expected, note=""):
    ok = server.edits == expected
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"\n   {mark} the server applied the edit \033[1m{server.edits}\033[0m time(s). {note}")


# ── 1 ────────────────────────────────────────────────────────────────────────
def one():
    head(1, "The same key, submitted ten times",
         "A user mashes the button. A queue redelivers. A caller has its own retry loop.")
    s, i = new()
    for n in range(10):
        r = i.run("edit-para-7", lambda: s.chat_async("edit-para-7"))
        if n in (0, 9):
            print(f"   call {n + 1:>2} returned                             → {r['job_id']}")
    score(s, 1, "Nine of those ten never touched the network.")


# ── 2 ────────────────────────────────────────────────────────────────────────
def two():
    head(2, "The answer is lost after the edit lands  ← the expensive one",
         "Server applied it. Response died on the way back. Did it happen? Nobody knows.")
    s, i = new()
    do("first call (response lost)", lambda: i.run("k", lambda: s.chat_async("k", fail="timeout")))
    print(f"   state is now: {i.store.state_of('k')}")
    print("\n   Now resubmit it five times, the way a naive retry loop would:")
    for _ in range(5):
        do("retry", lambda: i.run("k", lambda: s.chat_async("k")))
    score(s, 1, "\033[1mThis is the double-charge that does not happen.\033[0m")


# ── 3 ────────────────────────────────────────────────────────────────────────
def three():
    head(3, "Asking the server what actually happened",
         "reconcile() resolves the unknown — without running the operation again.")
    s, i = new()
    do("first call (response lost)", lambda: i.run("k", lambda: s.chat_async("k", fail="timeout")))

    probe = lambda rec: (Verdict.APPLIED, s.find(rec.key)) if s.find(rec.key) else Verdict.NOT_APPLIED
    do("run with on_unknown=RECONCILE",
       lambda: i.run("k", lambda: s.chat_async("k"), on_unknown=UnknownPolicy.RECONCILE, probe=probe))
    print(f"   state is now: {i.store.state_of('k')}")
    score(s, 1, "The caller got its answer. The edit was never repeated.")

    print("\n   And when the server cannot answer (no job id, no probe):")
    s2, i2 = new()
    do("first call (response lost)", lambda: i2.run("k", lambda: s2.chat_async("k", fail="timeout")))
    print(f"   reconcile() with nothing to ask            → {i2.reconcile('k').value}")
    do("run with RECONCILE anyway",
       lambda: i2.run("k", lambda: s2.chat_async("k"), on_unknown=UnknownPolicy.RECONCILE))
    print("   \033[33m'I could not find out' never becomes 'it did not happen'.\033[0m")


# ── 4 ────────────────────────────────────────────────────────────────────────
def four():
    head(4, "Which failures get retried, and which do not",
         "All four decided by policy.json. Nothing here is a conditional in the code.")
    for label, fail, note in [
        ("connect timeout  (never left the client)", "connect", "retried 5x, then gives up"),
        ("read timeout     (sent, no answer)", "timeout", "REFUSED — may have applied"),
        ("HTTP 503         (server got it)", "server", "REFUSED — may have applied"),
        ("HTTP 409         (session wedged)", "conflict", "terminal, not retried once"),
    ]:
        s, i = new()
        try:
            i.run("k", lambda: s.chat_async("k", fail=fail))
            out = "succeeded"
        except (OutcomeUnknown, TerminalFailure, RetriesExhausted) as e:
            out = type(e).__name__
        print(f"   {label:<46} → {out}")
        print(f"   {'':46}   edits={s.edits}, {note}")


# ── 5 ────────────────────────────────────────────────────────────────────────
def five():
    head(5, "Overriding the refusal on purpose",
         "The unsafe path exists — it just cannot be reached by accident.")
    s, i = new()
    do("first call (response lost)", lambda: i.run("k", lambda: s.chat_async("k", fail="timeout")))
    do("RETRY_ANYWAY, no assertion",
       lambda: i.run("k", lambda: s.chat_async("k"), on_unknown=UnknownPolicy.RETRY_ANYWAY))
    print("   ↑ selecting the policy is not enough on its own\n")
    do("RETRY_ANYWAY + naturally_idempotent=True",
       lambda: i.run("k", lambda: s.chat_async("k"),
                     on_unknown=UnknownPolicy.RETRY_ANYWAY, naturally_idempotent=True))
    score(s, 2, "Two edits — because you said so, in two separate arguments.")


# ── 6 ────────────────────────────────────────────────────────────────────────
def six():
    head(6, "Change the policy, change the behaviour — no code edited",
         "The whole point of the table being data. Edit policy.json and rerun this.")
    import json
    raw = json.loads(Path("policy.json").read_text())
    for rule in raw["rules"]:
        if rule["id"] == "conflict":
            rule["outcome"] = "retryable"          # pretend 409 is worth retrying
    s, i = Server(), Idempotent(Path(tempfile.mkdtemp()) / "o.db", Policy(raw), sleep=lambda x: None)
    try:
        i.run("k", lambda: s.chat_async("k", fail="conflict"))
    except Exception as e:
        print(f"   409 reclassified as retryable              → {type(e).__name__}")
    print("   (5 attempts instead of 1 — exactly the six-minute loop from the bug report)")
    print("\n   \033[33mNo Python was edited to change that. One field in one JSON file.\033[0m")


SCENARIOS = [one, two, three, four, five, six]

if __name__ == "__main__":
    print("\n\033[1midem-superdocs — hands-on demo\033[0m")
    print("no API key, no network. the fake server counts what it really did.")
    picked = [SCENARIOS[int(a) - 1] for a in sys.argv[1:]] or SCENARIOS
    for fn in picked:
        fn()
    print(f"\n   {'─' * (W - 3)}\n   policy.json is the decision table. Edit it and rerun.\n")
