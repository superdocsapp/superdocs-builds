"""Variable detection and semantic role inference with document-aware extraction."""

import re
from collections import Counter
from typing import Optional

from superdocs_template_inference.models import DocumentProfile, Document
from superdocs_template_inference.models.document import ParagraphBlock, TableBlock

_COMMON_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "he", "her", "his", "in", "is", "it", "its", "of", "on", "or", "our", "she",
    "that", "the", "their", "them", "there", "they", "this", "to", "we", "were",
    "with", "you", "your", "us", "i", "me", "my", "mine", "was", "will", "would",
    "all", "about", "after", "before", "between", "into", "over", "under", "through",
    "during", "while", "than", "then", "more", "most", "some", "such", "same", "out",
    "off", "up", "down", "also", "just", "not", "no", "yes", "but", "if", "so",
    "too", "very", "much", "many", "make", "made", "offer", "letter", "employment",
    "acceptance", "conditions", "benefits", "details", "work", "welcome", "company",
    "date", "time", "service", "document", "addition", "aboard", "acquisition",
    "affecting", "appropriate", "assistance", "based", "behalf", "support", "value",
    "views", "impact", "people", "issues", "annual", "local", "regional", "global",
    "business"
}

_GENERIC_SECTION_WORDS = {
    "offer", "letter", "employment", "acceptance", "position", "role", "company",
    "technologies", "details", "conditions", "benefits", "welcome", "team", "date",
    "time", "work", "your", "we", "you", "our", "there", "they", "their", "document",
    "support", "service"
}

_FIELD_CONTEXT_HINTS = {
    "name", "email", "phone", "mobile", "telephone", "tel", "title", "role", "position",
    "manager", "supervisor", "reporting", "department", "team", "division",
    "salary", "compensation", "package", "bonus", "benefit", "location", "address",
    "city", "state", "country", "office", "remote", "hybrid", "start", "joining",
    "hire", "commencement", "work", "mode", "type", "level", "employee", "candidate",
    "status", "contract", "period", "approval", "benefits"
}

# Semantic field name mapping: canonical variable names for different contexts
_SEMANTIC_FIELD_MAPPING = {
    # Common field labels -> canonical variable names (multi-value for context-dependent mapping)
    "name": {
        "offer": "candidate_name",
        "onboarding": "employee_name",
        "default": "name"
    },
    "candidate name": "candidate_name",
    "candidate_name": "candidate_name",
    "employee name": "employee_name",
    "employee_name": "employee_name",
    "employee id": "employee_id",
    "emp id": "employee_id",
    "id": "employee_id",
    "email": "candidate_email",
    "candidate email": "candidate_email",
    "candidate_email": "candidate_email",
    "employee email": "employee_email",
    "email address": "candidate_email",
    "phone": "candidate_phone",
    "candidate phone": "candidate_phone",
    "phone number": "candidate_phone",
    "mobile": "candidate_phone",
    "telephone": "candidate_phone",
    "address": "candidate_address",
    "candidate address": "candidate_address",
    "job title": "job_title",
    "position": "job_title",
    "designation": "job_title",
    "role": "job_title",
    "department": "department",
    "team": "department",
    "division": "department",
    "level": "employee_level",
    "employee level": "employee_level",
    "grade": "employee_level",
    "manager": {
        "offer": "reporting_manager",
        "onboarding": "manager_name",
        "default": "manager_name"
    },
    "reporting manager": "reporting_manager",
    "supervisor": "reporting_manager",
    "manager name": "manager_name",
    "manager title": "manager_title",
    "manager_title": "manager_title",
    "start date": "joining_date",
    "joining date": "joining_date",
    "commencement date": "joining_date",
    "employment type": "employment_type",
    "employment_type": "employment_type",
    "type of employment": "employment_type",
    "work location": "work_location",
    "location": "work_location",
    "office": "work_location",
    "work mode": "work_mode",
    "mode": "work_mode",
    "work mode / location": "work_mode",
    "relocation": "relocation_required",
    "relocation required": "relocation_required",
    "date": {
        "offer": "offer_date",
        "onboarding": "letter_date",
        "default": "letter_date"
    },
    "offer date": "offer_date",
    "offer_date": "offer_date",
    "letter date": "letter_date",
    "letter_date": "letter_date",
    "offer expiry date": "offer_expiry_date",
    "expiry date": "offer_expiry_date",
    "offer expiry": "offer_expiry_date",
    "reference": "offer_reference",
    "offer reference": "offer_reference",
    "annual ctc": "annual_ctc",
    "ctc": "annual_ctc",
    "annual salary": "annual_ctc",
    "monthly salary": "monthly_salary",
    "salary": {
        "offer": "annual_ctc",
        "onboarding": "monthly_salary",
        "default": "monthly_salary"
    },
    "probation": "probation_period",
    "probation period": "probation_period",
    "probation_period": "probation_period",
    "hr representative": "hr_representative",
    "hr_representative": "hr_representative",
    "hr contact": "hr_representative",
    "hr_contact": "hr_representative",
    "hr title": "hr_title",
    "hr_title": "hr_title",
    "pto": "pto_days",
    "pto days": "pto_days",
    "pto_days": "pto_days",
    "leave": "pto_days",
    "first day": "first_day_time",
    "first day time": "first_day_time",
    "first_day_time": "first_day_time",
    "arrival": "first_day_time",
    "arrival time": "first_day_time",
    "start time": "first_day_time",
    "orientation date": "orientation_date",
    "orientation_date": "orientation_date",
    "orientation time": "orientation_time",
    "orientation_time": "orientation_time",
    "orientation location": "orientation_location",
    "orientation_location": "orientation_location",
    "training program": "training_program",
    "training_program": "training_program",
    "training": "training_program",
    "hr contact name": "hr_contact_name",
    "hr_contact_name": "hr_contact_name",
    "hr contact email": "hr_contact_email",
    "hr_contact_email": "hr_contact_email",
    "special equipment": "special_equipment_required",
    "special equipment required": "special_equipment_required",
    "equipment": "equipment",
    "equipment_required": "special_equipment_required",
}

