"""Read the whole document back and decide what actually happened.

Three classes, and the third is the dangerous one:

- **NOT APPLIED** - the target chunk came back unchanged. This is the
  2026-08-07 corrupted-document mechanism: the change silently does not land and
  the caller executes its consequences anyway.
- **APPLIED WRONG** - the target changed, but not to the post-state we computed
  before sending.
- **COLLATERAL DAMAGE** - a chunk we did not target moved, appeared or vanished.
  Measured on 2026-08-09: one requested change *succeeded* while four fabricated
  sections appeared alongside it, and again when a template instantiation kept
  the table and silently deleted the letterhead. A verifier that checked only its
  own target would have reported success both times.

So the comparison is over the **whole document**, every time, including on a
retry - failed content has been observed arriving a turn later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..chunks import ChunkMap, canonical


@dataclass
class Problem:
    kind: str  # not_applied | applied_wrong | collateral_damage
    detail: str
    diff: str = ""


@dataclass
class Verification:
    step_index: int
    chunk_id: str
    problems: list[Problem] = field(default_factory=list)
    receipt: str = ""
    exact_bytes: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    def report(self) -> str:
        if self.ok:
            return f"step {self.step_index}: ok - {self.receipt}"
        lines = [f"step {self.step_index}: FAILED on chunk {self.chunk_id}"]
        for problem in self.problems:
            lines.append(f"  {problem.kind.upper().replace('_', ' ')}: {problem.detail}")
            if problem.diff:
                lines.append(problem.diff)
        return "\n".join(lines)


def verify(
    step_index: int,
    chunk_id: str,
    before: ChunkMap,
    after: ChunkMap,
    expected_html: str,
) -> Verification:
    result = Verification(step_index=step_index, chunk_id=chunk_id)
    expected = canonical(expected_html)

    before_ids = before.ids
    after_ids = after.ids
    added = [i for i in after_ids if i not in set(before_ids)]
    removed = [i for i in before_ids if i not in set(after_ids)]
    if added or removed:
        result.problems.append(
            Problem(
                "collateral_damage",
                f"the chunk set changed: {len(before_ids)} chunk(s) before, {len(after_ids)} "
                f"after; {len(added)} added, {len(removed)} removed. A replacement never "
                f"changes the chunk set.",
                diff="\n".join(
                    f"    + {after.by_id[i].tag}: {after.by_id[i].html[:120]}" for i in added[:6]
                )
                + "\n".join(f"    - {i}" for i in removed[:6]),
            )
        )
    moved = [
        i
        for i in before_ids
        if i
        and i != chunk_id
        and i in after.by_id
        and after.by_id[i].canonical != before.by_id[i].canonical
    ]
    if moved:
        result.problems.append(
            Problem(
                "collateral_damage",
                f"{len(moved)} chunk(s) we did not target changed: {moved[:6]}",
                diff="\n".join(
                    f"    was: {before.by_id[i].html[:150]}\n    now: {after.by_id[i].html[:150]}"
                    for i in moved[:3]
                ),
            )
        )

    if chunk_id not in after.by_id:
        result.problems.append(
            Problem("not_applied", f"the target chunk {chunk_id} is not in the read-back at all")
        )
        return result

    was = before.by_id[chunk_id].canonical
    now = after.by_id[chunk_id].canonical
    if now == was:
        result.problems.append(
            Problem(
                "not_applied",
                "the target chunk came back byte-identical to what it held before. The chat "
                "reply is not evidence and is not consulted here.",
                diff=f"    unchanged: {before.by_id[chunk_id].html[:200]}",
            )
        )
    elif now != expected:
        result.problems.append(
            Problem(
                "applied_wrong",
                "the target chunk changed, but not to the post-state computed before sending",
                diff=_diff(expected, now),
            )
        )
    else:
        result.exact_bytes = _strip_id(after.by_id[chunk_id].html) == _strip_id(expected_html)
        result.receipt = (
            f"read back {len(after_ids)} chunk(s) from GET /v1/documents/"
            f"{{id}}?include_html=true; target chunk {chunk_id} matches the computed "
            f"post-state{' byte for byte' if result.exact_bytes else ' (canonical form)'}; "
            f"{len(after_ids) - 1} non-target chunk(s) unchanged"
        )
    return result


def _strip_id(html: str) -> str:
    from ..chunks import strip_chunk_ids

    return strip_chunk_ids(html)


def _diff(expected: str, actual: str) -> str:
    import difflib

    lines = list(
        difflib.unified_diff(
            expected.split(">"), actual.split(">"), "expected", "actual", lineterm="", n=1
        )
    )
    return "\n".join(f"    {line}" for line in lines[:24])


def verify_upload_verbatim(uploaded: ChunkMap, sent_blocks: list[str]) -> str:
    """The upload is only useful if it is verbatim, so that is checked, not assumed.

    Decision 29 rests entirely on `upload-base64` being a verbatim load. It was
    measured once; it is re-checked on every run, because a design resting on a
    measured property should re-measure it rather than remember it.
    """
    ours = [canonical(block) for block in sent_blocks]
    theirs = [chunk.canonical for chunk in uploaded.chunks]
    if ours != theirs:
        mismatch = next(
            (i for i, (a, b) in enumerate(zip(ours, theirs, strict=False)) if a != b),
            min(len(ours), len(theirs)),
        )
        raise AssertionError(
            f"the upload was not verbatim: we sent {len(ours)} block(s) and {len(theirs)} came "
            f"back, first difference at block {mismatch}.\n"
            f"  sent: {ours[mismatch] if mismatch < len(ours) else '(nothing)'}\n"
            f"  got : {theirs[mismatch] if mismatch < len(theirs) else '(nothing)'}\n"
            f"Decision 29 rests on the upload being verbatim; if it is not, the whole "
            f"skeleton approach is unsound and the run stops here rather than editing a "
            f"document that is not the one we computed."
        )
    return f"upload verified verbatim: {len(theirs)} chunk(s), every block canonically identical"
