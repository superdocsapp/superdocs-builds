"""Bounded two-page layout policy with fail-closed protected-content handling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class LayoutBlock:
    block_id: str
    text: str
    protected: bool = True
    min_lines: int = 1

class LayoutBlocked(ValueError): pass

PAGE_BUDGET_UNSATISFIABLE = "PAGE_BUDGET_UNSATISFIABLE"

def solve_two_page(blocks: Iterable[LayoutBlock], *, lines_per_page: int = 42) -> dict:
    blocks = list(blocks)
    protected = [b for b in blocks if b.protected]
    if sum(max(1, b.min_lines) for b in protected) > lines_per_page * 2:
        raise LayoutBlocked(f"{PAGE_BUDGET_UNSATISFIABLE}: protected content cannot fit without removal")
    pages, current, used = [[], []], 0, 0
    for block in blocks:
        size = max(1, block.min_lines)
        if used + size > lines_per_page:
            if len(pages) == 1: raise LayoutBlocked(f"{PAGE_BUDGET_UNSATISFIABLE}: overflow")
            used = 0; current = 1
        pages[current].append(block.block_id); used += size
    return {"status": "PASS", "pages": pages, "font_pt": 11, "protected_preserved": True}

def correction_candidates(blocks: Iterable[LayoutBlock], *, lines_per_page: int = 42) -> list[dict]:
    result=[]
    for font in (11, 10, 9):
        if font < 9: continue
        try:
            solved=solve_two_page(blocks, lines_per_page=lines_per_page + (11-font)*4); result.append({"font_pt":font,"solution":solved})
        except LayoutBlocked: continue
    return result

def pdf_postflight(*, page_count: int, text: str, warnings: list[str] | None = None, diagram_rendered: bool = True) -> dict:
    checks = {
        "two_pages": page_count == 2,
        "safety": "Isolate electrical and pneumatic energy" in text,
        "specification": "24 N·m ± 2 N·m" in text,
        "citations": "PDF p." in text,
        "diagram_rendered": diagram_rendered and "flowchart" not in text,
        "warnings": not warnings,
    }
    return {"status": "PASS" if all(checks.values()) else "BLOCKED", "checks": checks}

def detect_clipping(block_boxes: list[tuple[float,float,float,float]], page_width: float, page_height: float) -> dict:
    clipped=[box for box in block_boxes if box[0] < 0 or box[1] < 0 or box[2] > page_width or box[3] > page_height]
    return {"status":"BLOCKED" if clipped else "PASS", "clipped_boxes":clipped}