_VALUE_LIKE_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b"),
    re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b"),
    re.compile(r"^\$\d|\d+\s*(usd|eur|gbp|inr)$", re.IGNORECASE),
    re.compile(r"^(true|false|yes|no|remote|office|hybrid|full-time|part-time|permanent|temporary)$", re.IGNORECASE),
)


def _normalize_token(value: str) -> str:
    """Normalize a token from vocabulary or heading text."""
    if value is None:
        return ""
    token = str(value).strip().lower()
    token = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", token)
    return token


def _normalize_field_label(label: str) -> str:
    """Normalize field label for matching (lowercase, strip punctuation)."""
    if not label:
        return ""
    normalized = label.strip().lower()
    # Remove trailing colons, asterisks, etc.
    normalized = re.sub(r"[:\*\s]+$", "", normalized)
    return normalized


def _infer_document_context(profiles: list[DocumentProfile], documents_by_id: dict[str, Document] = None) -> str:
    """Infer document type context (offer or onboarding) from profiles and documents.

    Returns "offer", "onboarding", or None if uncertain.
    """
    if not profiles:
        return None

    # Strategy 1: Check actual documents for distinguishing variables
    if documents_by_id:
        offer_indicators = 0
        onboarding_indicators = 0

        for doc in list(documents_by_id.values())[:3]:  # Sample first 3 docs
            if not isinstance(doc, Document):
                continue
            # Check for distinguishing content
            text_content = []
            for block in doc.blocks:
                if isinstance(block, ParagraphBlock):
                    text_content.append(block.text.lower())

            full_text = " ".join(text_content)

            # Offer-specific patterns
            if any(word in full_text for word in ["offer letter", "salary", "annual ctc", "offer reference", "ctc"]):
                offer_indicators += 1
            if any(word in full_text for word in ["offer expiry", "acceptance of this offer"]):
                offer_indicators += 2

            # Onboarding-specific patterns
            if any(word in full_text for word in ["onboarding letter", "welcome", "first day", "orientation", "employee id"]):
                onboarding_indicators += 1
            if any(word in full_text for word in ["welcome to", "employee onboarding", "your first day"]):
                onboarding_indicators += 2

        if offer_indicators > onboarding_indicators:
            return "offer"
        if onboarding_indicators > offer_indicators:
            return "onboarding"

    # Strategy 2: Check heading texts in profiles (fallback)
    all_headings = []
    for profile in profiles:
        if hasattr(profile, 'content') and hasattr(profile.content, 'heading_texts'):
            all_headings.extend(profile.content.heading_texts)

    heading_text = " ".join(all_headings).lower()

    if any(word in heading_text for word in ["employment offer", "offer letter", "salary"]):
        return "offer"
    if any(word in heading_text for word in ["onboarding", "welcome", "orientation", "employee id"]):
        return "onboarding"

    # Strategy 3: Check section titles
    all_sections = set()
    for profile in profiles:
        if hasattr(profile, 'sections'):
            for section in profile.sections:
                if hasattr(section, 'title') and section.title:
                    all_sections.add(section.title.lower())

    section_text = " ".join(all_sections).lower()
    offer_section_count = sum(1 for word in ["position", "compensation", "ctc", "salary", "offer"] if word in section_text)
    onboard_section_count = sum(1 for word in ["orientation", "equipment", "first day", "onboarding"] if word in section_text)

    if offer_section_count > onboard_section_count:
        return "offer"
    if onboard_section_count > offer_section_count:
        return "onboarding"

    # Default fallback - check if there are any section texts that might help
    all_section_texts = []
    for profile in profiles:
        if hasattr(profile, 'content') and hasattr(profile.content, 'section_texts'):
            all_section_texts.extend(profile.content.section_texts)

    if all_section_texts:
        section_content = " ".join(all_section_texts).lower()
        if "offer" in section_content or "salary" in section_content or "compensation" in section_content:
            return "offer"
        if "onboarding" in section_content or "orientation" in section_content or "welcome" in section_content:
            return "onboarding"

    # Last resort: if almost empty, return None
    return None



