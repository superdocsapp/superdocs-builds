"""Finding and EvaluationResult data models for the rules checking stage.

These models represent the output of rule evaluation against source spans.
A Finding is produced only when a rule evaluation yields a verdict of "fail".
"""

from dataclasses import dataclass
from typing import Literal

# Type aliases for evaluation outcomes and methods
FindingVerdict = Literal["pass", "fail", "not_applicable", "insufficient_evidence"]
EvaluationMethod = Literal["llm", "structured"]


@dataclass
class CitedSpan:
    """Exact source location cited by a finding.

    Attributes:
        start_offset: 0-based inclusive start position in the source document.
        end_offset: 0-based exclusive end position in the source document.
        text: Exact text at [start_offset:end_offset].
    """

    start_offset: int
    end_offset: int
    text: str


@dataclass
class EvaluationResult:
    """Result from evaluating a single rule against a single span.

    Produced by both LLM and structured evaluators. The verdict determines
    whether a Finding is created (only on "fail").

    Attributes:
        rule_id: The unique identifier of the rule that was evaluated.
        verdict: The evaluation outcome.
        cited_span: The exact source span that triggered the evaluation.
        explanation: Reasoning for the verdict.
        evaluation_method: Whether the rule was evaluated by LLM or structured logic.
    """

    rule_id: str
    verdict: FindingVerdict
    cited_span: CitedSpan
    explanation: str
    evaluation_method: EvaluationMethod


@dataclass
class Finding:
    """A confirmed rule violation with full provenance.

    Only produced when verdict == "fail". Findings are violations only —
    no padding, no forced findings.

    Attributes:
        rule_id: The unique identifier of the violated rule.
        verdict: Always "fail" — findings represent violations only.
        cited_span: The exact source span that triggered the violation.
        explanation: Reasoning for the violation determination.
        evaluation_method: Whether the rule was evaluated by LLM or structured logic.
    """

    rule_id: str
    verdict: Literal["fail"]
    cited_span: CitedSpan
    explanation: str
    evaluation_method: EvaluationMethod
