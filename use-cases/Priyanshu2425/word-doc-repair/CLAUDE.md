# Working on this build

**Read [BASELINE.md](BASELINE.md) before changing behaviour.** It states what
this system does as numbered invariants (B1–B26), and today's behaviour is the
contract rather than a starting point.

The rule agreed with the owner on 2026-08-26:

> The current implementation is the primary baseline. Later work **adds** to it.
> Anything new that cannot run must fall back to one of the paths already there,
> rather than replace it.

So, before writing code:

1. Find the invariant the change touches.
2. If the change keeps every invariant true, build it.
3. If it would make one false, **stop and say so** — name the invariant, explain
   what would break, and let the owner make the call explicitly. Do not resolve
   it quietly, and do not treat "it seems small" as an exemption. A request can
   read as a tweak and still land on B1 or B18.

Two failure modes this project has already paid for, both worth naming:

- **Wiring cut, implementation left behind.** Three separate regressions
  (BUG-088, BUG-095, BUG-097) were the same shape: the correct code survived and
  only its caller was removed, so nothing failed loudly. Before concluding a
  capability is missing, check whether it exists and is merely unreferenced.
- **Believing the code's own description of itself.** The docstrings called the
  styling pass a "ceiling, not a floor" for weeks while the brief called it the
  deliverable. Ground product claims in `/TASK_CONTEXT/` and the SuperDocs docs,
  not in the comments of the thing you are reading.

Process rules for the wider repository — PROGRESS.md, BUGS.md, checkpointing —
are in `/TASK_CONTEXT/TASK.md` and still apply here.