def _map_field_label_to_variable(label: str, document_context: Optional[str] = None) -> Optional[str]:
    """Map a field label to canonical variable name using semantic mapping.

    Args:
        label: Field label from document (e.g., "Employee Name", "Job Title")
        document_context: Context hint ("offer" or "onboarding" if known)

    Returns:
        Canonical variable name or None if no mapping found
    """
    if not label:
        return None

    normalized_label = _normalize_field_label(label)

    # Direct lookup
    if normalized_label in _SEMANTIC_FIELD_MAPPING:
        mapping = _SEMANTIC_FIELD_MAPPING[normalized_label]
        # Handle context-dependent mappings
        if isinstance(mapping, dict):
            # Use document context if available, fallback to default
            if document_context and document_context in mapping:
                return mapping[document_context]
            return mapping.get("default")
        return mapping

    # Fuzzy matching for slight variations
    for key, value in _SEMANTIC_FIELD_MAPPING.items():
        if isinstance(value, dict):
            continue  # Skip context-dependent ones for now
        # Check if label contains or is contained by key
        if key in normalized_label or normalized_label in key:
            if len(normalized_label) >= 3:  # Avoid matching too short labels
                return value

    return None


def _extract_table_field_values(document: Document) -> dict[str, list[str]]:
    """Extract field:value pairs from tables in document.

    Returns dict mapping field_label -> [values]
    """
    field_values: dict[str, list[str]] = {}

    for block in document.blocks:
        if not isinstance(block, TableBlock):
            continue

        # Two-column table: first column is labels, second is values
        if block.num_cols == 2 and block.num_rows > 0:
            for row in block.rows:
                if len(row) >= 2:
                    label = row[0].strip()
                    value = row[1].strip()
                    if label and value:
                        canonical_var = _map_field_label_to_variable(label, None)
                        if canonical_var:
                            if canonical_var not in field_values:
                                field_values[canonical_var] = []
                            field_values[canonical_var].append(value)

        # Multi-column table: look for header row + data rows
        elif block.num_cols >= 2 and block.num_rows > 1:
            # Assume first row is headers
            headers = [h.strip().lower() for h in block.rows[0]]

            # Map headers to canonical variables
            col_to_var = {}
            for col_idx, header in enumerate(headers):
                canonical_var = _map_field_label_to_variable(header, None)
                if canonical_var:
                    col_to_var[col_idx] = canonical_var

            # Extract values from data rows
            for row in block.rows[1:]:
                for col_idx, var_name in col_to_var.items():
                    if col_idx < len(row):
                        value = row[col_idx].strip()
                        if value:
                            if var_name not in field_values:
                                field_values[var_name] = []
                            field_values[var_name].append(value)

    return field_values


