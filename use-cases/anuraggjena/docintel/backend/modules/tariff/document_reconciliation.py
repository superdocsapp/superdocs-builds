"""
Document Reconciliation for Tariff Workflow.

Matches product specifications with relevant ruling documents
based on extracted facts.
"""

from typing import List, Dict, Optional
from backend.modules.tariff.memo_types import ProductFacts, RulingFacts
from backend.logging_config import get_logger

logger = get_logger(__name__)


class DocumentReconciliation:
    """
    Reconcile product specifications with ruling documents.

    Uses generic matching based on extracted facts without hardcoding
    specific products, materials, or classifications.
    """

    def reconcile(
        self,
        product_facts: Optional[ProductFacts],
        ruling_facts: List[RulingFacts],
    ) -> Dict[str, any]:
        """
        Determine which rulings are relevant to the product.

        Args:
            product_facts: Extracted product facts
            ruling_facts: List of extracted ruling facts from all ruling documents

        Returns:
            Dict with:
                - matched_ruling_ids: List of relevant ruling document IDs
                - match_reasons: Dict mapping ruling_id to match reason
                - conflicts: List of detected conflicts
        """
        if not product_facts or not ruling_facts:
            logger.info("reconciliation_skipped", has_product=bool(product_facts), has_rulings=bool(ruling_facts))
            return {
                "matched_ruling_ids": [],
                "match_reasons": {},
                "conflicts": [],
            }

        matched_ruling_ids = []
        match_reasons = {}
        conflicts = []

        for ruling in ruling_facts:
            match_score, reason = self._calculate_match(product_facts, ruling)

            if match_score > 0:
                ruling_id = ruling.document_id or "unknown"
                matched_ruling_ids.append(ruling_id)
                match_reasons[ruling_id] = reason

                # Check for conflicts
                conflict = self._detect_conflict(product_facts, ruling)
                if conflict:
                    conflicts.append({
                        "ruling_id": ruling_id,
                        "conflict_type": conflict["type"],
                        "description": conflict["description"],
                    })

        logger.info(
            "reconciliation_complete",
            total_rulings=len(ruling_facts),
            matched=len(matched_ruling_ids),
            conflicts=len(conflicts),
        )

        return {
            "matched_ruling_ids": matched_ruling_ids,
            "match_reasons": match_reasons,
            "conflicts": conflicts,
        }

    def _calculate_match(
        self,
        product: ProductFacts,
        ruling: RulingFacts,
    ) -> tuple[int, str]:
        """
        Calculate match score between product and ruling.

        Returns:
            (score, reason) where score > 0 indicates a match
        """
        score = 0
        reasons = []

        # Material composition match
        if product.material_composition and ruling.product_description:
            product_material = product.material_composition.lower()
            ruling_desc = ruling.product_description.lower()

            # Check for shared material keywords
            material_keywords = self._extract_material_keywords(product_material)
            for keyword in material_keywords:
                if keyword in ruling_desc:
                    score += 3
                    reasons.append(f"material '{keyword}' appears in ruling")

        # Product name/description similarity
        if product.product_name and ruling.product_description:
            product_name = product.product_name.lower()
            ruling_desc = ruling.product_description.lower()

            # Check for shared significant words (>3 chars, not common)
            product_words = set(w for w in product_name.split() if len(w) > 3)
            ruling_words = set(ruling_desc.split())
            common_words = product_words & ruling_words

            if common_words:
                score += len(common_words)
                reasons.append(f"shared keywords: {', '.join(list(common_words)[:3])}")

        # Functional characteristics match
        if product.intended_use and ruling.product_description:
            use_lower = product.intended_use.lower()
            ruling_desc = ruling.product_description.lower()

            use_keywords = set(w for w in use_lower.split() if len(w) > 3)
            for keyword in use_keywords:
                if keyword in ruling_desc:
                    score += 2
                    reasons.append(f"use '{keyword}' in ruling")

        # Construction/characteristics overlap
        if product.construction and ruling.product_description:
            construction = product.construction.lower()
            ruling_desc = ruling.product_description.lower()

            construction_words = set(w for w in construction.split() if len(w) > 3)
            for word in construction_words:
                if word in ruling_desc:
                    score += 2
                    reasons.append(f"construction '{word}' in ruling")

        reason_text = "; ".join(reasons[:3]) if reasons else "no match"
        return (score, reason_text)

    def _extract_material_keywords(self, material_text: str) -> List[str]:
        """Extract significant material keywords."""
        # Common materials to look for
        materials = [
            "aluminum", "aluminium", "steel", "plastic", "wood",
            "rubber", "metal", "fiber", "carbon", "titanium",
            "copper", "brass", "iron", "glass", "ceramic",
            "textile", "fabric", "leather", "paper", "cardboard",
        ]

        found = []
        text_lower = material_text.lower()
        for material in materials:
            if material in text_lower:
                found.append(material)

        return found

    def _detect_conflict(
        self,
        product: ProductFacts,
        ruling: RulingFacts,
    ) -> Optional[Dict[str, str]]:
        """
        Detect explicit conflicts between product and ruling.

        Returns:
            Dict with conflict type and description, or None
        """
        # Material conflict: product says X, ruling says Y
        if product.material_composition and ruling.product_description:
            product_materials = self._extract_material_keywords(
                product.material_composition.lower()
            )
            ruling_desc = ruling.product_description.lower()
            ruling_materials = self._extract_material_keywords(ruling_desc)

            # Check if ruling explicitly describes different materials
            if product_materials and ruling_materials:
                if not any(m in ruling_materials for m in product_materials):
                    return {
                        "type": "material_mismatch",
                        "description": (
                            f"Product materials ({', '.join(product_materials)}) "
                            f"differ from ruling materials ({', '.join(ruling_materials)})"
                        ),
                    }

        return None
