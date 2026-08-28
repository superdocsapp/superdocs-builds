"""Evaluator protocol and implementations for the rules checking stage.

Provides a RuleEvaluator protocol for evaluating compliance rules against
source document spans, an LLM-based implementation (default), and a
structured (deterministic) implementation for opt-in rules.

LLM evaluation batches multiple rules per span to reduce API calls.
On API failure, exceptions are raised and caught by the node as transient errors.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Protocol

from src.pipeline.findings import (
    CitedSpan,
    EvaluationMethod,
    EvaluationResult,
    FindingVerdict,
)
from src.pipeline.playbook import RuleDefinition

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM API interaction.

    Implementations must provide a chat method that accepts a system prompt,
    user prompt, and returns a parsed structured response.
    """

    async def chat(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send a prompt to the LLM and return a structured response.

        Args:
            system_prompt: Instructions for the LLM behavior.
            user_prompt: The actual evaluation request.

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            Exception: On API failure (timeout, rate-limit, connection error).
        """
        ...


class RuleEvaluator(Protocol):
    """Protocol for evaluating a rule against a source span."""

    async def evaluate(
        self,
        rule: RuleDefinition,
        span_text: str,
        span_offset: int,
    ) -> EvaluationResult:
        """Evaluate a single rule against a source span.

        Args:
            rule: The rule to evaluate.
            span_text: The text content of the source span.
            span_offset: The start offset of the span in the original document.

        Returns:
            EvaluationResult with verdict, cited_span, and explanation.
        """
        ...


_SYSTEM_PROMPT = """You are a compliance rule evaluator. You evaluate whether a source document \
span violates a specific compliance rule.

You MUST return a JSON object with the following fields:
- "verdict": one of "pass", "fail", "not_applicable", or "insufficient_evidence"
- "cited_start": integer start offset (0-based, relative to the span start) of the relevant text
- "cited_end": integer end offset (0-based, exclusive, relative to the span start) of the relevant text
- "cited_text": the exact text from the span that is most relevant to the evaluation
- "explanation": a brief explanation of your verdict

If the rule is not applicable to this span, return verdict "not_applicable".
If there is not enough information in the span to make a determination, return "insufficient_evidence".
Only return "fail" if there is a clear violation of the rule in the span.

Return ONLY valid JSON, no additional text."""

_BATCH_SYSTEM_PROMPT = """You are a compliance rule evaluator. You evaluate whether a source document \
span violates one or more compliance rules.

You MUST return a JSON array where each element corresponds to a rule (in the same order as provided) \
with the following fields:
- "rule_id": the id of the rule being evaluated
- "verdict": one of "pass", "fail", "not_applicable", or "insufficient_evidence"
- "cited_start": integer start offset (0-based, relative to the span start) of the relevant text
- "cited_end": integer end offset (0-based, exclusive, relative to the span start) of the relevant text
- "cited_text": the exact text from the span that is most relevant to the evaluation
- "explanation": a brief explanation of your verdict

If a rule is not applicable to this span, return verdict "not_applicable" for that rule.
If there is not enough information in the span to make a determination, return "insufficient_evidence".
Only return "fail" if there is a clear violation of the rule in the span.

Return ONLY a valid JSON array, no additional text."""


class LLMEvaluator:
    """Evaluates rules using LLM with structured output.

    Implements the RuleEvaluator protocol and provides an additional
    evaluate_batch() method for batching multiple rules per span to
    reduce API calls.

    On LLM API failure, exceptions propagate to the caller (the node
    catches them and sets transient error state).
    """

    def __init__(self, llm_client: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm_client: An implementation of the LLMClient protocol.
        """
        self._client = llm_client

    async def evaluate(
        self,
        rule: RuleDefinition,
        span_text: str,
        span_offset: int,
    ) -> EvaluationResult:
        """Evaluate a single rule against a source span via LLM.

        The LLM prompt includes the rule description, check_description,
        source span text, and instructions to return a structured verdict.

        Args:
            rule: The rule to evaluate.
            span_text: The text content of the source span.
            span_offset: The start offset of the span in the original document.

        Returns:
            EvaluationResult with evaluation_method="llm".

        Raises:
            Exception: On LLM API failure (caught by node as transient error).
        """
        user_prompt = self._build_single_prompt(rule, span_text)

        # LLM API call — exceptions propagate on failure
        response = await self._client.chat(_SYSTEM_PROMPT, user_prompt)

        return self._parse_single_response(response, rule, span_text, span_offset)

    async def evaluate_batch(
        self,
        rules: list[RuleDefinition],
        span_text: str,
        span_offset: int,
    ) -> list[EvaluationResult]:
        """Evaluate multiple rules against a single span in one LLM call.

        Reduces API calls by batching rules per span. If only one rule is
        provided, delegates to the single evaluate method.

        Args:
            rules: List of rules to evaluate against the span.
            span_text: The text content of the source span.
            span_offset: The start offset of the span in the original document.

        Returns:
            List of EvaluationResult (one per rule, same order as input).

        Raises:
            Exception: On LLM API failure (caught by node as transient error).
        """
        if not rules:
            return []

        if len(rules) == 1:
            result = await self.evaluate(rules[0], span_text, span_offset)
            return [result]

        user_prompt = self._build_batch_prompt(rules, span_text)

        # LLM API call — exceptions propagate on failure
        response = await self._client.chat(_BATCH_SYSTEM_PROMPT, user_prompt)

        return self._parse_batch_response(response, rules, span_text, span_offset)

    def _build_single_prompt(self, rule: RuleDefinition, span_text: str) -> str:
        """Build the user prompt for evaluating a single rule."""
        return (
            f"Rule ID: {rule.id}\n"
            f"Rule Description: {rule.description}\n"
            f"Check Instructions: {rule.check_description}\n\n"
            f"Source Span Text:\n---\n{span_text}\n---\n\n"
            f"Evaluate this span against the rule and return the JSON verdict."
        )

    def _build_batch_prompt(
        self, rules: list[RuleDefinition], span_text: str
    ) -> str:
        """Build the user prompt for evaluating multiple rules against one span."""
        rules_section = "\n".join(
            f"- Rule ID: {rule.id}\n"
            f"  Description: {rule.description}\n"
            f"  Check Instructions: {rule.check_description}"
            for rule in rules
        )
        return (
            f"Rules to evaluate:\n{rules_section}\n\n"
            f"Source Span Text:\n---\n{span_text}\n---\n\n"
            f"Evaluate this span against each rule and return the JSON array of verdicts."
        )

    def _parse_single_response(
        self,
        response: dict[str, Any],
        rule: RuleDefinition,
        span_text: str,
        span_offset: int,
    ) -> EvaluationResult:
        """Parse a single LLM response into an EvaluationResult."""
        verdict: FindingVerdict = response.get("verdict", "insufficient_evidence")
        cited_start: int = response.get("cited_start", 0)
        cited_end: int = response.get("cited_end", len(span_text))
        cited_text: str = response.get("cited_text", span_text[cited_start:cited_end])
        explanation: str = response.get("explanation", "")

        # Clamp offsets to valid range
        cited_start = max(0, min(cited_start, len(span_text)))
        cited_end = max(cited_start, min(cited_end, len(span_text)))

        cited_span = CitedSpan(
            start_offset=span_offset + cited_start,
            end_offset=span_offset + cited_end,
            text=cited_text,
        )

        return EvaluationResult(
            rule_id=rule.id,
            verdict=verdict,
            cited_span=cited_span,
            explanation=explanation,
            evaluation_method="llm",
        )

    def _parse_batch_response(
        self,
        response: Any,
        rules: list[RuleDefinition],
        span_text: str,
        span_offset: int,
    ) -> list[EvaluationResult]:
        """Parse a batch LLM response into a list of EvaluationResults.

        The response should be a list of dicts, one per rule in order.
        If the response is malformed or has fewer items than rules,
        missing entries default to 'insufficient_evidence'.
        """
        results: list[EvaluationResult] = []

        # Response should be a list; handle if it's something else
        if isinstance(response, dict) and "results" in response:
            response_list = response["results"]
        elif isinstance(response, list):
            response_list = response
        else:
            # Fallback: treat entire response as insufficient evidence for all rules
            logger.warning(
                "Unexpected batch response format, returning insufficient_evidence "
                "for all %d rules",
                len(rules),
            )
            for rule in rules:
                results.append(
                    EvaluationResult(
                        rule_id=rule.id,
                        verdict="insufficient_evidence",
                        cited_span=CitedSpan(
                            start_offset=span_offset,
                            end_offset=span_offset + len(span_text),
                            text=span_text,
                        ),
                        explanation="Batch response was malformed",
                        evaluation_method="llm",
                    )
                )
            return results

        for i, rule in enumerate(rules):
            if i < len(response_list):
                item = response_list[i]
                results.append(
                    self._parse_single_response(item, rule, span_text, span_offset)
                )
            else:
                # Missing response entry — default to insufficient_evidence
                results.append(
                    EvaluationResult(
                        rule_id=rule.id,
                        verdict="insufficient_evidence",
                        cited_span=CitedSpan(
                            start_offset=span_offset,
                            end_offset=span_offset + len(span_text),
                            text=span_text,
                        ),
                        explanation="No response received for this rule in batch",
                        evaluation_method="llm",
                    )
                )

        return results


# --- Structured Check Functions ---
# Each function accepts (span_text: str, span_offset: int) and returns a dict
# with keys: verdict, cited_start, cited_end, cited_text, explanation


def _check_apr_exceeds_36(span_text: str, span_offset: int) -> dict[str, Any]:
    """Check if a stated APR exceeds 36%.

    Searches the span text for percentage patterns and determines if any
    numeric value associated with APR/interest rate exceeds 36%.

    Args:
        span_text: The text content of the source span.
        span_offset: The start offset of the span in the original document.

    Returns:
        Dict with verdict, cited_start, cited_end, cited_text, explanation.
    """
    # Pattern matches percentages like "42%", "42.5%", "42.00%"
    percentage_pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
    )

    matches = list(percentage_pattern.finditer(span_text))

    if not matches:
        return {
            "verdict": "not_applicable",
            "cited_start": 0,
            "cited_end": len(span_text),
            "cited_text": span_text,
            "explanation": "No percentage values found in span.",
        }

    for match in matches:
        value = float(match.group(1))
        if value > 36.0:
            return {
                "verdict": "fail",
                "cited_start": match.start(),
                "cited_end": match.end(),
                "cited_text": match.group(0),
                "explanation": (
                    f"Found rate of {value}% which exceeds the 36% maximum."
                ),
            }

    # All percentages found are <= 36%
    # Return pass citing the last match found
    last_match = matches[-1]
    return {
        "verdict": "pass",
        "cited_start": last_match.start(),
        "cited_end": last_match.end(),
        "cited_text": last_match.group(0),
        "explanation": "All percentage values in span are at or below 36%.",
    }


