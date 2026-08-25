"""Template inference engine."""

from superdocs_template_inference.clustering.result import FamilyCluster
from superdocs_template_inference.models import Document, DocumentProfile
from superdocs_template_inference.template_inference.conditionals import (
    infer_conditional_rules,
    _find_best_variable_condition,
)
from superdocs_template_inference.template_inference.result import (
    ConditionalRule,
    InferenceEvidence,
    TemplateInferenceResult,
    TemplateSection,
    VariableField,
)
from superdocs_template_inference.template_inference.sections import (
    align_sections,
    calculate_section_presence_frequency,
    classify_section_presence,
    get_section_content_representation,
    infer_section_ordering,
    normalize_section_title,
    detect_semantic_sections,
    augment_sections_with_semantic_names,
    _get_canonical_section_title_internal,
)
from superdocs_template_inference.template_inference.sections_document_aware import (
    detect_semantic_sections_from_document,
    merge_sections_preserving_headings,
    deduplicate_semantic_sections,
)
from superdocs_template_inference.template_inference.variables import (
    calculate_variable_frequency,
    detect_variables,
    infer_semantic_role,
    extract_variable_values,
    infer_variable_type,
    infer_variable_metadata,
    link_variable_to_sections,
)


class TemplateInferer:
    """Infer templates for document families."""

    def __init__(self):
        """Initialize template inferer."""
        pass

    def infer(
        self,
        family_cluster: FamilyCluster,
        profiles_by_id: dict[str, DocumentProfile],
        documents_by_id: dict[str, Document] | None = None,
    ) -> TemplateInferenceResult:
        """Infer template for a family cluster.

        Args:
            family_cluster: FamilyCluster containing family membership.
            profiles_by_id: Mapping of document_id to DocumentProfile.
            documents_by_id: Optional mapping of document_id to Document (normalized blocks).
                            When provided, enables document-aware M7 semantic detection.

        Returns:
            TemplateInferenceResult with inferred template data.
        """
        # Extract profiles for this family
        family_profiles = [
            profiles_by_id[doc_id] for doc_id in family_cluster.document_ids
        ]

        # Handle edge cases
        if not family_profiles:
            return TemplateInferenceResult(
                family_id=family_cluster.family_id,
                document_ids=family_cluster.document_ids,
                confidence=0.0,
            )

        # Initialize result
        result = TemplateInferenceResult(
            family_id=family_cluster.family_id,
            document_ids=family_cluster.document_ids,
            confidence=family_cluster.confidence,
        )

        # M7: Detect semantic sections using document-aware or profile-based detection
        family_documents = None
        if documents_by_id:
            family_documents = {
                doc_id: documents_by_id[doc_id]
                for doc_id in family_cluster.document_ids
                if doc_id in documents_by_id
            }

        for profile in family_profiles:
            # Only process if profile hasn't been augmented yet (check for semantic_pattern markers)
            has_semantic_sections = any(
                s.boundary_marker == "semantic_pattern" for s in profile.sections
            )

            if not has_semantic_sections:
                # Try document-aware detection first if documents available
                if family_documents and profile.document_id in family_documents:
                    document = family_documents[profile.document_id]
                    document_semantic_zones = detect_semantic_sections_from_document(document)

                    # Merge document-detected sections with profile sections,
                    # preserving heading-based structure
                    profile.sections = merge_sections_preserving_headings(
                        profile.sections, document_semantic_zones
                    )
                else:
                    # Fall back to profile-based detection when documents not available
                    semantic_zones = detect_semantic_sections(profile)

                    # Add semantic sections to profile sections if they provide new zones
                    if semantic_zones:
                        profile.sections.extend(semantic_zones)

                # Augment existing sections with semantic names when appropriate
                profile.sections = augment_sections_with_semantic_names(profile.sections, profile)

        # M7: Deduplicate semantic sections within each profile before cross-family alignment
        # This prevents multiple M7 detections of the same logical zone from inflating frequencies
        for profile in family_profiles:
            profile.sections = deduplicate_semantic_sections(profile.sections)

        # 1. Align sections across family
        section_groups = align_sections(family_profiles)

        # 1b. Detect section variants (conditional alternatives at same position)
        from superdocs_template_inference.template_inference.sections import detect_section_variants
        section_variants = detect_section_variants(section_groups, family_profiles)

        # 2. Infer section ordering
        section_order = infer_section_ordering(family_profiles)

        # 3. Build template sections
        inferred_sections = []
        optional_section_names = []
        variant_groups_to_infer = {}  # Maps variant_group_id to list of section titles for conditional inference

        # Track which section titles belong to variant groups
        sections_in_variants = set()
        for variant_group_id, variant_titles in section_variants.items():
            sections_in_variants.update(variant_titles)
            variant_groups_to_infer[variant_group_id] = variant_titles

        for idx, normalized_title in enumerate(section_order):
            if normalized_title not in section_groups:
                continue

            # Skip variant members for now; they'll be handled as a group below
            if normalized_title in sections_in_variants:
                continue

            sections = section_groups[normalized_title]
            frequency = calculate_section_presence_frequency(
                normalized_title, family_profiles, section_groups
            )
            presence_type = classify_section_presence(frequency)

            # Convert internal form (underscores) to output form (spaces)
            title_for_output = normalized_title.replace("_", " ")

            if presence_type != "always":
                optional_section_names.append(title_for_output)

            # Determine presence classification
            if frequency >= 0.95:
                inferred_type = "REQUIRED"
            else:
                inferred_type = "OPTIONAL"

            section = TemplateSection(
                section_id=f"section_{idx}",
                title_or_pattern=title_for_output,
                inferred_type=inferred_type,
                order=idx,
                presence_frequency=frequency,
                presence_type=presence_type,
                content_representation=get_section_content_representation(sections),
                confidence=frequency,
                evidence=[
                    InferenceEvidence(
                        evidence_type="section_alignment",
                        source_document_ids=[
                            family_profiles[i].document_id
                            for i in range(len(family_profiles))
                            if any(
                                _get_canonical_section_title_internal(s.title or "")
                                == normalized_title
                                for s in family_profiles[i].sections
                            )
                        ],
                        related_section=title_for_output,
                        observation=f"Section appears in {len(sections)}/{len(family_profiles)} documents",
                        confidence_contribution=frequency,
                    )
                ],
            )

            inferred_sections.append(section)

        # 3b. Add variant group sections as CONDITIONAL
        variant_section_mapping = {}  # Maps variant_group_name to list of section_titles for rule inference
        for variant_group_id, variant_titles in variant_groups_to_infer.items():
            # Get the first section's position for ordering
            first_section_idx = min(s.start_block_idx for title in variant_titles for s in section_groups[title])

            # Use the first variant title alphabetically as the representative name
            representative_title = sorted(variant_titles)[0]
            title_for_output = representative_title.replace("_", " ")

            variant_section = TemplateSection(
                section_id=f"section_{len(inferred_sections)}_variant_{variant_group_id}",
                title_or_pattern=title_for_output,
                inferred_type="CONDITIONAL",
                order=len(inferred_sections),
                presence_frequency=0.5,  # Variant groups span multiple docs but differently
                presence_type="conditional",
                content_representation=title_for_output,
                confidence=0.5,
                evidence=[
                    InferenceEvidence(
                        evidence_type="section_variant_group",
                        source_document_ids=[p.document_id for p in family_profiles],
                        related_section=title_for_output,
                        observation=f"Variant group with {len(variant_titles)} alternatives: {', '.join(sorted(variant_titles))}"[:200],
                        confidence_contribution=0.5,
                    )
                ],
            )

            inferred_sections.append(variant_section)
            # Store for conditional inference - add ALL variants to optional_section_names
            # so they get processed for rule inference
            variant_section_mapping[title_for_output] = variant_titles
            for title in variant_titles:
                optional_section_names.append(title.replace("_", " "))

        result.sections = inferred_sections

        # 4. Detect variables (with document-aware extraction when available)
        candidate_variables = detect_variables(family_profiles, family_documents)

        # M6: Extract actual values for each variable candidate
        variable_values = extract_variable_values(candidate_variables, family_profiles, family_documents)

        inferred_variables = []

        for var_name, var_info in candidate_variables.items():
            # Calculate frequency
            frequency = calculate_variable_frequency(var_name, family_profiles, family_documents)

            # Variables from field extraction (not vocabulary-based) should be kept broadly
            # Only vocabulary-based candidates need strict frequency filtering
            is_field_extracted = var_info.get("section") == "field_detection"

            if is_field_extracted:
                # Field-extracted variables: keep if present in multiple documents (>= 2 docs)
                # This allows legitimate variables that appear in all family documents
                min_docs_for_field = max(2, len(family_profiles) // 2)  # At least 2 docs or 50%
                if frequency < (min_docs_for_field / len(family_profiles)):
                    continue
            else:
                # Vocabulary-based candidates: original strict filtering
                # Skip if not varied or present in almost all documents (likely boilerplate)
                if frequency < 0.2 or frequency > 0.95:
                    continue

            # Infer semantic role
            semantic_role = infer_semantic_role(var_name, [])

            # M6: Extract observed values
            observed_values = variable_values.get(var_name, [])

            # M6: Infer variable type
            inferred_type, type_metadata = infer_variable_type(observed_values)

            # M6: Infer variable metadata
            var_metadata = infer_variable_metadata(var_name, observed_values, family_profiles, family_documents)

            # M6: Link variable to sections
            section_links = link_variable_to_sections(var_name, family_profiles, section_groups, family_documents)
            section_context = section_links[0] if section_links else "unknown"

            # Build evidence list
            evidence_list = [
                InferenceEvidence(
                    evidence_type="value_variance",
                    source_document_ids=family_cluster.document_ids,
                    related_variable=var_name,
                    observation=f"Variable appears in {frequency:.1%} of documents",
                    confidence_contribution=frequency,
                )
            ]

            # Add type inference evidence
            if inferred_type != "string":
                evidence_list.append(
                    InferenceEvidence(
                        evidence_type="semantic_pattern_match",
                        source_document_ids=[
                            family_profiles[i].document_id
                            for i in range(len(family_profiles))
                            if var_name.lower() in family_profiles[i].content.vocabulary
                        ],
                        related_variable=var_name,
                        observation=f"Variable values match {inferred_type} pattern",
                        confidence_contribution=0.3,
                    )
                )

            # Confidence calculation
            base_confidence = 0.6 if semantic_role != "unknown" else 0.4
            type_boost = 0.2 if inferred_type != "string" else 0.0
            confidence = min(1.0, base_confidence + type_boost)

            variable = VariableField(
                variable_name=var_name,
                semantic_role=semantic_role,
                section_context=section_context,
                observed_values=observed_values,
                frequency=frequency,
                confidence=confidence,
                evidence=evidence_list,
                # M6 fields
                inferred_type=inferred_type,
                is_enum=type_metadata.get("is_enum", False),
                enum_values=type_metadata.get("enum_values", []),
                unique_per_document=var_metadata.get("unique_per_document", False),
            )

            inferred_variables.append(variable)

        result.variables = inferred_variables

        # Populate per-section variable membership from actual section-context associations.
        section_lookup = {
            " ".join(str(section.title_or_pattern).strip().lower().replace("_", " ").split()): section
            for section in result.sections
        }
        for variable in inferred_variables:
            if not variable.section_context or variable.section_context == "unknown":
                continue
            normalized_context = " ".join(
                str(variable.section_context).strip().lower().replace("_", " ").split()
            )
            section = section_lookup.get(normalized_context)
            if section is None:
                continue
            section.variables = sorted(set(section.variables + [variable.variable_name]))

        # 5. Build per-document variable values for conditional inference
        per_doc_variable_values = {}  # {doc_id: {var_name: [values]}}
        if family_documents:
            from superdocs_template_inference.template_inference.variables import _extract_all_field_values
            for doc_id, document in family_documents.items():
                doc_vars = _extract_all_field_values(document)
                if doc_vars:
                    per_doc_variable_values[doc_id] = doc_vars

        # 5. Infer conditional rules
        # For variant groups, try to find what variable value predicts each variant
        conditional_rules_dict = infer_conditional_rules(
            family_profiles, optional_section_names, section_groups, per_doc_variable_values
        )

        # 5b. For variant groups, try to infer which variant corresponds to which variable value
        if variant_section_mapping and per_doc_variable_values:
            for group_display_name, variant_titles in variant_section_mapping.items():
                # For each variant, try to find which documents have it and what variables they share
                for variant_title in variant_titles:
                    # Find which profiles have this variant section
                    docs_with_variant = set()
                    for profile in family_profiles:
                        if any(_get_canonical_section_title_internal(s.title or "") == variant_title
                               for s in profile.sections):
                            docs_with_variant.add(profile.document_id)

                    if docs_with_variant and len(docs_with_variant) < len(family_profiles):
                        # This variant is optional; try to find predictive variable
                        docs_without_variant = {p.document_id for p in family_profiles} - docs_with_variant
                        docs_with_profile = [p for p in family_profiles if p.document_id in docs_with_variant]
                        docs_without_profile = [p for p in family_profiles if p.document_id in docs_without_variant]

                        # Use existing variable-based condition inference
                        condition = _find_best_variable_condition(
                            docs_with_profile, docs_without_profile, per_doc_variable_values
                        )

                        if condition and variant_title not in conditional_rules_dict:
                            # Add conditional rule for this variant
                            conditional_rules_dict[variant_title.replace("_", " ")] = {
                                "condition": {
                                    "field": condition[0],
                                    "operator": condition[1],
                                    "value": condition[2],
                                },
                                "evidence": {
                                    "docs_with_section": sorted(list(docs_with_variant)),
                                    "docs_without_section": sorted(list(docs_without_variant)),
                                },
                            }

        inferred_conditionals = []

        for section_name, rule_data in conditional_rules_dict.items():
            condition = rule_data.get("condition", {})
            evidence_data = rule_data.get("evidence", {})

            supporting_evidence = [
                InferenceEvidence(
                    evidence_type="conditional_correlation",
                    source_document_ids=evidence_data.get("docs_with_section", []),
                    related_section=section_name,
                    related_variable=condition.get("value"),
                    observation=(
                        f"Observed {condition.get('field', 'variable_observation')}={condition.get('value')} "
                        f"in documents with section and not in documents without it"
                    ),
                    confidence_contribution=rule_data.get("confidence", 0.7),
                ),
                InferenceEvidence(
                    evidence_type="conditional_correlation",
                    source_document_ids=evidence_data.get("docs_without_section", []),
                    related_section=section_name,
                    related_variable=condition.get("value"),
                    observation=(
                        f"Observed absence of {condition.get('field', 'variable_observation')}={condition.get('value')} "
                        f"in documents without the section"
                    ),
                    confidence_contribution=max(0.0, 1.0 - rule_data.get("confidence", 0.7)),
                ),
            ]

            conditional = ConditionalRule(
                target_section=section_name,
                condition=condition,
                supporting_evidence=supporting_evidence,
                confidence=rule_data.get("confidence", 0.7),
                status=rule_data.get("status", "inferred"),
            )

            inferred_conditionals.append(conditional)

        result.conditional_rules = inferred_conditionals

        for section in result.sections:
            # Look up in conditional_rules_dict using the output form (with spaces)
            section_key_output = section.title_or_pattern.lower()
            if section_key_output in conditional_rules_dict:
                section.inferred_type = "CONDITIONAL"
                section.presence_type = "conditional"
                section.conditional_info = {
                    "section_name": section.title_or_pattern,
                    "condition": conditional_rules_dict[section_key_output]["condition"],
                    "confidence": conditional_rules_dict[section_key_output].get("confidence", 0.7),
                    "evidence": conditional_rules_dict[section_key_output].get("evidence", {}),
                }

        # 6. Calculate family-level confidence
        if result.sections:
            avg_section_confidence = sum(s.confidence for s in result.sections) / len(
                result.sections
            )
            result.confidence = (
                0.7 * family_cluster.confidence + 0.3 * avg_section_confidence
            )
        else:
            result.confidence = family_cluster.confidence

        return result