def _extract_paragraph_field_values(document: Document) -> dict[str, list[str]]:
    """Extract field:value pairs from label:value paragraphs.

    Patterns:
        Field Label: value
        Field Label: value1, value2
        Field Label: value (multiline continuation)

    Returns dict mapping field_label -> [values]
    """
    field_values: dict[str, list[str]] = {}

    for block in document.blocks:
        if not isinstance(block, ParagraphBlock):
            continue

        text = block.text.strip()
        if not text or len(text) < 5:
            continue

        # Pattern: "Label: Value" or "Label:Value"
        match = re.match(r"^([^:]+):\s*(.+)$", text)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()

            # Ignore if too short or too long (likely not a field)
            if len(label) < 2 or len(label) > 50:
                continue

            # Skip if label is mostly uppercase (likely a heading/title)
            if label.isupper() and len(label) > 3:
                continue

            # Map to canonical variable
            canonical_var = _map_field_label_to_variable(label, None)
            if canonical_var and value:
                if canonical_var not in field_values:
                    field_values[canonical_var] = []
                field_values[canonical_var].append(value)

    return field_values


def _extract_all_field_values(document: Document) -> dict[str, list[str]]:
    """Extract all field:value pairs from document combining all sources.

    Returns dict mapping canonical_variable_name -> [values]
    """
    all_values: dict[str, list[str]] = {}

    # Extract from tables
    table_values = _extract_table_field_values(document)
    for var_name, values in table_values.items():
        if var_name not in all_values:
            all_values[var_name] = []
        all_values[var_name].extend(values)

    # Extract from paragraphs
    para_values = _extract_paragraph_field_values(document)
    for var_name, values in para_values.items():
        if var_name not in all_values:
            all_values[var_name] = []
        all_values[var_name].extend(values)

    # Deduplicate and sort within each variable
    for var_name in all_values:
        all_values[var_name] = sorted(list(set(all_values[var_name])))

    return all_values


def _token_in_context(token: str, context_text: str) -> bool:
    """Check for token as a standalone word in a context string."""
    if not token or not context_text:
        return False
    return re.search(rf"\b{re.escape(token)}\b", context_text, flags=re.IGNORECASE) is not None


def _has_value_pattern(token: str) -> bool:
    """Return True for tokens with actual value-like structure."""
    return any(pattern.search(token) for pattern in _VALUE_LIKE_PATTERNS)


def _is_name_like(token: str) -> bool:
    """Return True for likely document-value names rather than common vocabulary."""
    if not token or len(token) < 3 or len(token) > 40:
        return False
    if not token.isalpha():
        return False
    if token in _COMMON_WORDS or token in _GENERIC_SECTION_WORDS:
        return False
    if token.endswith(("ing", "ed", "ly", "tion", "ment", "ness")):
        return False
    return True


def _is_noise_candidate(token: str) -> bool:
    """Reject common English words, generic section labels and boilerplate."""
    if not token or len(token) <= 2:
        return True
    if token.isdigit():
        return True
    if token in _COMMON_WORDS:
        return True
    if token in _GENERIC_SECTION_WORDS:
        return True
    if token.endswith(("ing", "ed", "ly", "tion", "ment", "ness")) and token not in {"remote", "office", "hybrid"}:
        return True
    return False


def _context_supports_variable(profile: DocumentProfile, token: str) -> tuple[bool, str]:
    """Return context evidence for a document field candidate."""
    section_titles = [
        (section.title or "").strip() for section in profile.sections if getattr(section, "title", None)
    ]
    context_text = " ".join(profile.content.heading_texts + section_titles).lower()

    if token in _FIELD_CONTEXT_HINTS:
        return True, "token matches field context keyword"

    if _has_value_pattern(token):
        return True, "token matches value-like pattern"

    if _is_name_like(token):
        return True, "token looks like a document-specific value name"

    if context_text:
        context_words = set(re.findall(r"[a-z][a-z-]+", context_text))
        if any(field_word in context_words for field_word in _FIELD_CONTEXT_HINTS) and token not in _GENERIC_SECTION_WORDS:
            return True, "token appears in field-like section context"

    return False, "no contextual evidence for field-like token"


