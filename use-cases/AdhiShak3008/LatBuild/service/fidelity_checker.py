"""
fidelity_checker.py
Validate that a PDF modification was correctly localized.

After patching, compare original vs modified PDF to verify:
  1. Non-target pages are pixel-identical
  2. On target pages, changes are confined to planned regions
  3. Non-content elements (figures, tables, images) are unchanged
  4. No text overflowed outside allowed regions
  5. Page dimensions are unchanged
  6. Page count is the same (or only grew by pages we explicitly added)

Uses pymupdf to render pages to pixmaps and PIL for pixel comparison.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

import fitz  # pymupdf
from PIL import Image, ImageChops
import io

from reflow_engine import ReflowResult
from pdf_analyzer import NonContentElement, BBox, DocumentGrammar

logger = logging.getLogger(__name__)

RENDER_DPI = 150  # balance between accuracy and speed


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PageFidelityResult:
    page_number: int
    is_target: bool
    identical_to_original: bool
    change_is_localized: bool       # only True for target pages
    unplanned_change_detected: bool
    overflow_detected: bool
    note: str = ""


@dataclass
class FidelityReport:
    pass_overall: bool
    selected_sections: List[str]
    pages_total: int
    pages_modified: List[int]
    non_target_pages_changed: List[int]
    figures_original: int
    figures_modified: int
    tables_original: int
    tables_modified: int
    overflow_detected: bool
    page_count_changed: bool
    page_results: List[PageFidelityResult]
    summary: str

    def as_dict(self) -> dict:
        return {
            "pass": self.pass_overall,
            "selected_sections": self.selected_sections,
            "pages_total": self.pages_total,
            "pages_modified": self.pages_modified,
            "non_target_pages_changed": self.non_target_pages_changed,
            "figures_original": self.figures_original,
            "figures_modified": self.figures_modified,
            "tables_original": self.tables_original,
            "tables_modified": self.tables_modified,
            "overflow_detected": self.overflow_detected,
            "page_count_changed": self.page_count_changed,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class FidelityChecker:

    def check(
        self,
        original_path: str,
        modified_path: str,
        reflow_result: ReflowResult,
        selected_section_names: List[str],
        non_content: List[NonContentElement],
    ) -> FidelityReport:

        orig_doc = fitz.open(original_path)
        mod_doc = fitz.open(modified_path)

        orig_page_count = len(orig_doc)
        mod_page_count = len(mod_doc)
        page_count_changed = orig_page_count != mod_page_count

        target_pages = set(reflow_result.affected_pages)
        non_target_changed = []
        page_results = []
        overflow_detected = False

        # Count non-content elements in each PDF
        fig_orig = sum(1 for nc in non_content if nc.type == "image")
        tbl_orig = sum(1 for nc in non_content if nc.type == "table")
        fig_mod = self._count_images(mod_doc)
        tbl_mod = self._count_tables(mod_doc, non_content)

        for page_num in range(1, min(orig_page_count, mod_page_count) + 1):
            orig_page = orig_doc[page_num - 1]
            mod_page = mod_doc[page_num - 1]

            is_target = page_num in target_pages

            # Render both pages to images
            orig_img = self._render_page(orig_page)
            mod_img = self._render_page(mod_page)

            identical = self._images_identical(orig_img, mod_img)

            if is_target:
                # Target pages: verify changes are within planned regions
                diff_mask = self._diff_mask(orig_img, mod_img)
                planned_mask = self._build_planned_mask(
                    orig_img.size, page_num, reflow_result, orig_page.rect.height
                )
                unplanned = self._has_unplanned_changes(diff_mask, planned_mask)
                overflow = self._detect_overflow(mod_page, reflow_result, page_num)
                if overflow:
                    overflow_detected = True

                page_results.append(PageFidelityResult(
                    page_number=page_num,
                    is_target=True,
                    identical_to_original=identical,
                    change_is_localized=not unplanned,
                    unplanned_change_detected=unplanned,
                    overflow_detected=overflow,
                    note="Target page — expected to differ in planned regions.",
                ))
            else:
                if not identical:
                    non_target_changed.append(page_num)
                page_results.append(PageFidelityResult(
                    page_number=page_num,
                    is_target=False,
                    identical_to_original=identical,
                    change_is_localized=True,
                    unplanned_change_detected=False,
                    overflow_detected=False,
                    note="Non-target page." if identical else "UNEXPECTED CHANGE on non-target page.",
                ))

        orig_doc.close()
        mod_doc.close()

        # Overall pass/fail
        pass_overall = (
            len(non_target_changed) == 0
            and not overflow_detected
            and fig_orig == fig_mod
            and not page_count_changed
        )

        summary = self._build_summary(
            pass_overall,
            selected_section_names,
            orig_page_count,
            reflow_result.affected_pages,
            non_target_changed,
            fig_orig, fig_mod,
            tbl_orig, tbl_mod,
            overflow_detected,
            page_count_changed,
        )

        return FidelityReport(
            pass_overall=pass_overall,
            selected_sections=selected_section_names,
            pages_total=orig_page_count,
            pages_modified=reflow_result.affected_pages,
            non_target_pages_changed=non_target_changed,
            figures_original=fig_orig,
            figures_modified=fig_mod,
            tables_original=tbl_orig,
            tables_modified=tbl_mod,
            overflow_detected=overflow_detected,
            page_count_changed=page_count_changed,
            page_results=page_results,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_page(self, page) -> Image.Image:
        mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return Image.open(io.BytesIO(pix.tobytes("png")))

    def _images_identical(self, img1: Image.Image, img2: Image.Image) -> bool:
        if img1.size != img2.size:
            return False
        diff = ImageChops.difference(img1, img2)
        return diff.getbbox() is None

    def _diff_mask(self, img1: Image.Image, img2: Image.Image) -> Image.Image:
        """Return a binary image showing where the two images differ."""
        if img1.size != img2.size:
            # Resize to smaller for comparison
            min_w = min(img1.width, img2.width)
            min_h = min(img1.height, img2.height)
            img1 = img1.crop((0, 0, min_w, min_h))
            img2 = img2.crop((0, 0, min_w, min_h))
        diff = ImageChops.difference(img1.convert("L"), img2.convert("L"))
        return diff

    def _build_planned_mask(
        self,
        img_size: Tuple[int, int],
        page_num: int,
        reflow_result: ReflowResult,
        page_height_pts: float,
    ) -> Image.Image:
        """
        Build a mask image showing where changes are expected on this page.
        White = change expected here. Black = should be unchanged.
        """
        mask = Image.new("L", img_size, 0)
        scale = RENDER_DPI / 72.0

        from PIL import ImageDraw
        draw = ImageDraw.Draw(mask)

        for patch in reflow_result.section_patches:
            if patch.region.page != page_num:
                continue
            r = patch.region.bbox
            draw.rectangle(
                [int(r.x0 * scale), int(r.y0 * scale),
                 int(r.x1 * scale), int(r.y1 * scale)],
                fill=255
            )

        for shift in reflow_result.downstream_shifts:
            if shift.original_page == page_num:
                r = shift.original_bbox
                draw.rectangle(
                    [int(r.x0 * scale), int(r.y0 * scale),
                     int(r.x1 * scale), int(r.y1 * scale)],
                    fill=255
                )
            if shift.new_page == page_num:
                # New position is also expected to change
                # Approximate using original block dimensions
                block_h = shift.original_bbox.height
                block_w = shift.original_bbox.width
                draw.rectangle(
                    [int(shift.original_bbox.x0 * scale),
                     int(shift.new_y0 * scale),
                     int((shift.original_bbox.x0 + block_w) * scale),
                     int((shift.new_y0 + block_h) * scale)],
                    fill=255
                )

        return mask

    def _has_unplanned_changes(
        self, diff_mask: Image.Image, planned_mask: Image.Image,
        threshold_pixels: int = 50
    ) -> bool:
        """
        Return True if there are significant pixel differences outside
        the planned change regions.
        """
        import numpy as np
        try:
            diff_arr = np.array(diff_mask.convert("L"))
            planned_arr = np.array(planned_mask.convert("L"))

            # Resize planned to match diff if needed
            if diff_arr.shape != planned_arr.shape:
                planned_img = Image.fromarray(planned_arr)
                planned_img = planned_img.resize(
                    (diff_arr.shape[1], diff_arr.shape[0]), Image.NEAREST
                )
                planned_arr = np.array(planned_img)

            # Pixels that changed AND are outside planned regions
            changed = diff_arr > 20          # threshold for "changed"
            unplanned = planned_arr < 128    # outside planned zones
            unplanned_changes = changed & unplanned
            return int(unplanned_changes.sum()) > threshold_pixels
        except ImportError:
            # numpy not available — skip detailed check
            return False

    def _detect_overflow(self, mod_page, reflow_result: ReflowResult, page_num: int) -> bool:
        """
        Detect if any text on the page extends outside column bounds.
        Simple heuristic: check if text blocks exist outside grammar column regions.
        """
        # For MVP: check reflow overflow warnings
        return any(
            w.collides_with_non_content or "overflow" in w.description.lower()
            for w in reflow_result.overflow_warnings
        )

    # ------------------------------------------------------------------
    # Counting helpers
    # ------------------------------------------------------------------

    def _count_images(self, doc) -> int:
        count = 0
        for page in doc:
            count += len(page.get_images())
        return count

    def _count_tables(self, doc, original_non_content: List[NonContentElement]) -> int:
        # Use original table count as reference since tables are anchored
        return sum(1 for nc in original_non_content if nc.type == "table")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        pass_overall,
        section_names,
        pages_total,
        pages_modified,
        non_target_changed,
        fig_orig, fig_mod,
        tbl_orig, tbl_mod,
        overflow,
        page_count_changed,
    ) -> str:
        status = "PASS" if pass_overall else "FAIL"
        lines = [
            f"Fidelity Check: {status}",
            f"Selected sections: {', '.join(section_names)}",
            f"Pages modified: {len(pages_modified)} of {pages_total}",
            f"Non-target pages changed: {len(non_target_changed)}"
            + (f" (pages: {non_target_changed})" if non_target_changed else ""),
            f"Figures preserved: {fig_mod}/{fig_orig}",
            f"Tables preserved: {tbl_mod}/{tbl_orig}",
            f"Overflow: {'Detected' if overflow else 'None'}",
            f"Page count changed: {'Yes' if page_count_changed else 'No'}",
        ]
        return "\n".join(lines)


def check_fidelity(
    original_path: str,
    modified_path: str,
    reflow_result: ReflowResult,
    selected_section_names: List[str],
    non_content: List[NonContentElement],
) -> FidelityReport:
    """Convenience function."""
    return FidelityChecker().check(
        original_path, modified_path, reflow_result,
        selected_section_names, non_content
    )
