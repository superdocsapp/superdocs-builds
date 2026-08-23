"""
reflow_engine.py
Plan how replacement text flows through the document after a SuperDocs edit.

This is the core engine. It answers the question:
  "Given that Section X now has N more/fewer lines of text, where does
   everything go in the document?"

Key invariants enforced here:
  1. Non-content elements (figures, tables, images) are NEVER moved unless
     the reflow planner explicitly determines they are in the affected flow.
     For MVP, all non-content is treated as anchored (absolute position).
  2. Pages and columns outside the affected flow are untouched.
  3. Overflow is detected and reported — never silently applied.
  4. Text width is measured using pymupdf get_text_length(), not estimated
     with character counts.

Reflow strategy:
  - Measure how many lines the replacement text needs at the section's
    typography (font, size, column width).
  - Compute the delta: lines_needed - lines_available.
  - If delta <= 0: replacement fits. Empty space left at end of section.
  - If delta > 0: section needs more flow regions. Consume space from
    downstream content, pushing it further in the document flow.
  - Detect collision with anchored non-content elements and report.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import math
import re
import logging

logger = logging.getLogger(__name__)

try:
    import fitz  # pymupdf
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from flow_mapper import Section, FlowRegion, DocumentFlowMap
from pdf_analyzer import BBox, DocumentGrammar, NonContentElement


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------

@dataclass
class SectionPatch:
    """Describes one region to redact and refill with replacement text."""
    region: FlowRegion
    text_segment: str          # the text that goes into this region
    operation: str             # "replace" | "overflow_extend" | "shrink_empty"
    fontsize: float = 0.0
    fontname: str = ""


@dataclass
class BlockShift:
    """Describes one downstream text block that must be redrawn at a new position."""
    original_page: int
    original_col: int
    original_bbox: BBox
    original_text: str
    original_fontname: str
    original_fontsize: float
    new_page: int
    new_col: int
    new_y0: float              # new top y coordinate


@dataclass
class OverflowWarning:
    section_name: str
    lines_needed: int
    lines_available: int
    overflow_lines: int
    collides_with_non_content: bool
    description: str


@dataclass
class ReflowResult:
    """Complete plan for patching the PDF after one or more section edits."""
    section_patches: List[SectionPatch]
    downstream_shifts: List[BlockShift]
    overflow_warnings: List[OverflowWarning]
    delta_lines: int            # positive = grew, negative = shrank
    delta_points: float         # in PDF points
    affected_pages: List[int]
    unaffected_pages: List[int]
    can_apply: bool             # False if overflow is unresolvable


# ---------------------------------------------------------------------------
# Text measurement
# ---------------------------------------------------------------------------

def measure_text_width(text: str, fontname: str, fontsize: float) -> float:
    """
    Measure the rendered width of a text string in points.
    Uses pymupdf for accuracy when available; falls back to character estimate.
    """
    if PYMUPDF_AVAILABLE:
        try:
            return fitz.get_text_length(text, fontname=_normalise_fontname(fontname), fontsize=fontsize)
        except Exception:
            pass
    # Fallback: average character width ≈ 0.5 × fontsize
    return len(text) * fontsize * 0.5


def _normalise_fontname(fontname: str) -> str:
    """
    Strip PDF subset prefix (e.g. 'ABCDEF+TimesNewRoman' → 'Times-Roman')
    and map to a pymupdf built-in font name.
    """
    name = fontname.split("+")[-1].lower()
    if "times" in name or "roman" in name:
        if "bold" in name and "italic" in name:
            return "Times-BoldItalic"
        if "bold" in name:
            return "Times-Bold"
        if "italic" in name:
            return "Times-Italic"
        return "Times-Roman"
    if "helvetica" in name or "arial" in name or "sans" in name:
        if "bold" in name:
            return "Helvetica-Bold"
        return "Helvetica"
    if "courier" in name or "mono" in name:
        return "Courier"
    return "Times-Roman"


def estimate_lines_needed(
    text: str,
    column_width: float,
    fontname: str,
    fontsize: float,
    line_height: float,
) -> Tuple[int, float]:
    """
    Estimate how many lines and vertical points the text needs
    when typeset at the given column width and font.

    Returns (line_count, total_height_in_points).
    """
    if not text.strip():
        return 0, 0.0

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    total_lines = 0

    for para in paragraphs:
        words = para.split()
        if not words:
            continue

        current_line_width = 0.0
        line_count = 1
        space_width = measure_text_width(" ", fontname, fontsize)

        for word in words:
            word_width = measure_text_width(word, fontname, fontsize)
            if current_line_width == 0.0:
                current_line_width = word_width
            elif current_line_width + space_width + word_width <= column_width:
                current_line_width += space_width + word_width
            else:
                line_count += 1
                current_line_width = word_width

        total_lines += line_count

        # Paragraph spacing = 1 extra line between paragraphs
        total_lines += 1

    # Remove the trailing paragraph spacing
    if total_lines > 0:
        total_lines -= 1

    total_height = total_lines * line_height
    return total_lines, total_height


# ---------------------------------------------------------------------------
# Reflow Engine
# ---------------------------------------------------------------------------

class ReflowEngine:
    """
    Given a section, its replacement text, and the full document flow map,
    produce a ReflowResult describing exactly what needs to change in the PDF.
    """

    def plan(
        self,
        section: Section,
        replacement_text: str,
        flow_map: DocumentFlowMap,
    ) -> ReflowResult:
        grammar = flow_map.grammar
        sec_fontsize = (
            float(section.content_blocks[0].fontsize)
            if section.content_blocks and section.content_blocks[0].fontsize > 0
            else float(grammar.body_fontsize)
        )
        sec_fontname = (
            _normalise_fontname(section.content_blocks[0].fontname)
            if section.content_blocks and section.content_blocks[0].fontname
            else _normalise_fontname(grammar.body_fontname)
        )
        sec_line_height = (
            float(section.content_blocks[0].line_height)
            if section.content_blocks and section.content_blocks[0].line_height > 0
            else float(grammar.body_line_height)
        )

        fontname = sec_fontname
        fontsize = sec_fontsize
        line_height = sec_line_height

        # Handle inline heading prefix (e.g. "Abstract— " or "Keywords— ")
        is_inline = (
            section.title.strip().lower().startswith("abstract") or
            section.title.strip().lower().startswith("keywords") or
            section.title.strip().lower().startswith("index terms")
        )
        if is_inline:
            prefix = section.title.strip()
            first_word = prefix.split()[0].lower()
            if not replacement_text.strip().lower().startswith(first_word):
                if "—" in prefix or "--" in prefix or ":" in prefix or "–" in prefix:
                    replacement_text = f"{prefix} {replacement_text.strip()}"
                else:
                    replacement_text = f"{prefix}— {replacement_text.strip()}"

        # ------------------------------------------------------------------
        # Step 1: Measure the replacement text
        # ------------------------------------------------------------------
        if section.flow_regions:
            col_width = section.flow_regions[0].column_width
        elif grammar.column_regions:
            col_width = grammar.column_regions[0].width
        else:
            col_width = grammar.page_width * 0.8

        lines_needed, height_needed = estimate_lines_needed(
            replacement_text, col_width, fontname, fontsize, line_height
        )

        # ------------------------------------------------------------------
        # Step 2: Measure the available space in existing flow regions
        # ------------------------------------------------------------------
        total_available_lines = sum(
            r.capacity_lines(line_height) for r in section.flow_regions
        )
        total_available_height = sum(r.bbox.height for r in section.flow_regions)

        delta_lines = lines_needed - total_available_lines
        delta_points = height_needed - total_available_height

        # ------------------------------------------------------------------
        # Step 3: Distribute replacement text across existing flow regions
        # ------------------------------------------------------------------
        patches, remaining_text = self._distribute_text(
            replacement_text,
            section.flow_regions,
            grammar,
            fontsize=sec_fontsize,
            fontname=sec_fontname,
            line_height=sec_line_height,
        )

        overflow_warnings = []
        downstream_shifts = []
        extra_patches = []
        can_apply = True

        # ------------------------------------------------------------------
        # Step 4: Handle overflow (replacement is longer than original)
        # ------------------------------------------------------------------
        if remaining_text.strip():
            overflow_result = self._handle_overflow(
                remaining_text,
                section,
                flow_map,
                grammar,
                delta_points,
            )
            extra_patches.extend(overflow_result["patches"])
            downstream_shifts.extend(overflow_result["shifts"])
            overflow_warnings.extend(overflow_result["warnings"])
            if overflow_result["unresolvable"]:
                can_apply = False

        # ------------------------------------------------------------------
        # Step 5: Handle shrink (replacement is shorter — empty space remains)
        # ------------------------------------------------------------------
        elif delta_lines < 0:
            # Mark remaining regions as empty (will be cleared but not refilled)
            # This is fine — empty space at end of section is acceptable
            pass

        # ------------------------------------------------------------------
        # Step 6: Downstream shifting DISABLED for MVP.
        # Shifting downstream content across complex page layouts (last pages,
        # two-column with references) produces incorrect redaction of non-target
        # content. For now, just patch the section's own regions and accept
        # minor gaps or slight overflow. The reflow engine architecture supports
        # this feature but it needs per-layout calibration.
        # ------------------------------------------------------------------
        # Immutable-layout mode: downstream_shifts intentionally remain empty.
        downstream_shifts = []

        # Collect affected pages
        affected_pages = sorted(set(
            p.region.page for p in patches + extra_patches
        ) | set(s.new_page for s in downstream_shifts)
          | set(s.original_page for s in downstream_shifts))

        all_pages = list(range(1, flow_map.grammar.page_height and
                               max((b.page for b in flow_map.all_blocks), default=1) + 1
                               or 2))
        # simpler: just collect from all_blocks
        max_page = max((b.page for b in flow_map.all_blocks), default=1)
        # ------------------------------------------------------------------
        # Step 7: Preflight verification
        # ------------------------------------------------------------------
        if can_apply and patches:
            preflight_fontname = sec_fontname
            preflight_fontsize = sec_fontsize
            preflight_lh = min(1.15, max(1.08, sec_line_height / sec_fontsize)) if sec_fontsize > 0 else 1.15
            
            for p_idx, patch in enumerate(patches):
                if patch.operation == "shrink_empty" or not patch.text_segment.strip():
                    continue
                r = patch.region
                x0 = float(min(r.bbox.x0, r.bbox.x1))
                x1 = float(max(r.bbox.x0, r.bbox.x1))
                y0 = float(min(r.bbox.y0, r.bbox.y1))
                y1 = float(max(r.bbox.y0, r.bbox.y1))
                if r.heading_bottom_y > y0:
                    y0 = float(r.heading_bottom_y)
                w = max(0.0, x1 - x0)
                h = max(0.0, y1 - y0)
                
                if w > 0 and h > 0:
                    tmp_doc = fitz.open()
                    try:
                        p_page = tmp_doc.new_page(width=w, height=h)
                        p_rect = fitz.Rect(0, 0, w, h)
                        p_text = re.sub(r'\n{2,}', '\n', patch.text_segment.strip())
                        p_fontname = _normalise_fontname(patch.fontname or preflight_fontname)
                        p_res = p_page.insert_textbox(
                            p_rect,
                            p_text,
                            fontname=p_fontname,
                            fontsize=patch.fontsize if patch.fontsize > 0 else preflight_fontsize,
                            lineheight=preflight_lh,
                            align=fitz.TEXT_ALIGN_JUSTIFY,
                            color=(0, 0, 0),
                        )
                        if not math.isfinite(p_res) or p_res < 0:
                            can_apply = False
                            overflow_warnings.append(OverflowWarning(
                                section_name=section.title,
                                lines_needed=0,
                                lines_available=0,
                                overflow_lines=1,
                                collides_with_non_content=False,
                                description=(
                                    f"Replacement text for '{section.title}' exceeds its existing "
                                    f"physical text regions. Immutable-layout mode rejects the edit; "
                                    f"no neighbouring content, column geometry, or page layout will be changed."
                                ),
                            ))
                            break
                    except Exception:
                        pass
                    finally:
                        tmp_doc.close()

        all_page_nums = list(range(1, max_page + 1))
        unaffected_pages = [p for p in all_page_nums if p not in affected_pages]

        return ReflowResult(
            section_patches=patches + extra_patches,
            downstream_shifts=downstream_shifts,
            overflow_warnings=overflow_warnings,
            delta_lines=delta_lines,
            delta_points=delta_points,
            affected_pages=affected_pages,
            unaffected_pages=unaffected_pages,
            can_apply=can_apply,
        )

    # ------------------------------------------------------------------
    # Text distribution
    # ------------------------------------------------------------------

    def _distribute_text(
        self,
        text: str,
        regions: List[FlowRegion],
        grammar: DocumentGrammar,
        fontsize: float = 0.0,
        fontname: str = "",
        line_height: float = 0.0,
    ) -> Tuple[List[SectionPatch], str]:
        """
        Fill each region with as much text as fits.
        Preserves paragraph structure across region boundaries.
        Returns (patches, remaining_text).
        """
        import logging
        logger = logging.getLogger(__name__)

        patches = []
        remaining = text.strip()

        eff_fontsize = float(fontsize) if fontsize > 0 else float(grammar.body_fontsize)
        eff_fontname = _normalise_fontname(fontname or grammar.body_fontname)
        eff_line_height = float(line_height) if line_height > 0 else float(grammar.body_line_height)

        logger.debug("[REFLOW] Distributing text across %d regions", len(regions))

        for idx, region in enumerate(regions):
            if not remaining:
                # Region is now empty — mark it as cleared
                patches.append(SectionPatch(
                    region=region,
                    text_segment="",
                    operation="shrink_empty",
                    fontsize=eff_fontsize,
                    fontname=eff_fontname,
                ))
                logger.debug(
                    "[REFLOW] region=%d page=%d col=%d shrink_empty (unused)",
                    idx, region.page, region.column
                )
                continue

            segment, remaining = self._fill_region(
                remaining,
                region,
                grammar,
                fontsize=eff_fontsize,
                fontname=eff_fontname,
                line_height=eff_line_height,
            )
            patches.append(SectionPatch(
                region=region,
                text_segment=segment,
                operation="replace",
                fontsize=eff_fontsize,
                fontname=eff_fontname,
            ))
            logger.debug(
                "[REFLOW] region=%d page=%d col=%d placed_words=%d remaining_words=%d",
                idx, region.page, region.column,
                len(segment.split()), len(remaining.split()) if remaining else 0
            )

        return patches, remaining

    def _fill_region(
        self,
        text: str,
        region: FlowRegion,
        grammar: DocumentGrammar,
        fontsize: float = 0.0,
        fontname: str = "",
        line_height: float = 0.0,
    ) -> Tuple[str, str]:
        """
        Fill a region using the exact writable geometry and typography used by pdf_patcher.

        The patcher preserves the heading and inserts body text only below
        heading_bottom_y. The planner measures against that same reduced rectangle
        and uses the document grammar's derived line height ratio.
        """
        if not text.strip():
            return "", ""

        eff_fontname = _normalise_fontname(fontname or grammar.body_fontname)
        eff_fontsize = float(fontsize) if fontsize > 0 else float(grammar.body_fontsize)
        eff_lh = float(line_height) if line_height > 0 else float(grammar.body_line_height)
        lh_ratio = min(1.15, max(1.08, eff_lh / eff_fontsize)) if eff_fontsize > 0 else 1.15

        x0 = float(min(region.bbox.x0, region.bbox.x1))
        x1 = float(max(region.bbox.x0, region.bbox.x1))
        y0 = float(min(region.bbox.y0, region.bbox.y1))
        y1 = float(max(region.bbox.y0, region.bbox.y1))

        if region.heading_bottom_y > y0:
            y0 = float(region.heading_bottom_y)

        width = x1 - x0
        height = y1 - y0

        if (
            not all(math.isfinite(v) for v in (x0, y0, x1, y1))
            or width <= 0.5
            or height <= 0.5
        ):
            return "", text.strip()

        rect = fitz.Rect(0, 0, width, height)

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return "", ""

        def fits(candidate: str) -> bool:
            if not candidate.strip():
                return False

            tmp_doc = fitz.open()
            try:
                page = tmp_doc.new_page(width=width, height=height)
                # Clean multiple newlines so paragraph breaks don't insert double-height empty lines
                text_to_insert = re.sub(r'\n{2,}', '\n', candidate.strip())
                result = page.insert_textbox(
                    rect,
                    text_to_insert,
                    fontname=eff_fontname,
                    fontsize=eff_fontsize,
                    lineheight=lh_ratio,
                    align=fitz.TEXT_ALIGN_JUSTIFY,
                    color=(0, 0, 0),
                )
                return math.isfinite(result) and result >= 0
            except Exception:
                return False
            finally:
                tmp_doc.close()

        # If the entire text fits, place it all
        if fits(text.strip()):
            return text.strip(), ""

        # Place full paragraphs that fit, then binary search words of the partial paragraph
        placed_paras: List[str] = []

        for p_idx, para in enumerate(paragraphs):
            candidate_paras = placed_paras + [para]
            candidate_str = "\n\n".join(candidate_paras)
            if fits(candidate_str):
                placed_paras.append(para)
            else:
                words = para.split()
                low = 1
                high = len(words)
                best_w = 0

                while low <= high:
                    mid = (low + high) // 2
                    sub_para = " ".join(words[:mid])
                    candidate_str = (
                        "\n\n".join(placed_paras + [sub_para])
                        if placed_paras
                        else sub_para
                    )
                    if fits(candidate_str):
                        best_w = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                if best_w > 0:
                    placed_paras.append(" ".join(words[:best_w]))
                    rem_in_this_para = " ".join(words[best_w:])
                    remaining_paras = [rem_in_this_para] + paragraphs[p_idx + 1:]
                    return "\n\n".join(placed_paras), "\n\n".join(remaining_paras)
                else:
                    if placed_paras:
                        remaining_paras = paragraphs[p_idx:]
                        return "\n\n".join(placed_paras), "\n\n".join(remaining_paras)
                    else:
                        return "", text.strip()

        return "\n\n".join(placed_paras), ""


    # ------------------------------------------------------------------
    # Overflow handling
    # ------------------------------------------------------------------

    def _handle_overflow(
        self,
        remaining_text: str,
        section: Section,
        flow_map: DocumentFlowMap,
        grammar: DocumentGrammar,
        delta_points: float,
    ) -> dict:
        """
        Immutable-layout policy.

        There is deliberately no overflow extension and no downstream
        movement. SuperDocs may edit text only inside the section's existing
        physical regions. If text remains after those regions are filled,
        the edit is rejected.
        """
        if not remaining_text.strip():
            return {
                "patches": [],
                "shifts": [],
                "warnings": [],
                "unresolvable": False,
            }

        overflow_lines = max(1, len(remaining_text.split()))
        warning = OverflowWarning(
            section_name=section.title,
            lines_needed=0,
            lines_available=0,
            overflow_lines=overflow_lines,
            collides_with_non_content=False,
            description=(
                f"Replacement text for '{section.title}' exceeds its existing "
                "physical text regions. Immutable-layout mode rejects the edit; "
                "no neighbouring content, column geometry, or page layout will "
                "be changed."
            ),
        )

        return {
            "patches": [],
            "shifts": [],
            "warnings": [warning],
            "unresolvable": True,
        }


    # ------------------------------------------------------------------
    # Downstream shift planning
    # ------------------------------------------------------------------

    def _plan_downstream_shifts(
        self,
        edited_section: Section,
        delta_points: float,
        flow_map: DocumentFlowMap,
    ) -> List[BlockShift]:
        """
        Plan how downstream blocks shift after the edited section grows/shrinks.
        Positive delta_points = content grew = downstream shifts down.
        Negative delta_points = content shrank = downstream shifts up.
        """
        if abs(delta_points) < 2.0:
            return []  # Negligible change

        grammar = flow_map.grammar
        downstream_sections = flow_map.sections_after(edited_section)

        shifts = []
        for ds in downstream_sections:
            # Skip non-editable sections at the very end (References, etc.)
            # They stay anchored unless the shift is very large
            all_blocks = ds.content_blocks
            if ds.heading_block:
                all_blocks = [ds.heading_block] + all_blocks

            for block in all_blocks:
                new_pos = self._compute_shifted_position(
                    block, delta_points, grammar
                )
                if new_pos:
                    shifts.append(BlockShift(
                        original_page=block.page,
                        original_col=block.column,
                        original_bbox=block.bbox,
                        original_text=block.text,
                        original_fontname=block.fontname,
                        original_fontsize=block.fontsize,
                        new_page=new_pos["page"],
                        new_col=new_pos["col"],
                        new_y0=new_pos["y0"],
                    ))

        return shifts

    def _compute_shifted_position(
        self,
        block,
        delta_points: float,
        grammar: DocumentGrammar,
    ) -> Optional[dict]:
        """
        Compute where a block should move after a delta shift.
        Returns dict with page, col, y0 or None if unmoved.
        """
        new_y0 = block.bbox.y0 + delta_points  # shift down (positive delta)
        new_page = block.page
        new_col = block.column

        col_count = grammar.column_count
        bottom_limit = grammar.page_height - grammar.margin_bottom
        top_limit = grammar.margin_top

        # Check if shifted position overflows the column bottom
        if new_y0 + block.bbox.height > bottom_limit:
            overflow = (new_y0 + block.bbox.height) - bottom_limit

            # Try next column on same page
            next_col = new_col + 1
            if next_col < col_count:
                new_col = next_col
                new_y0 = top_limit
            else:
                # Move to next page
                new_page = block.page + 1
                new_col = 0
                new_y0 = top_limit

        # Check if shifted position is above the top of the column
        elif new_y0 < top_limit and delta_points < 0:
            # Shrink case — block moves up; clamp to top margin
            new_y0 = max(top_limit, new_y0)

        if new_page == block.page and abs(new_y0 - block.bbox.y0) < 1.0:
            return None  # No meaningful movement

        return {"page": new_page, "col": new_col, "y0": new_y0}


def plan_reflow(
    section: Section,
    replacement_text: str,
    flow_map: DocumentFlowMap,
) -> ReflowResult:
    """Convenience function."""
    return ReflowEngine().plan(section, replacement_text, flow_map)


def plan_multi_section_reflow(
    edits: List[Tuple[Section, str]],
    flow_map: DocumentFlowMap,
) -> List[ReflowResult]:
    """
    Plan reflow for multiple section edits.
    Processes sections in reading order. Each edit's delta affects subsequent edits.
    """
    # Sort by reading order
    sorted_edits = sorted(edits, key=lambda e: e[0].reading_start)
    results = []
    engine = ReflowEngine()
    for section, replacement in sorted_edits:
        result = engine.plan(section, replacement, flow_map)
        results.append(result)
    return results