def _candidate_evidence_for_profile(profile: DocumentProfile, token: str) -> list[str]:
    """Return evidence strings explaining why a token is a supported candidate."""
    supported, reason = _context_supports_variable(profile, token)
    if not supported:
        return []

    evidence = [reason]
    section_titles = [
        (section.title or "").strip() for section in profile.sections if getattr(section, "title", None)
    ]
    context_text = " ".join(profile.content.heading_texts + section_titles)
    if context_text:
        evidence.append(f"context={context_text[:120]}")
    if _has_value_pattern(token):
        evidence.append("value_pattern")
    return evidence


def detect_variables(
    profiles: list[DocumentProfile],
    documents_by_id: Optional[dict[str, Document]] = None,
) -> dict[str, dict]:
    """Detect semantic variables using document-aware field extraction.

    When documents are available, extracts actual field labels and values from:
    - Tables (key-value format)
    - Paragraphs (label: value format)

    Falls back to vocabulary-based detection when documents unavailable.

    Args:
        profiles: List of DocumentProfile objects
        documents_by_id: Optional dict mapping document_id -> Document with raw blocks

    Returns:
        Dict mapping {variable_name: {section, values, frequency, confidence, evidence}}
    """
    if len(profiles) < 2:
        return {}

    # Use document-aware extraction if documents available
    if documents_by_id:
        detected_variables: dict[str, set[str]] = {}  # var_name -> set of observed values

        for profile in profiles:
            doc_id = profile.document_id
            if doc_id not in documents_by_id:
                continue

            document = documents_by_id[doc_id]
            field_values = _extract_all_field_values(document)

            # Record all detected field values
            for var_name, values in field_values.items():
                if var_name not in detected_variables:
                    detected_variables[var_name] = set()
                detected_variables[var_name].update(values)

        # Build candidate scores from detected variables
        candidate_scores: dict[str, dict] = {}

        for var_name in sorted(detected_variables.keys()):
            values = sorted(list(detected_variables[var_name]))

            # Count how many documents have this variable
            doc_count = 0
            for profile in profiles:
                doc_id = profile.document_id
                if doc_id not in documents_by_id:
                    continue
                document = documents_by_id[doc_id]
                field_values = _extract_all_field_values(document)
                if var_name in field_values:
                    doc_count += 1

            frequency = doc_count / len(profiles) if len(profiles) > 0 else 0.0

            # High confidence for detected semantic fields
            confidence = 0.9

            candidate_scores[var_name] = {
                "section": "field_detection",
                "values": set(values),
                "frequency": frequency,
                "confidence": confidence,
                "evidence": {"document_field_extraction"},
            }

        # Filter: keep variables present in 2+ documents with reasonable frequency
        filtered_candidates: dict[str, dict] = {}
        for name, info in sorted(candidate_scores.items()):
            # For now, keep if in at least 1 document (conservative filter)
            if info["frequency"] >= (1.0 / len(profiles)) if len(profiles) > 0 else True:
                filtered_candidates[name] = {
                    "section": info["section"],
                    "values": sorted(info["values"]),
                    "frequency": round(info["frequency"], 3),
                    "confidence": round(info["confidence"], 3),
                    "evidence": sorted(list(info["evidence"])),
                }

        return filtered_candidates

    # Fallback: vocabulary-based detection (original behavior)
    candidate_scores: dict[str, dict] = {}

    for profile in profiles:
        for token, _ in sorted(profile.content.vocabulary.items(), key=lambda item: (-item[1], item[0])):
            normalized = _normalize_token(token)
            if not normalized:
                continue
            if _is_noise_candidate(normalized):
                continue

            supported, _ = _context_supports_variable(profile, normalized)
            if not supported:
                continue

            evidence = _candidate_evidence_for_profile(profile, normalized)
            if not evidence:
                continue

            if normalized not in candidate_scores:
                candidate_scores[normalized] = {
                    "section": "unknown",
                    "values": set(),
                    "frequency": 0.0,
                    "confidence": 0.0,
                    "evidence": set(),
                }

            candidate_scores[normalized]["values"].add(normalized)
            candidate_scores[normalized]["evidence"].update(evidence)
            candidate_scores[normalized]["frequency"] = max(
                candidate_scores[normalized]["frequency"],
                1.0 / len(profiles),
            )

            context_score = 0.6 if normalized in _FIELD_CONTEXT_HINTS or _has_value_pattern(normalized) or _is_name_like(normalized) else 0.35
            candidate_scores[normalized]["confidence"] = max(
                candidate_scores[normalized]["confidence"],
                min(1.0, 0.35 + context_score),
            )

    filtered_candidates: dict[str, dict] = {}
    for name, info in sorted(candidate_scores.items(), key=lambda item: (-item[1]["confidence"], item[0])):
        if info["confidence"] < 0.45:
            continue
        filtered_candidates[name] = {
            "section": "heading_or_section_context",
            "values": sorted(info["values"]),
            "frequency": round(info["frequency"], 3),
            "confidence": round(info["confidence"], 3),
            "evidence": sorted(info["evidence"]),
        }

    return filtered_candidates


