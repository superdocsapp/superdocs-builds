"""Conditional section and rule inference."""

from __future__ import annotations

from superdocs_template_inference.models import DocumentProfile, Document


def _normalize_condition_value(value: str) -> str:
    """Normalize value strings for deterministic comparison."""
    return " ".join(str(value).strip().lower().split())


def _section_tokens(section_name: str) -> set[str]:
    """Extract normalized token set from a section title for noise filtering."""
    if not section_name:
        return set()
    return {_normalize_condition_value(token) for token in section_name.split()}


def _is_generic_condition_token(token: str) -> bool:
    """Filter obvious section-title noise words from conditional candidates."""
    generic = {
        "section",
        "sections",
        "work",
        "setup",
        "details",
        "summary",
        "information",
        "content",
        "header",
        "document",
        "general",
        "addendum",
        "custom",
        "notes",
        "info",
        "overview",
        "details",
    }
    return token in generic


def _find_best_variable_condition(
    docs_with_section: list[DocumentProfile],
    docs_without_section: list[DocumentProfile],
    variable_values: dict[str, dict] | None,
) -> tuple[str, str, str] | None:
    """Find the best variable-based condition predicting section presence.

    Analyzes actual variable values across documents to find which variable+value
    best predicts whether a section is present.

    Only accepts values that appear in at least 2 distinct documents to prevent
    document-specific singleton identifiers from being used as template conditions.

    Args:
        docs_with_section: Profiles of documents with this section
        docs_without_section: Profiles of documents without this section
        variable_values: Dict mapping {doc_id: {variable_name: [values]}}

    Returns:
        (variable_name, operator, value) if condition found, else None
    """
    if not variable_values:
        return None

    docs_with_ids = {p.document_id for p in docs_with_section}
    docs_without_ids = {p.document_id for p in docs_without_section}

    # Collect all variable names and their values
    all_vars = {}  # var_name -> set of all values seen
    var_by_doc = {}  # doc_id -> {var_name: [values]}

    for doc_id, doc_vars in variable_values.items():
        var_by_doc[doc_id] = {}
        for var_name, values in doc_vars.items():
            if var_name not in all_vars:
                all_vars[var_name] = set()
            if isinstance(values, list):
                var_by_doc[doc_id][var_name] = values
                all_vars[var_name].update(values)
            else:
                var_by_doc[doc_id][var_name] = [values]
                all_vars[var_name].add(values)

    # Build document frequency map: for each variable=value, count distinct docs
    # This helps identify singleton identifiers (appear in only one doc)
    var_value_doc_count = {}  # (var_name, value) -> distinct document count
    for doc_id, doc_vars in var_by_doc.items():
        for var_name, values in doc_vars.items():
            for value in values:
                key = (var_name, value)
                if key not in var_value_doc_count:
                    var_value_doc_count[key] = set()
                var_value_doc_count[key].add(doc_id)

    best_score = 0.0
    best_condition = None

    # For each variable and each value it takes, check if it predicts section
    for var_name, all_values in all_vars.items():
        for value in all_values:
            if value is None:
                continue

            # CRITICAL FILTER: Reject document-specific singleton values.
            # A value must appear in at least 2 distinct documents to be
            # considered for a reusable template condition.
            key = (var_name, value)
            distinct_doc_count = len(var_value_doc_count.get(key, set()))
            if distinct_doc_count < 2:
                continue

            # Count how many documents with/without section have this variable=value
            with_count = 0
            with_total = len(docs_with_section)
            for doc_id in docs_with_ids:
                if doc_id in var_by_doc:
                    doc_var_vals = var_by_doc[doc_id].get(var_name, [])
                    if value in doc_var_vals:
                        with_count += 1

            without_count = 0
            without_total = len(docs_without_section)
            for doc_id in docs_without_ids:
                if doc_id in var_by_doc:
                    doc_var_vals = var_by_doc[doc_id].get(var_name, [])
                    if value in doc_var_vals:
                        without_count += 1

            # Calculate how well this variable=value predicts section presence
            with_ratio = with_count / with_total if with_total else 0.0
            without_ratio = without_count / without_total if without_total else 0.0

            # Only consider if reasonably discriminative
            if with_ratio < 0.4 or without_ratio > 0.2:
                continue

            # Score combining presence in with-sections and absence in without-sections
            score = (0.6 * with_ratio) + (0.4 * (1.0 - without_ratio))

            if score > best_score and score > 0.55:
                best_score = score
                best_condition = (var_name, "equals", str(value))

    return best_condition


