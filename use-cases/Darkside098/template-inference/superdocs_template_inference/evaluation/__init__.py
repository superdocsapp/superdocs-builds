"""Evaluation layer for template inference results."""

from .loader import GroundTruthLoader, load_all_ground_truths, load_ground_truth
from .metrics import (
    canonical_condition,
    conditional_rule_score,
    normalize_name,
    section_f1_score,
    section_order_score,
    variable_score,
)
from .scorer import EvaluationMetric, EvaluationReport, TemplateEvaluator

__all__ = [
    "GroundTruthLoader",
    "load_ground_truth",
    "load_all_ground_truths",
    "normalize_name",
    "canonical_condition",
    "section_f1_score",
    "section_order_score",
    "variable_score",
    "conditional_rule_score",
    "EvaluationMetric",
    "EvaluationReport",
    "TemplateEvaluator",
]