def infer_semantic_role(variable_name: str, context_words: list[str]) -> str:
    """Infer semantic role for a variable using pattern matching.

    Args:
        variable_name: The variable name or value.
        context_words: Surrounding words for context.

    Returns:
        Semantic role string such as "person_name", "salary", "unknown", etc.
    """
    # Convert to lowercase for matching
    var_lower = variable_name.lower()
    context_lower = " ".join(w.lower() for w in context_words)

    # Email pattern
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", var_lower):
        return "email"

    # Phone pattern
    if re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", var_lower):
        return "phone"

    # Salary/amount pattern (numbers with common currency symbols or context)
    if re.search(r"\$\d+|salary|compensation", context_lower):
        if re.search(r"\d{4,}", var_lower):
            return "salary"

    # Date pattern
    if re.search(
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        var_lower,
    ):
        return "date"

    # ID pattern
    if re.search(r"^[a-z]?_?id$|employee_id|emp_id", var_lower) or re.search(
        r"\d{4,}", var_lower
    ):
        return "employee_id"

    # Person name context (common first/last names in context or title)
    if re.search(r"name|manager|employee|person", context_lower):
        if len(var_lower.split()) <= 2 and not re.search(r"\d", var_lower):
            return "person_name"

    # Organization/department
    if re.search(r"department|team|organization|company|division", context_lower):
        return "department"

    # Job title
    if re.search(r"title|position|role|job", context_lower):
        return "job_title"

    # Work mode
    if re.search(r"remote|on-site|hybrid|work.mode|location", context_lower):
        return "work_mode"

    # Location
    if re.search(r"location|city|office|address|building", context_lower):
        return "location"

    # Manager
    if re.search(r"manager|supervisor|lead", context_lower):
        return "manager"

    # Default: unknown
    return "unknown"


def calculate_variable_frequency(
    variable_name: str,
    profiles: list[DocumentProfile],
    documents_by_id: Optional[dict[str, Document]] = None,
) -> float:
    """Calculate how frequently a variable appears across documents.

    When documents available, counts presence of actual detected field values.
    Otherwise, checks vocabulary presence.

    Args:
        variable_name: The variable name.
        profiles: List of DocumentProfile objects from a single family.
        documents_by_id: Optional dict mapping document_id -> Document

    Returns:
        Frequency as 0.0–1.0.
    """
    if not profiles:
        return 0.0

    if documents_by_id:
        # Count documents where this variable was detected
        count = 0
        for profile in profiles:
            doc_id = profile.document_id
            if doc_id not in documents_by_id:
                continue

            document = documents_by_id[doc_id]
            field_values = _extract_all_field_values(document)

            if variable_name in field_values:
                count += 1

        return count / len(profiles)

    # Fallback to vocabulary check
    count = 0
    for profile in profiles:
        if variable_name.lower() in profile.content.vocabulary:
            count += 1

    return count / len(profiles)


