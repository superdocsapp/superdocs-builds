"""The edit plan: one single-target chunk replacement per step, and nothing else.

Every step is a `replace`. There is no other verb (Decision 28), no step targets
a heading (Decision 29 put the clause numbers in before upload), no step targets
a **notice** (INVARIANTS.md B4), and no step carries more than one chunk
(Decision 35). All four are checked here, before anything is sent, because a plan
that breaks a wire rule should never reach the wire.

The expected post-state is the whole chunk's HTML, not the value inside it
(Decision 37). That is what we compare on read-back and it is also what we send:
the instruction hands SuperDocs the finished clause rather than describing an
edit to make. Which matters more here than it did for a set of accounts - a
described edit is an invitation to draft, and drafting is what produced four
invented sections on 2026-08-09.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assemble import Block, Draft
from .chunks import ChunkMap, canonical
from .errors import PlanRefusedError

# Ordered so that a halt loses the least verified work. Measured over Phase 4's
# live runs: a whole-table chunk replacement is the one unit the product does not
# apply reliably. A <ul> has not been measured, so it is treated as being between
# the two. This changes nothing about what is sent or checked; it changes which
# failure a reviewer is left holding (Decision 43, carried over).
TAG_RISK = {"p": 0, "ul": 1, "table": 2}


@dataclass
class Step:
    index: int
    role: str
    tag: str
    clause_number: int | None
    expected_html: str  # what the chunk must hold afterwards (no chunk id)
    was_html: str  # what it holds before
    chunk_id: str = ""  # filled in once the document is uploaded and read back

    @property
    def verb(self) -> str:
        return "replace"

    def instruction(self) -> str:
        """One instruction, one chunk, fully resolved. Nothing is left to plan."""
        return (
            f"Replace the entire contents of the chunk whose data-chunk-id is "
            f"{self.chunk_id} with exactly the following HTML, character for character. "
            f"The chunk must remain a single <{self.tag}> element and keep the same "
            f"data-chunk-id; do not wrap it in a <div> or in any other element. "
            f"Do not add any clause. Do not change any heading. Do not reword anything. "
            f"Do not touch any other chunk anywhere in the document."
            f"\n\n{self.expected_html}"
        )

    def describe(self) -> str:
        where = f"clause {self.clause_number}" if self.clause_number else "front matter"
        return f"[{self.index:02d}] replace {self.tag:5s} {self.role:28s} ({where})"


@dataclass
class Plan:
    steps: list[Step]
    draft: Draft

    def __len__(self) -> int:
        return len(self.steps)

    def sample(self, limit: int | None) -> Plan:
        if limit is None or limit >= len(self.steps):
            return self
        return Plan(self.steps[:limit], self.draft)


def build_plan(draft: Draft) -> Plan:
    blocks = sorted(draft.editable_changed(), key=lambda b: TAG_RISK.get(b.tag, 1))
    steps = [
        Step(
            index=index,
            role=block.role,
            tag=block.tag,
            clause_number=block.clause_number,
            expected_html=block.target,
            was_html=block.skeleton,
        )
        for index, block in enumerate(blocks, start=1)
    ]
    plan = Plan(steps, draft)
    assert_plan_is_legal(plan, draft)
    return plan


def assert_plan_is_legal(plan: Plan, draft: Draft) -> None:
    by_role: dict[str, Block] = {b.role: b for b in draft.blocks}
    for step in plan.steps:
        block = by_role.get(step.role)
        if step.verb != "replace":
            raise PlanRefusedError(
                f"step {step.index} uses the verb {step.verb!r}. There is one verb and it is "
                f"replace (Decision 28): the only operation that inserts is also the one "
                f"measured to fabricate clauses nobody asked for, and an invented clause in a "
                f"power of attorney is a power nobody granted."
            )
        if block is not None and block.is_notice:
            raise PlanRefusedError(
                f"step {step.index} targets {step.role!r}, which is a notice. The counsel-review "
                f"notice and the external-execution notice are uploaded verbatim and are never "
                f"edited: an instruction that touches one is an instruction that could "
                f"paraphrase it (INVARIANTS.md B4)."
            )
        if (block is not None and block.is_heading) or step.tag in ("h1", "h2", "h3"):
            raise PlanRefusedError(
                f"step {step.index} targets {step.role!r}, which is a heading. Headings carry "
                f"the clause numbering and are uploaded at their final values (Decision 29); "
                f"there is no renumbering step to get wrong."
            )
        if step.expected_html == step.was_html:
            raise PlanRefusedError(
                f"step {step.index} ({step.role}) would send a chunk that is already correct. "
                f"An edit that changes nothing cannot be verified by read-back and reads as "
                f"'not applied'."
            )


def bind_chunk_ids(plan: Plan, uploaded: ChunkMap) -> None:
    """Match each step to the chunk it will address, by the bytes we uploaded.

    Matched on canonical content rather than on position, so a document that came
    back re-ordered fails here rather than quietly editing the wrong clause.
    """
    by_canonical: dict[str, list[str]] = {}
    for chunk in uploaded.chunks:
        by_canonical.setdefault(chunk.canonical, []).append(chunk.chunk_id)
    for step in plan.steps:
        key = canonical(step.was_html)
        candidates = by_canonical.get(key, [])
        if len(candidates) != 1:
            raise PlanRefusedError(
                f"step {step.index} ({step.role}) matches {len(candidates)} uploaded chunk(s). "
                f"A single-target edit needs exactly one target; {len(uploaded)} chunks came "
                f"back. Content we uploaded:\n  {step.was_html[:200]}"
            )
        step.chunk_id = candidates[0]
