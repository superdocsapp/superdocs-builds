"""The split, and the proof that it is a split.

`coverage()` reads the parts back and compares them to the master three ways —
blocks, characters, headings — and the service refuses an export that fails.
The split is stateless: `POST /v1/documents/export` takes a raw `html` body with
no session, so each slice exports on its own, with no copies of the master and
nothing mutated.

See use-cases/doc-splitter/README.md § "The completeness check".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from service.blocks import Block, flow, furniture
from service.cutting import Cut, relabel, split_html, text_length


@dataclass(frozen=True, slots=True)
class Part:
    number: int
    title: str
    """First heading in the part, or its first line — shown in the list, used for
    the filename."""
    blocks: list[Block]
    furniture: list[Block] = field(default_factory=list)

    @property
    def html(self) -> str:
        """Furniture first — a header belongs at the top of the part it heads.
        One HTML fragment, taken by the export endpoint directly."""
        return "\n".join(block.html for block in [*self.furniture, *self.blocks])

    @property
    def text(self) -> str:
        return " ".join(block.text for block in self.blocks if block.text)

    @property
    def headings(self) -> int:
        return sum(1 for block in self.blocks if block.heading_level)


@dataclass
class Coverage:
    """Did the parts add up to the master? Three independent checks: block ids
    catch a dropped/repeated block, characters catch text lost *inside* a block,
    headings catch a structural loss that leaves the words intact."""

    complete: bool
    dropped: list[str] = field(default_factory=list)
    duplicated: list[str] = field(default_factory=list)
    master_blocks: int = 0
    part_blocks: int = 0
    master_chars: int = 0
    part_chars: int = 0
    master_headings: int = 0
    part_headings: int = 0
    blocks_cut: int = 0
    """Blocks a marker split in two. The part count exceeds the master's by
    exactly this — expected."""
    headings_cut: int = 0
    """Of those, the ones that were headings — the heading count rises by this,
    also expected."""
    repeated_furniture: int = 0
    """Headers/footers copied into every part — reported separately, never
    counted as duplication."""

    @property
    def summary(self) -> str:
        if self.complete:
            return (
                f"{self.part_blocks} parts-blocks from {self.master_blocks} "
                + (f"({self.blocks_cut} cut mid-paragraph), " if self.blocks_cut else "blocks, ")
                + 
                f"{self.part_headings} headings from {self.master_headings}"
                + (f" ({self.headings_cut} cut)" if self.headings_cut else "")
                + ", "
                f"{self.part_chars} characters — nothing dropped, nothing duplicated."
            )
        faults = []
        if self.dropped:
            faults.append(f"{len(self.dropped)} block(s) missing from every part")
        if self.duplicated:
            faults.append(f"{len(self.duplicated)} block(s) in more than one part")
        if self.master_chars != self.part_chars:
            faults.append(f"{self.master_chars - self.part_chars} characters lost")
        expected_headings = self.master_headings + self.headings_cut
        if self.part_headings != expected_headings:
            missing = expected_headings - self.part_headings
            faults.append(
                f"{missing} heading(s) lost" if missing > 0 else f"{-missing} heading(s) invented"
            )
        return "; ".join(faults) or "the parts do not reconstruct the master"


def normalise(blocks: list[Block], cuts: list[Cut]) -> list[Cut]:
    """The reviewer's marks → the cuts that apply, deduped and in document order.
    A cut at offset 0 of the first block is the document's own start and is
    dropped (it would make an empty first part)."""
    content = flow(blocks)
    position = {block.chunk_id: index for index, block in enumerate(content)}
    seen: dict[tuple[int, int], Cut] = {}
    for cut in cuts:
        index = position.get(cut.chunk_id)
        if index is None:
            continue
        offset = max(0, min(cut.offset, text_length(content[index].html)))
        if index == 0 and offset == 0:
            continue
        seen[(index, offset)] = Cut(chunk_id=cut.chunk_id, offset=offset)
    return [seen[key] for key in sorted(seen)]


def split(blocks: list[Block], cuts: list[Cut]) -> list[Part]:
    """`n` cuts → `n + 1` parts, each beginning where a marker landed. A cut
    inside a block splits it; the halves get their own ids (`relabel`) so the
    coverage check can still count them."""
    content = flow(blocks)
    if not content:
        return []
    page = furniture(blocks)
    applied = normalise(blocks, cuts)
    position = {block.chunk_id: index for index, block in enumerate(content)}

    # Walk the blocks once, opening a new part whenever a cut is reached.
    groups: list[list[Block]] = [[]]
    edges = {(position[cut.chunk_id], cut.offset) for cut in applied}
    for index, block in enumerate(content):
        starts = sorted(offset for where, offset in edges if where == index)
        if not starts:
            groups[-1].append(block)
            continue
        # Cut into pieces first, then name them. A cut at offset 0 is a clean
        # boundary — the block keeps its own id; suffixing regardless broke the
        # parts' id sequence.
        pieces: list[str | None] = []  # None marks "a new part starts here"
        remaining = block.html
        consumed = 0
        for offset in starts:
            before, after = split_html(remaining, offset - consumed)
            if before:
                pieces.append(before)
            pieces.append(None)
            remaining, consumed = after, offset
        if remaining:
            pieces.append(remaining)

        fragments = sum(1 for piece in pieces if piece is not None)
        numbered = 0
        for piece in pieces:
            if piece is None:
                groups.append([])
                continue
            numbered += 1
            suffix = f"#{numbered}" if fragments > 1 else ""
            groups[-1].append(_half(block, piece, suffix))

    parts: list[Part] = []
    for number, group in enumerate(groups, start=1):
        parts.append(
            Part(number=number, title=_title(group, number), blocks=group, furniture=page)
        )
    return parts


def _half(block: Block, html: str, suffix: str) -> Block:
    """One side of a cut block, with its own id when there are two of them."""
    return Block(
        index=block.index,
        chunk_id=block.chunk_id + suffix,
        tag=block.tag,
        html=relabel(html, suffix) if suffix else html,
        part_type=block.part_type,
    )


def _title(blocks: list[Block], number: int) -> str:
    for block in blocks:
        if block.heading_level and block.text:
            return block.text[:80]
    for block in blocks:
        if block.text:
            return block.text[:80]
    return f"Part {number}"


def coverage(blocks: list[Block], parts: list[Part]) -> Coverage:
    """Read the parts back and compare to the master. Recomputed from the parts,
    not from the slicing indices — checking the slicing arithmetic against itself
    would pass for any bug in it."""
    content = flow(blocks)
    master_ids = [block.chunk_id for block in content]

    fragments: dict[str, int] = {}
    exact: dict[str, int] = {}
    for part in parts:
        for block in part.blocks:
            base = block.chunk_id.split("#")[0]
            fragments[base] = fragments.get(base, 0) + 1
            exact[block.chunk_id] = exact.get(block.chunk_id, 0) + 1
    cuts_made = sum(count - 1 for count in fragments.values())
    # A cut inside a heading leaves two <h2> fragments, so the heading count
    # legitimately rises; exact equality reported "-1 heading lost" on a correct
    # split.
    heading_ids = {block.chunk_id for block in content if block.heading_level}
    headings_cut = sum(
        count - 1 for base, count in fragments.items() if base in heading_ids
    )

    report = Coverage(
        complete=False,
        dropped=[chunk_id for chunk_id in master_ids if chunk_id not in fragments],
        duplicated=sorted(chunk_id for chunk_id, count in exact.items() if count > 1),
        master_blocks=len(content),
        part_blocks=sum(len(part.blocks) for part in parts),
        # Raw text-node characters, not Block.text: .text collapses/strips
        # whitespace, so cutting at a space "lost" a character that was still
        # there. text_length is the unit the cut offsets use — conserved by
        # construction.
        master_chars=sum(text_length(block.html) for block in content),
        part_chars=sum(text_length(block.html) for part in parts for block in part.blocks),
        master_headings=sum(1 for block in content if block.heading_level),
        part_headings=sum(part.headings for part in parts),
        blocks_cut=cuts_made,
        headings_cut=headings_cut,
        repeated_furniture=len(furniture(blocks)) * len(parts),
    )
    report.complete = (
        not report.dropped
        and not report.duplicated
        and report.part_blocks == report.master_blocks + report.blocks_cut
        and report.master_chars == report.part_chars
        and report.part_headings == report.master_headings + report.headings_cut
    )
    return report