# Type alias for structured check callables
StructuredCheckFn = Callable[[str, int], dict[str, Any]]


class StructuredEvaluator:
    """Evaluates rules using deterministic structured logic.

    Uses a registry (SUPPORTED_CHECKS) mapping check_description strings
    to callable functions that perform deterministic evaluation. This avoids
    LLM calls for rules where structured logic can produce reliable results.

    Each registered check function accepts (span_text, span_offset) and returns
    a dict with: verdict, cited_start, cited_end, cited_text, explanation.
    """

    # Registry of supported check_descriptions → callable logic
    SUPPORTED_CHECKS: dict[str, StructuredCheckFn] = {
        "Check if the stated annual percentage rate (APR) exceeds 36%.\n"
        "Look for interest rate declarations in loan terms.\n": _check_apr_exceeds_36,
    }

    def supports(self, rule: RuleDefinition) -> bool:
        """Return True if this evaluator can handle the rule.

        Checks whether the rule's check_description is registered in
        SUPPORTED_CHECKS.

        Args:
            rule: The rule to check for support.

        Returns:
            True if the rule's check_description has a registered handler.
        """
        return rule.check_description in self.SUPPORTED_CHECKS

    async def evaluate(
        self,
        rule: RuleDefinition,
        span_text: str,
        span_offset: int,
    ) -> EvaluationResult:
        """Execute deterministic check logic for a rule.

        Looks up the rule's check_description in SUPPORTED_CHECKS and
        invokes the corresponding callable. Returns an EvaluationResult
        with evaluation_method="structured".

        Args:
            rule: The rule to evaluate (must be supported).
            span_text: The text content of the source span.
            span_offset: The start offset of the span in the original document.

        Returns:
            EvaluationResult with evaluation_method="structured".

        Raises:
            KeyError: If the rule's check_description is not in SUPPORTED_CHECKS.
        """
        check_fn = self.SUPPORTED_CHECKS[rule.check_description]
        result = check_fn(span_text, span_offset)

        verdict: FindingVerdict = result["verdict"]
        cited_start: int = result["cited_start"]
        cited_end: int = result["cited_end"]
        cited_text: str = result["cited_text"]
        explanation: str = result["explanation"]

        # Clamp offsets to valid range
        cited_start = max(0, min(cited_start, len(span_text)))
        cited_end = max(cited_start, min(cited_end, len(span_text)))

        cited_span = CitedSpan(
            start_offset=span_offset + cited_start,
            end_offset=span_offset + cited_end,
            text=cited_text,
        )

        return EvaluationResult(
            rule_id=rule.id,
            verdict=verdict,
            cited_span=cited_span,
            explanation=explanation,
            evaluation_method="structured",
        )
