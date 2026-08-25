"""Scoring and reporting for template-inference evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .metrics import (
    canonical_condition,
    conditional_rule_score,
    normalize_name,
    section_f1_score,
    section_order_score,
    variable_score,
)


@dataclass
class EvaluationMetric:
    """A single metric result with supporting detail."""

    name: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    """Overall evaluation report for a single inference run."""

    family_id: str
    overall_score: float
    metrics: dict[str, EvaluationMetric] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "overall_score": self.overall_score,
            "metrics": {name: {"score": metric.score, "details": metric.details} for name, metric in self.metrics.items()},
        }


class TemplateEvaluator:
    """Generic evaluator for inference outputs against ground-truth fixtures."""

    def __init__(self, *, family_weight: float = 0.15, clustering_weight: float = 0.15, section_weight: float = 0.20, ordering_weight: float = 0.20, variable_weight: float = 0.15, conditional_section_weight: float = 0.10, conditional_rule_weight: float = 0.05):
        weights = [
            family_weight,
            clustering_weight,
            section_weight,
            ordering_weight,
            variable_weight,
            conditional_section_weight,
            conditional_rule_weight,
        ]
        total = sum(weights)
        if abs(total) < 1e-12:
            raise ValueError("Overall scoring weights cannot all be zero.")
        scale = 1.0 / total
        self.weights = {
            "family_detection": family_weight * scale,
            "clustering_accuracy": clustering_weight * scale,
            "section_detection": section_weight * scale,
            "section_ordering": ordering_weight * scale,
            "variable_detection": variable_weight * scale,
            "conditional_section_detection": conditional_section_weight * scale,
            "conditional_rule_inference": conditional_rule_weight * scale,
        }

    def evaluate(self, inference_result: Any, ground_truth: dict[str, Any], *, predicted_family_id: str | None = None, predicted_cluster_map: dict[str, str] | None = None) -> EvaluationReport:
        """Compute a full evaluation report for one predicted inference result."""
        family_name = str(ground_truth.get("document_family") or "unknown_family")
        family_id = predicted_family_id or self._extract_predicted_family_id(inference_result)

        family_score = self._family_score(family_name, family_id)
        clustering_score = self._clustering_score(ground_truth, inference_result, predicted_cluster_map)
        section_score = self._section_score(ground_truth, inference_result)
        order_score = self._ordering_score(ground_truth, inference_result)
        variable_score_value = self._variable_score(ground_truth, inference_result)
        conditional_section_score = self._conditional_section_score(ground_truth, inference_result)
        conditional_rule_score_value = self._conditional_rule_score(ground_truth, inference_result)

        overall_score = (
            self.weights["family_detection"] * family_score
            + self.weights["clustering_accuracy"] * clustering_score
            + self.weights["section_detection"] * section_score
            + self.weights["section_ordering"] * order_score
            + self.weights["variable_detection"] * variable_score_value
            + self.weights["conditional_section_detection"] * conditional_section_score
            + self.weights["conditional_rule_inference"] * conditional_rule_score_value
        )

        metrics = {
            "family_detection": EvaluationMetric("family_detection", family_score, {"expected_family": family_name, "predicted_family": family_id}),
            "clustering_accuracy": EvaluationMetric("clustering_accuracy", clustering_score, {"expected_documents": len(self._expected_document_ids(ground_truth)), "predicted_documents": len(self._predicted_document_ids(inference_result))}),
            "section_detection": EvaluationMetric("section_detection", section_score, {"expected_sections": len(self._extract_ground_truth_sections(ground_truth)), "predicted_sections": len(self._extract_predicted_sections(inference_result))}),
            "section_ordering": EvaluationMetric("section_ordering", order_score, {"expected_order_length": len(self._extract_ground_truth_order(ground_truth)), "predicted_order_length": len(self._extract_predicted_order(inference_result))}),
            "variable_detection": EvaluationMetric("variable_detection", variable_score_value, {"expected_variables": len(self._extract_ground_truth_variables(ground_truth)), "predicted_variables": len(self._extract_predicted_variables(inference_result))}),
            "conditional_section_detection": EvaluationMetric("conditional_section_detection", conditional_section_score, {"expected_conditional_sections": len(self._extract_ground_truth_conditional_sections(ground_truth)), "predicted_conditional_sections": len(self._extract_predicted_conditional_sections(inference_result))}),
            "conditional_rule_inference": EvaluationMetric("conditional_rule_inference", conditional_rule_score_value, {"expected_rules": len(self._extract_ground_truth_conditional_rules(ground_truth)), "predicted_rules": len(self._extract_predicted_conditional_rules(inference_result))}),
        }

        return EvaluationReport(family_id=family_name, overall_score=overall_score, metrics=metrics)

    def _family_score(self, expected_family: str, predicted_family: str | None) -> float:
        if predicted_family is None:
            return 0.0
        return 1.0 if normalize_name(expected_family) == normalize_name(predicted_family) else 0.0

    def _clustering_score(self, ground_truth: dict[str, Any], inference_result: Any, predicted_cluster_map: dict[str, str] | None) -> float:
        expected_mapping = self._expected_document_mapping(ground_truth)
        if not expected_mapping:
            return 1.0
        predicted_mapping = predicted_cluster_map or self._predicted_document_mapping(inference_result)
        if not predicted_mapping:
            return 0.0
        total_docs = len(expected_mapping)
        correct = sum(1 for document_id, expected_family in expected_mapping.items() if predicted_mapping.get(document_id) == expected_family)
        return correct / total_docs if total_docs else 0.0

    def _section_score(self, ground_truth: dict[str, Any], inference_result: Any) -> float:
        expected_sections = self._extract_ground_truth_sections(ground_truth)
        predicted_sections = self._extract_predicted_sections(inference_result)
        return section_f1_score(expected_sections, predicted_sections)

    def _ordering_score(self, ground_truth: dict[str, Any], inference_result: Any) -> float:
        expected_order = self._extract_ground_truth_order(ground_truth)
        predicted_order = self._extract_predicted_order(inference_result)
        return section_order_score(expected_order, predicted_order)

    def _variable_score(self, ground_truth: dict[str, Any], inference_result: Any) -> float:
        expected_variables = self._extract_ground_truth_variables(ground_truth)
        predicted_variables = self._extract_predicted_variables(inference_result)
        return variable_score(expected_variables, predicted_variables)

    def _conditional_section_score(self, ground_truth: dict[str, Any], inference_result: Any) -> float:
        expected_sections = self._extract_ground_truth_conditional_sections(ground_truth)
        predicted_sections = self._extract_predicted_conditional_sections(inference_result)
        return section_f1_score(expected_sections, predicted_sections)

    def _conditional_rule_score(self, ground_truth: dict[str, Any], inference_result: Any) -> float:
        expected_rules = self._extract_ground_truth_conditional_rules(ground_truth)
        predicted_rules = self._extract_predicted_conditional_rules(inference_result)
        return conditional_rule_score(expected_rules, predicted_rules)

    def _extract_predicted_family_id(self, inference_result: Any) -> str | None:
        if inference_result is None:
            return None
        for attribute in ("family_id", "document_family", "family_name"):
            value = getattr(inference_result, attribute, None)
            if value is None and isinstance(inference_result, dict):
                value = inference_result.get(attribute)
            if value is not None:
                return str(value)
        return None

    def _expected_document_mapping(self, ground_truth: dict[str, Any]) -> dict[str, str]:
        if not ground_truth:
            return {}
        document_summary = ground_truth.get("per_document_summary") or ground_truth.get("documents") or []
        family_name = str(ground_truth.get("document_family") or "unknown_family")
        mapping: dict[str, str] = {}
        for item in document_summary:
            if isinstance(item, dict):
                document_id = item.get("id") or item.get("file")
                if document_id is not None:
                    mapping[str(document_id)] = family_name
        return mapping

    def _predicted_document_mapping(self, inference_result: Any) -> dict[str, str]:
        if inference_result is None:
            return {}
        if hasattr(inference_result, "get_document_to_cluster_mapping"):
            result = inference_result.get_document_to_cluster_mapping()
            if isinstance(result, dict):
                return {str(key): str(value) for key, value in result.items()}
        document_ids = getattr(inference_result, "document_ids", None)
        family_id = self._extract_predicted_family_id(inference_result)
        if isinstance(document_ids, list) and family_id is not None:
            return {str(doc_id): family_id for doc_id in document_ids}
        if isinstance(inference_result, dict):
            document_ids = inference_result.get("document_ids") or []
            family_id = inference_result.get("family_id") or inference_result.get("document_family")
            if isinstance(document_ids, list) and family_id is not None:
                return {str(doc_id): str(family_id) for doc_id in document_ids}
        return {}

    def _predicted_document_ids(self, inference_result: Any) -> list[str]:
        if inference_result is None:
            return []
        document_ids = getattr(inference_result, "document_ids", None)
        if document_ids is None and isinstance(inference_result, dict):
            document_ids = inference_result.get("document_ids")
        if isinstance(document_ids, list):
            return [str(doc_id) for doc_id in document_ids]
        mapping = self._predicted_document_mapping(inference_result)
        return list(mapping)

    def _expected_document_ids(self, ground_truth: dict[str, Any]) -> list[str]:
        return list(self._expected_document_mapping(ground_truth))

    def _extract_ground_truth_sections(self, ground_truth: dict[str, Any]) -> list[str]:
        expected = []
        for key in ("fixed_sections", "expected_section_order"):
            expected.extend(ground_truth.get(key) or [])
        return [normalize_name(item) for item in expected if item is not None]

    def _extract_predicted_sections(self, inference_result: Any) -> list[str]:
        if inference_result is None:
            return []
        sections = getattr(inference_result, "sections", None)
        if sections is None and isinstance(inference_result, dict):
            sections = inference_result.get("sections")
        result: list[str] = []
        if sections is None:
            return result
        for section in sections:
            if isinstance(section, dict):
                candidate = (
                    section.get("title_or_pattern")
                    or section.get("section_name")
                    or section.get("name")
                    or section.get("title")
                )
            else:
                candidate = (
                    getattr(section, "title_or_pattern", None)
                    or getattr(section, "section_name", None)
                    or getattr(section, "name", None)
                    or getattr(section, "title", None)
                    or section
                )
            normalized = normalize_name(candidate)
            if normalized:
                result.append(normalized)
        return result

    def _extract_ground_truth_order(self, ground_truth: dict[str, Any]) -> list[str]:
        order = ground_truth.get("expected_section_order") or []
        return [normalize_name(item) for item in order if item is not None]

    def _extract_predicted_order(self, inference_result: Any) -> list[str]:
        if inference_result is None:
            return []
        sections = getattr(inference_result, "sections", None)
        if sections is None and isinstance(inference_result, dict):
            sections = inference_result.get("sections")
        if sections is None:
            return []
        ordered: list[str] = []
        for section in sections:
            if isinstance(section, dict):
                candidate = (
                    section.get("title_or_pattern")
                    or section.get("section_name")
                    or section.get("name")
                    or section.get("title")
                )
            else:
                candidate = (
                    getattr(section, "title_or_pattern", None)
                    or getattr(section, "section_name", None)
                    or getattr(section, "name", None)
                    or getattr(section, "title", None)
                    or section
                )
            normalized = normalize_name(candidate)
            if normalized:
                ordered.append(normalized)
        return ordered

    def _extract_ground_truth_variables(self, ground_truth: dict[str, Any]) -> list[dict[str, Any]]:
        variables = ground_truth.get("variable_fields") or []
        normalized: list[dict[str, Any]] = []
        for variable in variables:
            if not isinstance(variable, dict):
                continue
            item = dict(variable)
            item["variable_name"] = item.get("name")
            item["inferred_type"] = item.get("type")
            normalized.append(item)
        return normalized

    def _extract_predicted_variables(self, inference_result: Any) -> list[dict[str, Any]]:
        if inference_result is None:
            return []
        variables = getattr(inference_result, "variables", None)
        if variables is None and isinstance(inference_result, dict):
            variables = inference_result.get("variables")
        if variables is None:
            return []
        normalized: list[dict[str, Any]] = []
        for variable in variables:
            if isinstance(variable, dict):
                item = dict(variable)
                variable_name = item.get("variable_name") or item.get("name")
                inferred_type = item.get("inferred_type") or item.get("type")
                normalized.append({
                    "variable_name": variable_name,
                    "inferred_type": inferred_type or ""
                })
            else:
                # Handle VariableField or dataclass-style objects
                variable_name = getattr(variable, "variable_name", None) or getattr(variable, "name", None)
                inferred_type = getattr(variable, "inferred_type", None) or getattr(variable, "type", None)
                normalized.append({
                    "variable_name": variable_name,
                    "inferred_type": inferred_type or ""
                })
        return normalized

    def _extract_ground_truth_conditional_sections(self, ground_truth: dict[str, Any]) -> list[str]:
        conditional = ground_truth.get("conditional_sections") or []
        names: list[str] = []
        for item in conditional:
            if isinstance(item, dict):
                candidate = item.get("name") or item.get("section_name")
            else:
                candidate = item
            normalized = normalize_name(candidate)
            if normalized:
                names.append(normalized)
        return names

    def _extract_predicted_conditional_sections(self, inference_result: Any) -> list[str]:
        if inference_result is None:
            return []
        rules = getattr(inference_result, "conditional_rules", None)
        if rules is None and isinstance(inference_result, dict):
            rules = inference_result.get("conditional_rules")
        result: list[str] = []
        if rules is None:
            sections = getattr(inference_result, "sections", None)
            if sections is None and isinstance(inference_result, dict):
                sections = inference_result.get("sections")
            for section in sections or []:
                if isinstance(section, dict):
                    conditional_info = section.get("conditional_info")
                    if conditional_info:
                        candidate = section.get("title_or_pattern") or section.get("section_name") or section.get("name")
                        normalized = normalize_name(candidate)
                        if normalized:
                            result.append(normalized)
            return result
        for rule in rules:
            if isinstance(rule, dict):
                candidate = rule.get("target_section") or rule.get("section_name") or rule.get("name")
            else:
                candidate = getattr(rule, "target_section", None)
            normalized = normalize_name(candidate)
            if normalized:
                result.append(normalized)
        return result

    def _extract_ground_truth_conditional_rules(self, ground_truth: dict[str, Any]) -> list[dict[str, Any]]:
        conditional = ground_truth.get("conditional_sections") or []
        rules: list[dict[str, Any]] = []
        for item in conditional:
            if not isinstance(item, dict):
                continue
            section_name = item.get("name") or item.get("section_name") or ""
            condition = item.get("condition")
            if section_name:
                rules.append({"target_section": section_name, "condition": condition})
        return rules

    def _extract_predicted_conditional_rules(self, inference_result: Any) -> list[dict[str, Any]]:
        if inference_result is None:
            return []
        rules = getattr(inference_result, "conditional_rules", None)
        if rules is None and isinstance(inference_result, dict):
            rules = inference_result.get("conditional_rules")
        if rules is None:
            return []
        normalized: list[dict[str, Any]] = []
        for rule in rules:
            if isinstance(rule, dict):
                normalized.append({
                    "target_section": rule.get("target_section") or rule.get("section_name") or rule.get("name"),
                    "condition": rule.get("condition") or rule.get("rule") or rule.get("expression"),
                })
            else:
                target_section = getattr(rule, "target_section", None)
                condition = getattr(rule, "condition", None)
                normalized.append({"target_section": target_section, "condition": condition})
        return normalized

    def evaluate_family(self, predicted_family_id: str | None, expected_family_id: str) -> EvaluationMetric:
        """Evaluate family detection in isolation."""
        score = self._family_score(expected_family_id, predicted_family_id)
        return EvaluationMetric("family_detection", score, {"expected_family": expected_family_id, "predicted_family": predicted_family_id})

    def evaluate_sections(self, expected_sections: Any, predicted_sections: Any) -> EvaluationMetric:
        """Evaluate section detection in isolation."""
        score = section_f1_score(expected_sections, predicted_sections)
        return EvaluationMetric("section_detection", score, {"expected_count": len(self._as_list(expected_sections)), "predicted_count": len(self._as_list(predicted_sections))})

    def evaluate_ordering(self, expected_order: Any, predicted_order: Any) -> EvaluationMetric:
        """Evaluate order accuracy in isolation."""
        score = section_order_score(expected_order, predicted_order)
        return EvaluationMetric("section_ordering", score, {"expected_order": self._as_list(expected_order), "predicted_order": self._as_list(predicted_order)})

    def evaluate_variables(self, expected_variables: Any, predicted_variables: Any) -> EvaluationMetric:
        """Evaluate variable detection in isolation."""
        score = variable_score(expected_variables, predicted_variables)
        return EvaluationMetric("variable_detection", score, {"expected_count": len(self._as_list(expected_variables)), "predicted_count": len(self._as_list(predicted_variables))})

    def evaluate_conditional_rules(self, expected_rules: Any, predicted_rules: Any) -> EvaluationMetric:
        """Evaluate conditional-rule inference in isolation."""
        score = conditional_rule_score(expected_rules, predicted_rules)
        return EvaluationMetric("conditional_rule_inference", score, {"expected_rule_count": len(self._as_list(expected_rules)), "predicted_rule_count": len(self._as_list(predicted_rules))})

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return sorted(value)
        return [value]

    @staticmethod
    def _normalize_rule(rule: Any) -> str:
        return canonical_condition(rule)
