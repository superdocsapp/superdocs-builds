"""
Memo Grounding Validator.

Validates generated memo content against authoritative workflow state:
- ProductFacts
- RulingFacts
- matched_ruling_ids
- reconciliation conflicts
- retrieved evidence

Detects:
- contradictions with explicit product facts
- contradictions with ruling facts
- unsupported classification assertions
- unsupported "no ruling" statements
- placeholder values
- missing source attribution
- fabricated ruling identifiers
"""

import re
from typing import Any, Dict, List, Optional
from backend.modules.tariff.memo_types import (
    ProductFacts,
    RulingFacts,
    MemoSectionOutput,
    Recommendation,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Placeholder patterns (generic, no fixture-specific values)
PLACEHOLDER_PATTERNS = [
    r"\[(?:TODO|TBD|PLACEHOLDER|INSERT|FILL\s*IN|XXX|FIXME|YOUR|ENTER).*?\]",
    r"<(?:TODO|TBD|PLACEHOLDER|INSERT|FILL\s*IN|XXX|FIXME|YOUR|ENTER).*?>",
    r"\bPLACEHOLDER\b",
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bXXX\b",
    r"\bFIXME\b",
    r"\bINSERT\s+\w+\s+HERE\b",
    r"\bFILL\s+IN\b",
]

# Internal / meta AI phrases that should not appear in professional analyst memos
PROHIBITED_META_AI_PATTERNS = [
    r"(?i)\bthis section is drafted\b",
    r"(?i)\bthe description focuses\b",
    r"(?i)\bhas been excluded to adhere to\b",
    r"(?i)\bthe analysis evaluated\b",
    r"(?i)\bthe workflow\b",
    r"(?i)\bthe model\b",
    r"(?i)\bsection focus requirements\b",
    r"(?i)\bintentionally excluding\b",
    r"(?i)\bi have synthesized\b",
    r"(?i)\bas requested by the section focus\b",
    r"(?i)\bin this section (?:we|i|the analyst) (?:will|have|aim to)\b",
    r"(?i)\bas an ai\b",
    r"(?i)\bthe product overview is drafted to\b",
    r"(?i)\bthis section covers\b",
    r"(?i)\bthis section provides\b",
    r"(?i)^\s*reasoning\s*:\s*$",
]


def sanitize_memo_text(content: str, analyst_reasoning: str = "") -> tuple[str, str]:
    """
    Clean and sanitize memo content and analyst reasoning.

    1. Removes orphan 'Reasoning:' or 'Analyst Reasoning:' standalone headings.
    2. Strips meta AI sentences (e.g. 'This section is drafted to...', 'The description focuses on...').
    3. Cleans duplicate or redundant analyst reasoning matching content.
    4. Strips leading/trailing whitespace and redundant empty lines.
    """
    def _clean_field(text: str) -> str:
        if not text:
            return ""
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Drop standalone reasoning / section labels
            if re.match(r"^(?:Analyst\s+)?Reasoning\s*:\s*$", stripped, re.IGNORECASE):
                continue
            if re.match(r"^Section\s+Focus\s*:\s*$", stripped, re.IGNORECASE):
                continue
            # Remove meta-AI sentences from line
            cleaned_line = line
            for pattern in PROHIBITED_META_AI_PATTERNS:
                # Replace sentence matching meta pattern if present
                if pattern != r"(?i)^\s*reasoning\s*:\s*$":
                    cleaned_line = re.sub(pattern + r"[^.!?\n]*(?:[.!?]|$)", "", cleaned_line)
            cleaned_line = re.sub(r"\s+", " ", cleaned_line).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        return "\n\n".join(cleaned_lines).strip()

    clean_content = _clean_field(content)
    clean_reasoning = _clean_field(analyst_reasoning)

    # Strip redundant prefix if reasoning begins with 'Reasoning:'
    clean_reasoning = re.sub(r"^(?:Analyst\s+)?Reasoning\s*:\s*", "", clean_reasoning, flags=re.IGNORECASE).strip()

    # If reasoning is identical to content or empty after cleaning, set to empty
    if clean_reasoning.lower() == clean_content.lower() or len(clean_reasoning) < 5:
        clean_reasoning = ""

    return clean_content, clean_reasoning


class GroundingViolation:
    """Represents a single grounding violation."""

    def __init__(
        self,
        category: str,
        severity: str,
        message: str,
        section_type: Optional[str] = None,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.category = category
        self.severity = severity  # "error" or "warning"
        self.message = message
        self.section_type = section_type
        self.field = field
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "section_type": self.section_type,
            "field": self.field,
            "details": self.details,
        }


class MemoGroundingValidator:
    """Validates memo content against authoritative workflow state."""

    def __init__(self):
        self.placeholder_regex = re.compile(
            "|".join(f"(?:{p})" for p in PLACEHOLDER_PATTERNS),
            re.IGNORECASE,
        )

    def validate_section(
        self,
        section_output: MemoSectionOutput,
        section_type: str,
        product_facts: Optional[ProductFacts],
        ruling_facts: List[RulingFacts],
        matched_ruling_ids: List[str],
        reconciliation_conflicts: List[Dict[str, Any]],
        retrieved_evidence: List[Dict[str, Any]],
    ) -> List[GroundingViolation]:
        """
        Validate a single memo section against authoritative state.

        Args:
            section_output: Generated section from LLM
            section_type: Section type (e.g., "product_description")
            product_facts: Authoritative product facts
            ruling_facts: List of extracted ruling facts
            matched_ruling_ids: IDs of matched rulings from reconciliation
            reconciliation_conflicts: Conflicts detected during reconciliation
            retrieved_evidence: Retrieved evidence chunks

        Returns:
            List of grounding violations
        """
        violations: List[GroundingViolation] = []

        # Check for placeholder text
        violations.extend(
            self._check_placeholders(section_output, section_type)
        )

        # Check product fact consistency
        if product_facts:
            violations.extend(
                self._check_product_fact_consistency(
                    section_output, section_type, product_facts
                )
            )

        # Check ruling fact consistency
        if ruling_facts:
            violations.extend(
                self._check_ruling_consistency(
                    section_output,
                    section_type,
                    ruling_facts,
                    matched_ruling_ids,
                    product_facts=product_facts,
                )
            )

        # Check unsupported "no ruling" statements
        violations.extend(
            self._check_unsupported_no_ruling(
                section_output, section_type, ruling_facts, matched_ruling_ids
            )
        )

        # Check recommendation grounding
        if section_output.recommendation:
            section_text = (section_output.content or "") + " " + (section_output.analyst_reasoning or "")
            violations.extend(
                self._check_recommendation_grounding(
                    section_output.recommendation,
                    section_type,
                    product_facts,
                    ruling_facts,
                    matched_ruling_ids,
                    section_text=section_text,
                )
            )

        # Check for meta AI language
        violations.extend(
            self._check_meta_ai_language(section_output, section_type)
        )

        # Check source attribution
        violations.extend(
            self._check_source_attribution(section_output, section_type)
        )

        return violations

    def _check_meta_ai_language(
        self, section: MemoSectionOutput, section_type: str
    ) -> List[GroundingViolation]:
        """Detect internal AI/process meta language in generated content."""
        violations = []
        for field_name in ["content", "analyst_reasoning"]:
            text = getattr(section, field_name, None)
            if not text:
                continue

            for pattern in PROHIBITED_META_AI_PATTERNS:
                match = re.search(pattern, text)
                if match:
                    violations.append(
                        GroundingViolation(
                            category="meta_ai_language",
                            severity="warning",
                            message=f"Section {field_name} contains internal AI process language: '{match.group(0)}'",
                            section_type=section_type,
                            field=field_name,
                            details={"matched_phrase": match.group(0)},
                        )
                    )
        return violations

    def _check_placeholders(
        self, section: MemoSectionOutput, section_type: str
    ) -> List[GroundingViolation]:
        """Check for unresolved placeholder text."""
        violations = []

        placeholder_patterns = [
            r"\[(?:TODO|TBD|INSERT|PLACEHOLDER|SPECIFY|UNKNOWN)\]",
            r"\b(?:TODO|TBD)\b",
            r"\[\.\.\.\]",
            r"\{\{[^}]+\}\}",
        ]

        for field_name in ["content", "analyst_reasoning"]:
            text = getattr(section, field_name, None)
            if not text:
                continue

            for pattern in placeholder_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    violations.append(
                        GroundingViolation(
                            category="placeholder_content",
                            severity="error",
                            message=f"Unresolved placeholder detected in {field_name}: {matches[0]}",
                            section_type=section_type,
                            field=field_name,
                            details={"placeholders": matches},
                        )
                    )

        return violations

    def _check_product_fact_consistency(
        self,
        section: MemoSectionOutput,
        section_type: str,
        product_facts: ProductFacts,
    ) -> List[GroundingViolation]:
        """Check for contradictions with product facts."""
        violations = []

        content_text = section.content + " " + section.analyst_reasoning
        content_lower = content_text.lower()

        # Check material composition consistency
        if product_facts.material_composition:
            authoritative_material = product_facts.material_composition.lower()

            # Compile all text across all product facts fields to allow full context grounding
            all_product_text = " ".join(
                str(val) for val in [
                    product_facts.product_name,
                    product_facts.manufacturer,
                    product_facts.model,
                    product_facts.material_composition,
                    product_facts.functional_characteristics,
                    product_facts.physical_characteristics,
                    product_facts.construction,
                    product_facts.intended_use,
                    product_facts.packaging,
                    product_facts.manufacturing_process,
                    product_facts.dimensions,
                    product_facts.weight,
                ] if val
            ).lower()

            common_materials = [
                "aluminum",
                "plastic",
                "steel",
                "iron",
                "copper",
                "rubber",
                "glass",
                "wood",
                "paper",
                "textile",
                "ceramic",
            ]

            # Common compound interface/electrical component patterns that are not chassis/enclosure claims
            interface_patterns = [
                r"\bcopper\s+(?:ethernet\s+)?(?:interfaces?|ports?|cables?|cabling|connections?|connectors?|wiring|traces?|links?|phys?|transceivers?)\b",
                r"\bcopper\s+(?:ethernet|port|interface|port[s]?|cable|cabling|wiring|traces|gigabit|link|sfp|transceiver|connectivity|connection[s]?)\b",
                r"\b(?:1|10|25|40|100)\s*(?:gbe|gbps|mbps)\s+copper\b",
                r"\bdual\s+(?:\d+\s+gbe\s+)?copper\b",
                r"\bcopper\s+(?:conductors?|coils?|pins?|contacts?|bus|busbars?|windings?|leads?|tracks?)\b",
                r"\bprinted\s+circuit\b",
                r"\bpcba?\b",
            ]

            for material in common_materials:
                # Use word-boundary regex to prevent partial-substring false positives (e.g. 'iron' in 'environmental')
                mat_regex = rf"\b{re.escape(material)}\b"
                if re.search(mat_regex, content_lower):
                    # 1. Check if the material is supported in material_composition or its synonyms
                    synonyms = self._get_material_synonyms(material)
                    has_synonym = any(
                        re.search(rf"\b{re.escape(syn)}\b", authoritative_material) for syn in synonyms
                    )

                    # 2. Check if the material is supported anywhere in other authoritative ProductFacts fields
                    in_other_facts = any(
                        re.search(rf"\b{re.escape(syn)}\b", all_product_text) for syn in synonyms
                    )

                    # 3. Check if all occurrences in the content correspond to non-enclosure interface / component usage
                    is_interface_usage = False
                    if material == "copper":
                        copper_matches = list(re.finditer(mat_regex, content_lower))
                        interface_match_spans = []
                        for ip in interface_patterns:
                            for m in re.finditer(ip, content_lower):
                                interface_match_spans.append((m.start(), m.end()))

                        all_matches_in_interface = True
                        for cm in copper_matches:
                            cm_start, cm_end = cm.start(), cm.end()
                            if not any(span_start <= cm_start and cm_end <= span_end for span_start, span_end in interface_match_spans):
                                all_matches_in_interface = False
                                break
                        is_interface_usage = all_matches_in_interface and len(copper_matches) > 0

                    if not (has_synonym or in_other_facts or is_interface_usage):
                        violations.append(
                            GroundingViolation(
                                category="product_fact_conflict",
                                severity="error",
                                message=(
                                    f"Memo mentions '{material}' but ProductFacts "
                                    f"states material is '{product_facts.material_composition}'"
                                ),
                                section_type=section_type,
                                field="material_composition",
                                details={
                                    "authoritative_material": product_facts.material_composition,
                                    "conflicting_material": material,
                                },
                            )
                        )

        return violations

    def _check_ruling_consistency(
        self,
        section: MemoSectionOutput,
        section_type: str,
        ruling_facts: List[RulingFacts],
        matched_ruling_ids: List[str],
        product_facts: Optional[ProductFacts] = None,
    ) -> List[GroundingViolation]:
        """Check for contradictions with ruling facts and invalid ruling references."""
        violations = []

        content_text = section.content + " " + section.analyst_reasoning

        # Find mentioned ruling numbers using precise customs ruling formats and contextual ruling references
        cbp_pattern = r"\b(?:HQ|NY)\s*[A-Z]?\d{4,}\b|\bN\d{6}\b"
        agency_pattern = r"\b(?:NCR|CBP|WCO|BTI|UKCA|EUBTI)-[A-Z0-9]+(?:-[A-Z0-9]+)+\b"
        year_pattern = r"\b[A-Z]{2,5}-[A-Z0-9]+-(?:19|20)\d{2}-[A-Z0-9]+\b"
        context_pattern = r"(?i)\b(?:ruling|decision|precedent)\s*(?:#|no\.?|number)?\s*([A-Za-z0-9]{2,}(?:-[A-Za-z0-9]+)+)\b"

        mentioned_ruling_numbers = set()
        for m in re.findall(cbp_pattern, content_text, re.IGNORECASE):
            mentioned_ruling_numbers.add(m.strip())
        for m in re.findall(agency_pattern, content_text, re.IGNORECASE):
            mentioned_ruling_numbers.add(m.strip())
        for m in re.findall(year_pattern, content_text, re.IGNORECASE):
            mentioned_ruling_numbers.add(m.strip())
        for m in re.findall(context_pattern, content_text):
            mentioned_ruling_numbers.add(m.strip())

        # Exclude known product model numbers from candidate rulings to prevent false positives
        known_models = set()
        if product_facts and product_facts.model:
            known_models.add(re.sub(r"[\s\-_]", "", product_facts.model).upper())
        for r in ruling_facts:
            if r.product_description:
                for mod in re.findall(r"(?i)\b(?:model|type|unit)\s*[:#]?\s*([A-Z0-9]+(?:-[A-Z0-9]+)+)\b", r.product_description):
                    known_models.add(re.sub(r"[\s\-_]", "", mod).upper())

        # Collect valid ruling numbers and document IDs
        valid_ruling_numbers = [
            r.ruling_number for r in ruling_facts if r.ruling_number
        ]
        valid_document_ids = [
            str(r.document_id) for r in ruling_facts if r.document_id
        ] + [str(mid) for mid in matched_ruling_ids if mid]
        valid_normalized = {
            re.sub(r"[\s\-_]", "", r).upper() for r in valid_ruling_numbers
        }
        valid_doc_ids_set = {
            str(d).lower().strip() for d in valid_document_ids if d
        }

        uuid_regex = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

        if mentioned_ruling_numbers:
            for mentioned in mentioned_ruling_numbers:
                mentioned_norm = re.sub(r"[\s\-_]", "", mentioned).upper()
                if mentioned_norm in known_models:
                    continue

                # Check if this matches a known ruling document UUID
                if uuid_regex.match(mentioned):
                    if mentioned.lower() in valid_doc_ids_set:
                        continue
                    # If it's a UUID not in ruling facts document IDs, flag as invalid reference
                    violations.append(
                        GroundingViolation(
                            category="invalid_ruling_reference",
                            severity="error",
                            message=(
                                f"Memo references ruling document '{mentioned}' which was not "
                                f"found in extracted ruling facts"
                            ),
                            section_type=section_type,
                            field="content",
                            details={
                                "mentioned_ruling": mentioned,
                                "valid_rulings": valid_ruling_numbers,
                                "valid_document_ids": valid_document_ids,
                            },
                        )
                    )
                    continue

                if mentioned_norm not in valid_normalized and mentioned.lower() not in valid_doc_ids_set:
                    violations.append(
                        GroundingViolation(
                            category="invalid_ruling_reference",
                            severity="error",
                            message=(
                                f"Memo references ruling '{mentioned}' which was not "
                                f"found in extracted ruling facts"
                            ),
                            section_type=section_type,
                            field="content",
                            details={
                                "mentioned_ruling": mentioned,
                                "valid_rulings": valid_ruling_numbers,
                            },
                        )
                    )

        # Check classification consistency
        for ruling in ruling_facts:
            if ruling.document_id in matched_ruling_ids and ruling.applicable_classification:
                hs_pattern = r"\b\d{4}\.\d{2}(?:\.\d{2,4})?\b"
                mentioned_hs_codes = re.findall(hs_pattern, content_text)

                # Extract normalized HS codes from ruling.applicable_classification
                ruling_hs_codes = re.findall(hs_pattern, ruling.applicable_classification)
                # Also strip common classification prefixes like HTX, HTS, HTSUS, HS
                normalized_ruling_class = re.sub(
                    r"^(?:HTX|HTSUS|HTS|HS|CHAPTER|HEADING)\s*",
                    "",
                    ruling.applicable_classification.strip(),
                    flags=re.IGNORECASE,
                )

                has_match = False
                if ruling_hs_codes:
                    has_match = any(r_code in mentioned_hs_codes for r_code in ruling_hs_codes)
                elif normalized_ruling_class in mentioned_hs_codes:
                    has_match = True
                elif ruling.applicable_classification in mentioned_hs_codes:
                    has_match = True

                # This is a warning, not an error, because memo may discuss alternatives
                if mentioned_hs_codes and not has_match:
                    # Only warn if the section is specifically about this ruling
                    if "ruling" in section_type.lower():
                        violations.append(
                            GroundingViolation(
                                category="ruling_conflict",
                                severity="warning",
                                message=(
                                    f"Matched ruling {ruling.ruling_number} classified as "
                                    f"{ruling.applicable_classification}, but memo mentions "
                                    f"different HS codes: {mentioned_hs_codes}"
                                ),
                                section_type=section_type,
                                field="classification",
                                details={
                                    "ruling_classification": ruling.applicable_classification,
                                    "mentioned_codes": mentioned_hs_codes,
                                },
                            )
                        )

        return violations

    def _check_unsupported_no_ruling(
        self,
        section: MemoSectionOutput,
        section_type: str,
        ruling_facts: List[RulingFacts],
        matched_ruling_ids: List[str],
    ) -> List[GroundingViolation]:
        """Check for unsupported 'no ruling exists' statements."""
        violations = []

        content_lower = (section.content + " " + section.analyst_reasoning).lower()

        # Patterns indicating "no ruling"
        no_ruling_patterns = [
            r"no\s+(?:previous\s+)?ruling(?:s)?\s+(?:exist|available|found)",
            r"no\s+relevant\s+ruling",
            r"ruling\s+does\s+not\s+exist",
            r"(?:lack|absence)\s+of\s+ruling",
        ]

        has_no_ruling_statement = any(
            re.search(pattern, content_lower) for pattern in no_ruling_patterns
        )

        if has_no_ruling_statement:
            # If we have matched rulings, this statement is incorrect
            if matched_ruling_ids:
                violations.append(
                    GroundingViolation(
                        category="unsupported_claim",
                        severity="error",
                        message=(
                            f"Memo claims no ruling exists, but {len(matched_ruling_ids)} "
                            f"matched ruling(s) were found in workspace documents"
                        ),
                        section_type=section_type,
                        field="content",
                        details={
                            "matched_ruling_count": len(matched_ruling_ids),
                            "matched_ruling_ids": matched_ruling_ids,
                        },
                    )
                )

        return violations

    def _check_recommendation_grounding(
        self,
        recommendation: Recommendation,
        section_type: str,
        product_facts: Optional[ProductFacts],
        ruling_facts: List[RulingFacts],
        matched_ruling_ids: List[str],
        section_text: str = "",
    ) -> List[GroundingViolation]:
        """Check that recommendation is grounded in facts/rulings."""
        violations = []

        # Check for placeholder HS code
        if not recommendation.hs_code or re.match(r"^[X\*]+", recommendation.hs_code):
            violations.append(
                GroundingViolation(
                    category="unsupported_classification",
                    severity="error",
                    message="Recommended HS code is missing or placeholder",
                    section_type=section_type,
                    field="recommendation.hs_code",
                    details={"hs_code": recommendation.hs_code},
                )
            )

        # Check if recommendation reasoning is empty
        if not recommendation.reasoning or len(recommendation.reasoning.strip()) < 20:
            violations.append(
                GroundingViolation(
                    category="missing_source",
                    severity="error",
                    message="Recommendation reasoning is missing or too brief",
                    section_type=section_type,
                    field="recommendation.reasoning",
                    details={"reasoning_length": len(recommendation.reasoning or "")},
                )
            )

        # If matched rulings exist, recommendation sections (or recommendation reasoning) should reference them
        if matched_ruling_ids and section_type in {"recommended_classification", "executive_summary", "classification_analysis"}:
            matched_ruling_numbers = [
                r.ruling_number for r in ruling_facts if r.document_id in matched_ruling_ids and r.ruling_number
            ]
            combined_reasoning = (recommendation.reasoning or "") + " " + section_text

            # Check if any matched ruling number is cited
            has_matched_ruling_mention = any(
                re.search(rf"\b{re.escape(r_num)}\b", combined_reasoning, re.IGNORECASE)
                for r_num in matched_ruling_numbers
            )
            # Or general ruling/precedent reference
            has_general_ruling_ref = bool(
                re.search(r"(?:HQ|NY|N\d+)\s*[A-Z]?\d+|[A-Z]{2,5}(?:-[A-Z0-9]+){2,}|\b(?:ruling|precedent)s?\b", combined_reasoning, re.IGNORECASE)
            )

            if not (has_matched_ruling_mention or has_general_ruling_ref):
                violations.append(
                    GroundingViolation(
                        category="missing_source",
                        severity="warning",
                        message=(
                            f"Recommendation does not reference matched rulings "
                            f"(found {len(matched_ruling_ids)} matched rulings)"
                        ),
                        section_type=section_type,
                        field="recommendation.reasoning",
                        details={"matched_ruling_count": len(matched_ruling_ids)},
                    )
                )

        return violations

    def _check_source_attribution(
        self, section: MemoSectionOutput, section_type: str
    ) -> List[GroundingViolation]:
        """Check that source attributions are present where required."""
        violations = []

        # Sections that require source attribution
        attribution_required = [
            "relevant_previous_rulings",
            "classification_analysis",
            "recommended_classification",
        ]

        if section_type in attribution_required:
            if not section.source_attribution or len(section.source_attribution) == 0:
                violations.append(
                    GroundingViolation(
                        category="missing_source",
                        severity="warning",
                        message=f"Section '{section_type}' should include source attribution",
                        section_type=section_type,
                        field="source_attribution",
                        details={"attribution_count": 0},
                    )
                )

        return violations

    def _get_material_synonyms(self, material: str) -> List[str]:
        """Get common synonyms and subcategories for materials to avoid false positives."""
        synonyms = {
            "aluminum": ["aluminium", "aluminum", "al", "alloy"],
            "plastic": ["polymer", "synthetic", "polyethylene", "polypropylene", "polycarbonate", "abs", "pc/abs", "pvc", "plastic", "resin", "foam", "elastomer"],
            "steel": ["stainless", "carbon steel", "alloy steel", "steel"],
            "iron": ["ferrous", "cast iron", "wrought iron", "iron"],
            "textile": ["fabric", "cloth", "fiber", "fibre", "yarn", "woven", "knit", "textile", "cotton", "wool", "silk", "polyester", "nylon", "linen", "canvas"],
            "rubber": ["elastomer", "latex", "silicone", "vulcanized", "rubber"],
            "glass": ["fiberglass", "silica", "glass"],
            "wood": ["timber", "lumber", "plywood", "mdf", "hardwood", "softwood", "wood"],
            "paper": ["cardboard", "paperboard", "paper", "pulp"],
            "copper": ["brass", "bronze", "copper", "cu"],
            "ceramic": ["porcelain", "clay", "ceramic", "earthenware", "stoneware"],
        }
        return synonyms.get(material, [material])


def validate_memo_sections(
    memo_sections: Dict[str, MemoSectionOutput],
    product_facts: Optional[ProductFacts],
    ruling_facts: List[RulingFacts],
    matched_ruling_ids: List[str],
    reconciliation_conflicts: List[Dict[str, Any]],
    retrieved_evidence: List[Dict[str, Any]],
) -> List[GroundingViolation]:
    """
    Validate all memo sections against authoritative workflow state.

    Args:
        memo_sections: Dict mapping section_type to MemoSectionOutput
        product_facts: Authoritative product facts
        ruling_facts: List of extracted ruling facts
        matched_ruling_ids: IDs of matched rulings
        reconciliation_conflicts: Conflicts from reconciliation
        retrieved_evidence: Retrieved evidence chunks

    Returns:
        List of all grounding violations across sections
    """
    validator = MemoGroundingValidator()
    all_violations = []

    for section_type, section_output in memo_sections.items():
        violations = validator.validate_section(
            section_output=section_output,
            section_type=section_type,
            product_facts=product_facts,
            ruling_facts=ruling_facts,
            matched_ruling_ids=matched_ruling_ids,
            reconciliation_conflicts=reconciliation_conflicts,
            retrieved_evidence=retrieved_evidence,
        )
        all_violations.extend(violations)

    return all_violations
