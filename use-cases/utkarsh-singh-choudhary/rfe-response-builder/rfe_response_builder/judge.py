"""
LLM-as-judge quality gate.

`is_substantive_reply` (rfe.py) already catches the cheap failure mode --
a reply that's an outright refusal/hedge/empty response. It cannot catch
the more common, more subtle failure mode: a reply that IS substantive
(passes the length/pattern check) but doesn't actually engage the
officer's specific stated concern -- e.g. it restates the original
petition, or answers a nearby-but-different point. Catching that
reliably needs semantic judgment, not more regex.

This module makes a second, focused model call -- via the same
`SuperDocsClient` already used for drafting -- asking it to grade one
drafted section against the officer's exact concern and return a small
structured verdict. This is "LLM-as-judge": using a model call to check
a model's own (or another turn's) output, a well-established pattern for
catching quality issues a static heuristic can't.

This is opt-in (`QUALITY_GATE_ENABLED=1`) and OFF by default, for two
honest reasons: (1) it doubles the number of API calls for every
substantively-answered item, a real cost/latency tradeoff a firm should
choose deliberately, not have silently imposed; (2) it's still a
heuristic, not a certainty -- a "weak" verdict is exactly like a
`fuzzy_matches`/`ungrounded_facts` flag: something for the human reviewer
to look at twice, never an auto-reject. The human is always the one who
approves or rejects a section; this narrows what they should look at
first.

Grading failures (a malformed/unparseable response, or the grading call
itself failing) degrade to `QualityVerdict.UNKNOWN` rather than raising
or silently defaulting to "looks good" -- an unreadable verdict must
never be presented to a reviewer as a clean bill of health.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum

from .superdocs_client import SuperDocsClient, SuperDocsError

logger = logging.getLogger("rfe_response_builder.judge")

_GRADING_INSTRUCTION_TEMPLATE = (
    "You are reviewing a DRAFT response section against the officer's SPECIFIC concern, "
    "not the topic in general. Respond with ONLY a JSON object (no markdown fences, no "
    "other text) with exactly these keys:\n"
    "  \"addresses_concern\": true or false -- does the draft directly engage the officer's "
    "stated concern below, rather than restating the original petition or answering a "
    "nearby-but-different point?\n"
    "  \"reasoning\": a one-sentence explanation of your verdict.\n\n"
    "Officer's concern: \"{request_text}\"\n\n"
    "Draft section:\n\"{draft_text}\""
)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class QualityVerdict(str, Enum):
    STRONG = "strong"  # model judged the draft as directly addressing the concern
    WEAK = "weak"  # model judged the draft as NOT directly addressing the concern
    UNKNOWN = "unknown"  # grading call failed, or its response couldn't be parsed


@dataclass
class QualityGateResult:
    verdict: QualityVerdict
    reasoning: str = ""


def _parse_verdict(raw_text: str) -> QualityGateResult:
    match = _JSON_BLOCK_RE.search(raw_text or "")
    if not match:
        return QualityGateResult(verdict=QualityVerdict.UNKNOWN, reasoning="grading response was not JSON")
    try:
        data = json.loads(match.group(0))
        addresses_concern = data["addresses_concern"]
        reasoning = str(data.get("reasoning", "")).strip()
    except (json.JSONDecodeError, KeyError, TypeError):
        return QualityGateResult(verdict=QualityVerdict.UNKNOWN, reasoning="grading response JSON was malformed")

    if not isinstance(addresses_concern, bool):
        return QualityGateResult(verdict=QualityVerdict.UNKNOWN,
                                  reasoning="grading response 'addresses_concern' was not a boolean")
    return QualityGateResult(
        verdict=QualityVerdict.STRONG if addresses_concern else QualityVerdict.WEAK,
        reasoning=reasoning,
    )


def grade_draft(client: SuperDocsClient, grading_session_id: str, request_text: str,
                 draft_text: str) -> QualityGateResult:
    """Sends one grading turn to SuperDocs on a SEPARATE session
    (`grading_session_id`, never the drafting session -- grading must not
    pollute the document-editing conversation) and parses the structured
    verdict. Any failure -- network, retries exhausted, unparseable
    response -- degrades to `QualityVerdict.UNKNOWN`, logged, never
    raised, so a grading-call outage can never block the actual drafting
    pipeline it's meant to be an optional add-on to."""
    instruction = _GRADING_INSTRUCTION_TEMPLATE.format(request_text=request_text, draft_text=draft_text)
    try:
        result = client.chat(session_id=grading_session_id, message=instruction)
    except SuperDocsError as e:
        logger.warning("quality-gate grading call failed, verdict=unknown: %s", e)
        return QualityGateResult(verdict=QualityVerdict.UNKNOWN, reasoning=f"grading call failed: {e}")
    return _parse_verdict(result.reply_text)