def extract_variable_values(
    variable_candidates: dict[str, dict],
    profiles: list[DocumentProfile],
    documents_by_id: Optional[dict[str, Document]] = None,
) -> dict[str, list[str]]:
    """Extract actual observed values for variable candidates.

    When documents available, returns actual field values extracted from tables/paragraphs.
    Otherwise, returns vocabulary-based values.

    Args:
        variable_candidates: Dict mapping variable names to candidate info.
        profiles: List of DocumentProfile objects.
        documents_by_id: Optional dict mapping document_id -> Document

    Returns:
        Dict mapping {variable_name: [observed values from documents]}.
    """
    variable_values: dict[str, list[str]] = {}

    if documents_by_id:
        # Extract actual field values from documents
        for var_name in variable_candidates.keys():
            all_values = set()

            for profile in profiles:
                doc_id = profile.document_id
                if doc_id not in documents_by_id:
                    continue

                document = documents_by_id[doc_id]
                field_values = _extract_all_field_values(document)

                if var_name in field_values:
                    all_values.update(field_values[var_name])

            # Sort for determinism
            variable_values[var_name] = sorted(list(all_values))
    else:
        # Fallback to vocabulary-based (original behavior)
        for var_name in variable_candidates.keys():
            values = []
            for profile in profiles:
                if var_name.lower() in profile.content.vocabulary:
                    values.append(var_name)
            variable_values[var_name] = sorted(list(set(values)))

    return variable_values


def infer_variable_type(values: list[str]) -> tuple[str, dict]:
    """Infer type from observed values.

    This stays conservative: ordinary words do not become enums, and weakly evidenced
    values remain string unless they clearly match a bounded categorical field.
    """
    if not values:
        return "string", {"is_enum": False}

    cleaned_values = [str(v).strip() for v in values if str(v).strip()]
    if not cleaned_values:
        return "string", {"is_enum": False}

    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    phone_pattern = r"^(\+[\d\s-]*|[\d\s().-]*\d[\d\s().-]*\d[\d\s().-]*\d[\d\s().-]*\d)$"
    date_pattern = r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"
    datetime_pattern = r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}[\s]+\d{1,2}:\d{2}(:\d{2})?$"
    time_pattern = r"^\d{1,2}:\d{2}(:\d{2})?\s?(AM|PM|am|pm)?$"
    currency_pattern = r"^\$[\d,]+\.?\d*$|^[\d,]+\.?\d+\s?(USD|GBP|EUR|INR)$"
    integer_pattern = r"^-?\d+$"
    boolean_values = {"true", "false", "yes", "no", "1", "0"}
    enum_values = {
        "remote", "office", "hybrid", "full-time", "part-time", "permanent",
        "temporary", "contract", "fulltime", "parttime", "on-site", "onsite",
        "off-site", "offsite", "yes", "no", "true", "false"
    }

    unique_values = sorted({str(v).lower() for v in cleaned_values})
    normalized_unique = {str(v).lower() for v in cleaned_values}

    all_emails = all(re.match(email_pattern, str(v)) for v in cleaned_values)
    all_integers = all(re.match(integer_pattern, str(v)) for v in cleaned_values)
    all_datetimes = all(re.match(datetime_pattern, str(v)) for v in cleaned_values)
    all_dates = all(re.match(date_pattern, str(v)) for v in cleaned_values)
    all_times = all(re.match(time_pattern, str(v)) for v in cleaned_values)
    all_currency = all(re.match(currency_pattern, str(v)) for v in cleaned_values)
    all_booleans = all(str(v).lower() in boolean_values for v in cleaned_values)

    all_phones = False
    if len(cleaned_values) > 0:
        has_phone_formatting = any(c in "".join(cleaned_values) for c in "-().+ ")
        all_phones = has_phone_formatting and all(re.match(phone_pattern, str(v)) for v in cleaned_values)

    if all_booleans:
        return "boolean", {"is_enum": True, "enum_values": unique_values}

    if len(normalized_unique) <= 8 and normalized_unique and normalized_unique.issubset(enum_values):
        return "enum", {"is_enum": True, "enum_values": unique_values}

    if all_emails:
        return "email", {"is_enum": False}
    elif all_phones:
        return "phone", {"is_enum": False}
    elif all_datetimes:
        return "datetime", {"is_enum": False}
    elif all_dates:
        return "date", {"is_enum": False}
    elif all_times:
        return "time", {"is_enum": False}
    elif all_currency:
        return "currency", {"is_enum": False}
    elif all_integers:
        return "integer", {"is_enum": False}
    else:
        return "string", {"is_enum": False}


