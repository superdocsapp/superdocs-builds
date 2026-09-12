import json
import re
from typing import Any


def quote_grounded(quote: str, source_text: str) -> bool:
    """Check whether a quoted claim appears in the source document text.

    Matches the Task 1 grounding rule: normalize whitespace and compare
    case-insensitively.
    """
    if not quote or not source_text:
        return False
    normalized_quote = " ".join(str(quote).split()).strip().lower()
    normalized_source = " ".join(str(source_text).split()).lower()
    return normalized_quote in normalized_source


def _coerce_entailment_payload(response: Any) -> dict:
    if isinstance(response, dict):
        payload = response
    elif isinstance(response, str):
        payload = {}
        match = re.search(r"verdict\s*[:\-]\s*(yes|no|partial|unverifiable)\s*", response, flags=re.IGNORECASE)
        if match:
            payload["verdict"] = match.group(1).lower()
        match_reason = re.search(r"reason\s*[:\-]\s*(.*)", response, flags=re.IGNORECASE | re.DOTALL)
        if match_reason:
            payload["reason"] = match_reason.group(1).strip()
        if not payload:
            raise ValueError("Could not parse entailment verdict from text response.")
    elif hasattr(response, "json"):
        payload = response.json()
    else:
        raise ValueError(f"Unsupported entailment response type: {type(response).__name__}")

    if not isinstance(payload, dict):
        raise ValueError("Entailment response must be a dict or parseable text.")

    verdict = payload.get("verdict")
    if verdict is None:
        # Some API wrappers may use a nested structure or a different key.
        for key in ("result", "status", "outcome"):
            if key in payload:
                verdict = payload[key]
                break
    if verdict is None:
        raise ValueError("Entailment response missing 'verdict'.")

    verdict = str(verdict).strip().lower()
    valid = {"yes", "no", "partial", "unverifiable"}
    if verdict not in valid:
        raise ValueError(f"Entailment verdict '{verdict}' is invalid; expected one of {sorted(valid)}.")

    reason = payload.get("reason") or payload.get("explanation") or payload.get("details") or ""
    if isinstance(reason, (dict, list)):
        reason = json.dumps(reason, ensure_ascii=True, default=str)
    reason = str(reason).strip() if reason is not None else ""
    if not reason:
        reason = "No reason provided."

    return {"verdict": verdict, "reason": reason}


def check_entailment(claim: str, source_passage: str, client) -> dict:
    """Independently ask a fresh model call whether a passage supports a claim.

    The client is expected to provide a .chat(...) method that returns either a
    dict or a plain-text verdict/reason payload.
    """
    response = client.chat(
        message=(
            "Determine whether the following source passage supports the claim. "
            "Respond with a verdict of yes, no, partial, or unverifiable and a "
            "one-sentence reason.\n\nClaim: "
            f"{claim}\n\nPassage: {source_passage}"
        )
    )
    return _coerce_entailment_payload(response)
