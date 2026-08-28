"""Review-queue enrichment — a rendering-pass data join, not new logic.

Every field surfaced here already exists somewhere in durable state:

- confidence            → claims in the extract_claims output_state
- confidence_threshold  → runs.config_snapshot (frozen at run start)
- escalation_reason     → derivable by reading the verdict entry the same
                          way route_to_queue already did when it decided
                          to escalate (priority: permanent-error >
                          non_compliant > needs_human_review > low
                          confidence > no verdict)
- retry counts          → retries dict accumulated in state (route_to_queue
                          output_state)
- rule text             → playbook rules (id → description +
                          check_description), loaded via the existing
                          playbook loader

This module only READS those values and attaches them to queue-item
details so the review UI can render them. It never recomputes verdicts,
never mutates stored payloads.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def _latest_step(outputs: dict[str, list[dict]], name: str) -> dict:
    """Output_state of the latest step with the given node name."""
    candidates = outputs.get(name) or []
    return candidates[-1].get("output_state") or {} if candidates else {}


def build_run_review_context(
    run_row: Any,
    step_rows: list[dict[str, Any]],
    rules_by_id: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Assemble the per-run enrichment context from raw DB rows.

    Args:
        run_row: Mapping with config_snapshot (dict) from the runs table.
        step_rows: List of {step_name, output_state} dicts ordered by
            step_order (ascending).
        rules_by_id: Preloaded playbook rules keyed by rule id, each with
            description and check_description.
    """
    snapshot = run_row.config_snapshot if isinstance(run_row.config_snapshot, dict) else {}

    outputs: dict[str, list[dict]] = {}
    for row in step_rows:
        outputs.setdefault(row["step_name"], []).append(row)

    claims_out = _latest_step(outputs, "extract_claims")
    rules_out = _latest_step(outputs, "match_rules")
    route_out = _latest_step(outputs, "route_to_queue")

    confidence_by_claim = {
        c.get("claim_id"): c.get("confidence")
        for c in claims_out.get("claims", [])
        if isinstance(c, dict)
    }
    verdict_by_claim = {
        v.get("claim_id"): v
        for v in rules_out.get("verdicts", [])
        if isinstance(v, dict)
    }

    return {
        "confidence_threshold": snapshot.get("confidence_threshold"),
        "playbook_id": snapshot.get("playbook_id"),
        "retries": route_out.get("retries", {}),
        "escalated_from_permanent_error": route_out.get("error_type")
        == "permanent",
        "confidence_by_claim": confidence_by_claim,
        "verdict_by_claim": verdict_by_claim,
        "rules_by_id": rules_by_id,
    }


def make_db_context_provider(session_factory) -> Callable[[str], dict]:
    """Provider wired at app startup: reads Postgres for a given run."""

    def provider(run_id: str) -> dict:
        import uuid

        from sqlalchemy import select

        try:
            run_uuid = uuid.UUID(run_id)
        except (ValueError, AttributeError):
            return {}

        session = session_factory()
        try:
            from src.models.runs import Run, RunStep

            run = session.execute(
                select(Run).where(Run.id == run_uuid)
            ).scalar_one_or_none()
            if run is None:
                return {}
            steps = session.execute(
                select(RunStep)
                .where(RunStep.run_id == run_uuid)
                .order_by(RunStep.step_order)
            ).scalars().all()

            # Rule text comes from the playbook the run was started with.
            rules_by_id: dict[str, dict[str, str]] = {}
            snapshot = run.config_snapshot if isinstance(run.config_snapshot, dict) else {}
            playbook_id = snapshot.get("playbook_id") or snapshot.get("playbook")
            if playbook_id:
                try:
                    from src.pipeline.playbook import load_playbook

                    playbook = load_playbook(str(playbook_id))
                    rules_by_id = {
                        r.id: {
                            "description": r.description,
                            "check_description": r.check_description,
                            "check_type": r.check_type,
                        }
                        for r in playbook.rules
                    }
                except Exception:
                    rules_by_id = {}

            return build_run_review_context(
                run,
                [
                    {
                        "step_name": s.step_name,
                        "output_state": s.output_state or {},
                    }
                    for s in steps
                ],
                rules_by_id,
            )
        finally:
            session.close()

    return provider


def derive_escalation_reason(
    claim_id: str,
    context: dict[str, Any],
) -> Optional[str]:
    """Why this claim reached the human queue — read off the same inputs
    route_to_queue used. Returns None when nothing explains escalation."""
    if context.get("escalated_from_permanent_error"):
        return "permanent_error_escalation"

    verdict_entry: Optional[dict] = context["verdict_by_claim"].get(claim_id)
    threshold = context.get("confidence_threshold")

    if verdict_entry is None:
        return "no_verdict_recorded"
    if verdict_entry.get("verdict") == "non_compliant":
        return "non_compliant_verdict"
    if verdict_entry.get("needs_human_review"):
        return "flagged_for_human_review"
    try:
        if (
            threshold is not None
            and float(verdict_entry.get("confidence", 1.0)) < float(threshold)
        ):
            return "low_confidence"
    except (TypeError, ValueError):
        pass
    return "unclassified"


def enrich_item_details(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Return an enriched copy of a queue item payload (not persisted).

    Adds provenance fields under details; existing keys are never
    overwritten (enqueue-time values win).
    """
    details = payload.get("details") or {}
    claim_id = details.get("claim_id") or payload.get("claim_id")

    enriched = dict(details)

    enriched.setdefault(
        "confidence",
        context.get("confidence_by_claim", {}).get(claim_id),
    )
    enriched.setdefault("confidence_threshold", context.get("confidence_threshold"))
    enriched.setdefault("playbook_id", context.get("playbook_id"))

    if "retries" not in enriched:
        retries = {
            node: count for node, count in (context.get("retries") or {}).items() if count
        }
        enriched["retries"] = retries or None

    rule_id = enriched.get("rule_id")
    rule = (context.get("rules_by_id") or {}).get(rule_id) if rule_id else None
    if rule:
        enriched.setdefault("rule_description", rule.get("description"))
        enriched.setdefault("rule_check_description", rule.get("check_description"))

    if claim_id:
        enriched.setdefault("escalation_reason", derive_escalation_reason(claim_id, context))

    payload = dict(payload)
    payload["details"] = enriched
    return payload
