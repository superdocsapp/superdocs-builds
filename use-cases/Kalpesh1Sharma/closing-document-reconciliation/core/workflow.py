from __future__ import annotations

from core.models import (
    DocumentType,
    ExtractedMortgageDocument,
    FieldObservation,
    FileRule,
    ReconciliationReport,
)
from core.normalize import (
    addresses_match,
    addresses_match_exact,
    borrower_sets_match_exact,
    borrower_sets_match_under_middle_initial_rule,
)
from core.reconcile import (
    reconcile_numeric_field,
    reconcile_text_field,
)
from core.rule_config import (
    NUMERIC_RECONCILIATION_CONFIGS,
    TEXT_RECONCILIATION_CONFIGS,
)
from core.rules import (
    numeric_tolerance_from_rule,
    rule_supports_address_abbreviations,
    rule_supports_correction,
    rule_supports_middle_initial_omission,
)


def find_rule(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    rule_id: str,
) -> FileRule | None:
    for document in documents.values():
        for rule in document.rules:
            if rule.rule_id == rule_id:
                return rule

    return None


def _observation(
    document: ExtractedMortgageDocument,
    field,
) -> FieldObservation:
    return FieldObservation(
        document_type=document.document_type,
        filename=document.filename,
        value=field.value,
        raw_value=field.raw_value,
        supporting_quote=field.supporting_quote,
    )


def _field_observation(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    document_type: DocumentType,
    field_name: str,
) -> FieldObservation | None:
    document = documents.get(document_type)

    if document is None:
        return None

    field = getattr(
        document,
        field_name,
    )

    return _observation(
        document,
        field,
    )


def _fee_observation(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    document_type: DocumentType,
    fee_name: str,
) -> FieldObservation | None:
    document = documents.get(document_type)

    if document is None:
        return None

    field = document.fees.get(
        fee_name
    )

    if field is None:
        return None

    return _observation(
        document,
        field,
    )


def _without_none(
    items: list[
        FieldObservation | None
    ],
) -> list[FieldObservation]:
    return [
        item
        for item in items
        if item is not None
    ]


def build_reconciliation_report(
    *,
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    scenario_id: str,
) -> ReconciliationReport:
    """
    Reconcile the file using extracted evidence and the file's own rules.

    Numeric field/reference mappings live in ``core.rule_config``. Numeric
    tolerances are parsed from the actual rule text at runtime; they are not
    hardcoded in this workflow. Text normalizations are enabled only when the
    corresponding rule text explicitly supports that normalization.
    """

    required_types = {
        DocumentType.LOAN_ESTIMATE,
        DocumentType.CLOSING_DISCLOSURE,
        DocumentType.PROMISSORY_NOTE,
        DocumentType.SETTLEMENT_STATEMENT,
        DocumentType.UNDERWRITING_APPROVAL,
    }

    missing_types = (
        required_types
        - set(documents.keys())
    )

    warnings: list[str] = []

    if missing_types:
        warnings.append(
            "Missing expected document type(s): "
            + ", ".join(
                sorted(
                    item.value
                    for item in missing_types
                )
            )
        )

    configured_rule_ids = {
        config.rule_id
        for config in NUMERIC_RECONCILIATION_CONFIGS
        if config.rule_id is not None
    } | {
        config.rule_id
        for config in TEXT_RECONCILIATION_CONFIGS
    }

    rules = {
        rule_id: find_rule(
            documents,
            rule_id,
        )
        for rule_id in configured_rule_ids
    }

    for rule_id in sorted(configured_rule_ids):
        if rules[rule_id] is None:
            warnings.append(
                f"{rule_id} was not found in the file."
            )

    findings = []

    # ---------------------------------------------------------
    # Numeric / boolean fields, including each fee category.
    # ---------------------------------------------------------
    for config in NUMERIC_RECONCILIATION_CONFIGS:
        observations = []

        for document_type in config.observation_documents:
            if config.source_kind == "fee":
                observation = _fee_observation(
                    documents,
                    document_type,
                    config.source_key,
                )
            else:
                observation = _field_observation(
                    documents,
                    document_type,
                    config.source_key,
                )

            observations.append(observation)

        applicable_rule = (
            rules.get(config.rule_id)
            if config.rule_id is not None
            else None
        )

        tolerance = numeric_tolerance_from_rule(
            applicable_rule
        )

        curable_action = None

        if (
            config.curable_action is not None
            and rule_supports_correction(
                applicable_rule
            )
        ):
            curable_action = config.curable_action

        findings.append(
            reconcile_numeric_field(
                field_name=config.field_name,
                observations=_without_none(
                    observations
                ),
                reference_document=(
                    config.reference_document
                ),
                tolerance=tolerance,
                applicable_rule=applicable_rule,
                curable_action=curable_action,
            )
        )

    # ---------------------------------------------------------
    # Text fields. Rule text decides whether permissive
    # normalization is allowed; otherwise comparison is strict.
    # ---------------------------------------------------------
    for config in TEXT_RECONCILIATION_CONFIGS:
        rule = rules.get(
            config.rule_id
        )

        if (
            config.semantics
            == "middle_initial_omission"
        ):
            supported_rule = (
                rule
                if rule_supports_middle_initial_omission(
                    rule
                )
                else None
            )

            comparator = (
                borrower_sets_match_under_middle_initial_rule
                if supported_rule is not None
                else borrower_sets_match_exact
            )

        elif (
            config.semantics
            == "address_abbreviations"
        ):
            supported_rule = (
                rule
                if rule_supports_address_abbreviations(
                    rule
                )
                else None
            )

            comparator = (
                addresses_match
                if supported_rule is not None
                else addresses_match_exact
            )

        else:  # pragma: no cover - config is type constrained.
            supported_rule = None
            raise ValueError(
                f"Unsupported text semantics: {config.semantics}"
            )

        observations = _without_none([
            _field_observation(
                documents,
                document_type,
                config.source_key,
            )
            for document_type in config.observation_documents
        ])

        findings.append(
            reconcile_text_field(
                field_name=config.field_name,
                observations=observations,
                reference_document=(
                    config.reference_document
                ),
                comparator=comparator,
                applicable_rule=supported_rule,
            )
        )

    return ReconciliationReport(
        scenario_id=scenario_id,
        findings=findings,
        warnings=warnings,
    )