def infer_variable_metadata(
    variable_name: str,
    values: list[str],
    profiles: list[DocumentProfile],
    documents_by_id: Optional[dict[str, Document]] = None,
) -> dict:
    """Infer metadata about a variable.

    Args:
        variable_name: Name of the variable.
        values: List of observed values.
        profiles: List of DocumentProfile objects.
        documents_by_id: Optional dict mapping document_id -> Document

    Returns:
        Dict with metadata: frequency, unique_per_document, etc.
    """
    frequency = calculate_variable_frequency(variable_name, profiles, documents_by_id)

    if documents_by_id:
        # Count unique values per document to determine if unique per document
        docs_with_values = []
        value_counts_per_doc = {}

        for profile in profiles:
            doc_id = profile.document_id
            if doc_id not in documents_by_id:
                continue

            document = documents_by_id[doc_id]
            field_values = _extract_all_field_values(document)

            if variable_name in field_values:
                doc_values = field_values[variable_name]
                docs_with_values.append(doc_id)
                value_counts_per_doc[doc_id] = len(doc_values)

        # Variable is unique_per_document if each document has exactly 1 value
        unique_per_document = len(docs_with_values) > 0 and all(
            count == 1 for count in value_counts_per_doc.values()
        )
    else:
        # Fallback: assume unique if fewer values than documents
        unique_per_document = len(values) <= len(profiles)

    return {
        "frequency": frequency,
        "unique_per_document": unique_per_document,
        "observed_value_count": len(values),
        "observed_in_documents": len(values),
    }


def _normalize_section_title(value: str) -> str:
    """Normalize section titles for deterministic comparison."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _section_text_for_range(document: Document, start_idx: int, end_idx: int) -> str:
    """Collect the text associated with a document section range."""
    if not document or not document.blocks:
        return ""

    start_idx = max(0, int(start_idx))
    end_idx = min(len(document.blocks) - 1, int(end_idx))
    if end_idx < start_idx:
        return ""

    parts: list[str] = []
    for idx in range(start_idx, end_idx + 1):
        block = document.blocks[idx]
        if isinstance(block, ParagraphBlock):
            if block.text:
                parts.append(block.text)
        elif isinstance(block, TableBlock):
            cell_text = [cell for row in block.rows for cell in row if cell]
            if cell_text:
                parts.append(" ".join(cell_text))

    return " ".join(parts).lower()


def _matches_value_in_section(section_text: str, value: str) -> bool:
    """Return True when a value appears within a section's observed content."""
    if not section_text or not value:
        return False

    normalized_value = _normalize_section_title(value)
    if not normalized_value:
        return False

    if normalized_value in section_text:
        return True

    value_tokens = set(re.findall(r"[a-z0-9]+", normalized_value))
    section_tokens = set(re.findall(r"[a-z0-9]+", section_text))
    return bool(value_tokens) and value_tokens.issubset(section_tokens)


def link_variable_to_sections(
    variable_name: str,
    profiles: list[DocumentProfile],
    section_groups: dict,
    documents_by_id: Optional[dict[str, Document]] = None,
) -> list[str]:
    """Determine which sections contain a variable.

    The association is based on actual occurrences within the document block ranges
    of the relevant section boundaries. This avoids broad document-level heuristics.

    Args:
        variable_name: Name of the variable.
        profiles: List of DocumentProfile objects.
        section_groups: Dict of aligned sections from section detection.
        documents_by_id: Optional dict mapping document_id -> Document

    Returns:
        List of section names/patterns containing the variable.
    """
    containing_sections: set[str] = set()

    if documents_by_id:
        for profile in profiles:
            document = documents_by_id.get(profile.document_id)
            if document is None:
                continue

            observed_values = _extract_all_field_values(document).get(variable_name, [])
            if not observed_values:
                continue

            for section in getattr(profile, "sections", []):
                if not getattr(section, "title", None):
                    continue
                section_text = _section_text_for_range(
                    document,
                    getattr(section, "start_block_idx", 0),
                    getattr(section, "end_block_idx", 0),
                )
                if not section_text:
                    continue
                if any(_matches_value_in_section(section_text, value) for value in observed_values):
                    containing_sections.add(_normalize_section_title(section.title))

        return sorted(containing_sections)

    # Conservative fallback: only link when the variable is explicitly part of the section title.
    for profile in profiles:
        for section in getattr(profile, "sections", []):
            title = getattr(section, "title", None)
            if not title:
                continue
            normalized_title = _normalize_section_title(title)
            if normalized_title and variable_name.lower() in normalized_title:
                containing_sections.add(normalized_title)

    return sorted(containing_sections)