def infer_conditional_rules(
    profiles: list[DocumentProfile],
    optional_sections: list[str],
    section_groups: dict[str, list] | None = None,
    variable_values: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Infer conditional rules for optional sections.

    A section is only promoted to conditional when an observed field/value pattern
    is repeated in documents containing the section and absent from those without it.

    Args:
        profiles: List of DocumentProfile objects
        optional_sections: List of optional section names
        section_groups: Optional semantic section grouping
        variable_values: Optional dict mapping {doc_id: {var_name: [values]}} for variable-aware inference
    """
    conditional_rules: dict[str, dict] = {}

    if not optional_sections or len(profiles) < 2:
        return conditional_rules

    for section_name in sorted(set(optional_sections), key=lambda s: s.lower()):
        docs_with_section = []
        docs_without_section = []

        # If section_groups is provided, use it to find documents with semantic sections
        if section_groups:
            # Convert output form (spaces) to internal form (underscores) for lookup
            section_pattern = section_name.replace(" ", "_")
            sections_for_pattern = section_groups.get(section_pattern, [])

            # Build set of document IDs that have this semantic section
            docs_with_this_section = set()
            for section in sections_for_pattern:
                # Find which profile this section belongs to using object identity
                for profile in profiles:
                    if any(section is s for s in profile.sections):
                        docs_with_this_section.add(profile.document_id)
                        break

            # Partition profiles based on section membership
            for profile in profiles:
                if profile.document_id in docs_with_this_section:
                    docs_with_section.append(profile)
                else:
                    docs_without_section.append(profile)
        else:
            # Fallback to original behavior when section_groups not provided (backward compatibility)
            for profile in profiles:
                has_section = any(
                    s.title and _normalize_condition_value(s.title) == _normalize_condition_value(section_name)
                    for s in profile.sections
                )
                if has_section:
                    docs_with_section.append(profile)
                else:
                    docs_without_section.append(profile)

        if not docs_with_section or not docs_without_section:
            continue

        condition = find_section_condition(
            docs_with_section, docs_without_section, section_name, variable_values
        )
        if not condition:
            continue

        conditional_rules[section_name] = {
            "condition": {
                "field": condition["field"],
                "operator": condition["operator"],
                "value": condition["value"],
            },
            "evidence": {
                "docs_with_section": [d.document_id for d in docs_with_section],
                "docs_without_section": [d.document_id for d in docs_without_section],
                "observed_field": condition["field"],
                "observed_value": condition["value"],
                "with_frequency": condition["with_frequency"],
                "without_frequency": condition["without_frequency"],
            },
            "confidence": float(condition["confidence"]),
            "status": "inferred",
        }

    return conditional_rules


def find_section_condition(
    docs_with_section: list[DocumentProfile],
    docs_without_section: list[DocumentProfile],
    section_name: str,
    variable_values: dict[str, dict] | None = None,
) -> dict | None:
    """Try to find a strong, evidence-backed condition that predicts section presence.

    When variable_values is provided, first attempts to find variable-based conditions.
    Falls back to vocabulary-based inference if no strong variable condition found.

    Returns a dict with field/operator/value and confidence when a deterministic
    pattern is observed; otherwise returns None.
    """
    if not docs_with_section or not docs_without_section:
        return None

    # PHASE 1: Try variable-based condition first (if variables available)
    if variable_values:
        variable_condition = _find_best_variable_condition(
            docs_with_section, docs_without_section, variable_values
        )
        if variable_condition:
            var_name, operator, value = variable_condition

            # Calculate confidence from variable presence
            docs_with_ids = {p.document_id for p in docs_with_section}
            docs_without_ids = {p.document_id for p in docs_without_section}

            with_count = sum(
                1 for doc_id in docs_with_ids
                if doc_id in variable_values and
                var_name in variable_values[doc_id] and
                value in (variable_values[doc_id][var_name] if isinstance(variable_values[doc_id][var_name], list) else [variable_values[doc_id][var_name]])
            )
            without_count = sum(
                1 for doc_id in docs_without_ids
                if doc_id in variable_values and
                var_name in variable_values[doc_id] and
                value in (variable_values[doc_id][var_name] if isinstance(variable_values[doc_id][var_name], list) else [variable_values[doc_id][var_name]])
            )

            with_ratio = with_count / len(docs_with_section) if docs_with_section else 0.0
            without_ratio = without_count / len(docs_without_section) if docs_without_section else 0.0

            confidence = min(0.95, max(0.6, with_ratio * 0.9 + (1.0 - without_ratio) * 0.1))

            return {
                "field": var_name,
                "operator": operator,
                "value": value,
                "with_frequency": round(with_ratio, 3),
                "without_frequency": round(without_ratio, 3),
                "confidence": confidence,
                "linked_variable": var_name,
                "source": "variable_analysis",
            }

    # PHASE 2: Fall back to vocabulary-based inference
    section_tokens = _section_tokens(section_name)
    candidate_scores: list[tuple[float, str, int, int, float, float, str]] = []
    seen_terms: set[str] = set()

    for profile in docs_with_section + docs_without_section:
        for term in profile.content.vocabulary:
            normalized = _normalize_condition_value(term)
            if not normalized:
                continue
            if normalized in section_tokens and _is_generic_condition_token(normalized):
                continue
            if normalized in seen_terms:
                continue
            seen_terms.add(normalized)

            with_count = sum(
                1 for p in docs_with_section if normalized in p.content.vocabulary
            )
            without_count = sum(
                1 for p in docs_without_section if normalized in p.content.vocabulary
            )
            with_total = len(docs_with_section)
            without_total = len(docs_without_section)

            with_ratio = with_count / with_total if with_total else 0.0
            without_ratio = without_count / without_total if without_total else 0.0

            # Require repeated evidence: strong presence in docs with the section,
            # and weak presence in docs without it.
            if with_count < max(1, with_total // 2):
                continue
            if with_ratio < 0.6 or without_ratio > 0.35:
                continue

            # Score combines predictive strength and support.
            score = (
                0.55 * (with_ratio - without_ratio)
                + 0.25 * with_ratio
                + 0.20 * (1.0 - without_ratio)
            )
            if score < 0.35:
                continue

            operator = "contains" if " " in normalized else "equals"
            candidate_scores.append(
                (score, normalized, with_count, without_count, with_ratio, without_ratio, operator)
            )

    if not candidate_scores:
        return None

    # Deterministic tie-break: highest score, then higher support, then lexical order
    candidate_scores.sort(
        key=lambda item: (
            item[0],  # score
            item[2],  # with_count
            -item[3],  # -without_count
            item[1],  # lexical
        ),
        reverse=True,
    )
    score, value, with_count, without_count, with_ratio, without_ratio, operator = candidate_scores[0]

    confidence = min(0.99, max(0.5, round(score, 3)))

    return {
        "field": "variable_observation",
        "operator": operator,
        "value": value,
        "with_frequency": round(with_ratio, 3),
        "without_frequency": round(without_ratio, 3),
        "confidence": confidence,
        "linked_variable": None,
        "source": "vocabulary_analysis",
    }
