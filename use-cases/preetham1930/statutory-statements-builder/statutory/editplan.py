"""The edit plan: one single-target chunk replacement per step, and nothing else.

Every step is a `replace`. There is no other verb (Decision 28), no step targets
a heading (Decision 29 put the headings at their final numbers before upload),
and no step carries more than one chunk (Decision 35). Those three are checked
here, before anything is sent, because a plan that breaks a wire rule should
never reach the wire.

The expected post-state is the **whole chunk's HTML**, not the value inside it
(Decision 37). That is what we compare on read-back, and it is also what we send:
the instruction hands SuperDocs the finished chunk rather than describing an edit
to make.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chunks import ChunkMap, canonical
from .errors import PlanRefusedError
from .skeleton import Block, StatutoryDocument

FORBIDDEN_VERBS = ("create", "insert", "add a", "append", "renumber", "move ", "delete")


@dataclass
class Step:
    index: int
    role: str
    tag: str
    note_number: int | None
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
            f"Do not add any section. Do not change any heading. Do not touch any other "
            f"chunk anywhere in the document.\n\n{self.expected_html}"
        )

    def describe(self) -> str:
        where = f"Note {self.note_number}" if self.note_number else "front matter"
        return f"[{self.index:02d}] replace {self.tag:5s} {self.role:34s} ({where})"


@dataclass
class Plan:
    steps: list[Step]
    document: StatutoryDocument

    def __len__(self) -> int:
        return len(self.steps)

    def sample(self, limit: int | None) -> Plan:
        if limit is None or limit >= len(self.steps):
            return self
        return Plan(self.steps[:limit], self.document)


def build_plan(document: StatutoryDocument) -> Plan:
    # Ordered so that a halt loses the least verified work. Paragraph chunks
    # first, table chunks last: measured on this build's live runs, a whole-table
    # replacement is the one unit the product does not apply reliably - clean
    # once, silently not applied twice, and once wrapped in a <div> nobody asked
    # for. The order changes nothing about what is sent or checked; it changes
    # which failure a reviewer is left holding.
    blocks = sorted(document.editable_changed(), key=lambda b: (b.tag == "table",))
    steps = [
        Step(
            index=index,
            role=block.role,
            tag=block.tag,
            note_number=block.note_number,
            expected_html=block.target,
            was_html=block.skeleton,
        )
        for index, block in enumerate(blocks, start=1)
    ]
    plan = Plan(steps, document)
    assert_plan_is_legal(plan, document)
    return plan


def assert_plan_is_legal(plan: Plan, document: StatutoryDocument) -> None:
    headings = {b.role for b in document.blocks if not b.editable}
    for step in plan.steps:
        if step.verb != "replace":
            raise PlanRefusedError(
                f"step {step.index} uses the verb {step.verb!r}. There is one verb and it is "
                f"replace (Decision 28): the only operation that inserts is also the one "
                f"measured to fabricate sections nobody asked for."
            )
        if step.role in headings or step.tag in ("h1", "h2", "h3"):
            raise PlanRefusedError(
                f"step {step.index} targets {step.role!r}, which is a heading. Headings carry "
                f"the note numbering and are uploaded at their final values (Decision 29); "
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
    back re-ordered fails here rather than quietly editing the wrong chunk.
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


def expected_after(before: ChunkMap, step: Step) -> dict[str, str]:
    """The canonical form of every chunk after this step, computed before sending."""
    expected = {chunk.chunk_id: chunk.canonical for chunk in before.chunks}
    if step.chunk_id not in expected:
        raise PlanRefusedError(
            f"step {step.index} targets chunk {step.chunk_id}, which is not in the document"
        )
    expected[step.chunk_id] = canonical(step.expected_html)
    return expected


def unused(block: Block) -> Block:  # pragma: no cover - keeps the import honest
    return block
