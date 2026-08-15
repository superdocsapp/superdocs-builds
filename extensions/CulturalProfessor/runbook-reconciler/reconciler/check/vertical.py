"""Claim against ground truth, one claim at a time.

No model, no network, no spend. Everything here is a lookup in files already
read and a comparison already defined, which is why the first useful output of
this whole project costs nothing and runs in a fraction of a second.

## The order of business

1. **The page-level pass runs first.** If a page's subject service resolves to
   nothing in the estate, the page yields one `orphan_runbook` finding and every
   other claim on it is recorded `unverifiable`. Five findings for one dead
   service is five queue entries with one decision behind them, and the decision
   is not "fix this sentence" — it is "archive the page, or name the successor".
2. **Then claim by claim**, against the rules in `config/checks.yaml`.

## The three verdicts, and how each is reached

- `contradicts` — a rule matched, a lookup found ground truth, and the
  comparison said no.
- `agrees` — the same, and the comparison said yes.
- `unverifiable` — *anything else*: no rule matched the subject, the lookup
  found nothing, the comparison could not be made, or the claim contains a
  placeholder. It is reported in every summary and counted separately, because
  a claim reported as correct that was never checked is rule 4 and is the exact
  failure this project exists to fix.

A placeholder is checked before anything else. `kubectl -n <your-namespace>` is
not a namespace that does not exist; it is a runbook written correctly, and a
checker without that convention fires on nearly every command block in a real
estate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from reconciler.check import compare as comparisons
from reconciler.check import lookups
from reconciler.claims import Claim, Finding
from reconciler.config import CONFIG_DIR, display_path
from reconciler.estate import Estate
from reconciler.extract.storage import PLACEHOLDER

#: Where a page's subject service comes from: the claim that names a workload.
_SUBJECT_CLAIM = re.compile(r"^workload:(?P<name>[^:]+):name$")


@dataclass(frozen=True)
class Check:
    """One rule, and — crucially — what its silence means.

    `on_missing` is the difference between a closed world and an open one, and
    getting it wrong in either direction is a real failure. Every CI job in the
    estate is enumerable, so "no job by that name" *proves* the runbook is wrong
    and must be `contradicts`; leaving it `unverifiable` means the tool reads a
    renamed job and says nothing. An identifier in a code span is the opposite:
    it could be a resource, a placeholder or an example, so absence proves
    nothing and calling it a contradiction is crying wolf.

    Neither is inferable from the lookup's return value, so it is declared per
    rule, in the rules file, by whoever knows whether the source is complete.
    """

    id: str
    subject: re.Pattern[str]
    lookup: str
    compare: str
    detail: str = ""
    args: dict[str, Any] = None  # type: ignore[assignment]
    confidence: float = 1.0
    on_missing: str = "unverifiable"

    def match(self, subject: str) -> dict[str, str] | None:
        found = self.subject.match(subject)
        return {k: v for k, v in found.groupdict().items() if v} if found else None


def load_checks(path: Path | None = None) -> list[Check]:
    path = path or CONFIG_DIR / "checks.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        Check(
            id=str(entry["id"]),
            subject=re.compile(entry["subject"]),
            lookup=str(entry["lookup"]),
            compare=str(entry.get("compare", "text")),
            detail=str(entry.get("detail", "")),
            args=dict(entry.get("args") or {}),
            confidence=float(entry.get("confidence", 1.0)),
            on_missing=str(entry.get("on_missing", "unverifiable")),
        )
        for entry in raw.get("checks") or []
    ]


def check_page(
    page_id: str,
    claims: list[Claim],
    estate: Estate,
    checks: list[Check] | None = None,
) -> list[Finding]:
    checks = checks if checks is not None else load_checks()
    orphan = _orphan_finding(page_id, claims, estate)
    if orphan:
        # Everything else on the page is unverifiable by construction: there is
        # nothing left to check it against.
        rest = [
            _unverifiable(
                claim,
                "the service this page describes is not in the declared estate, so nothing "
                "on it can be checked",
            )
            for claim in claims
            if claim.kind != "directive" and not _is_subject_claim(claim)
        ]
        return [orphan, *rest, *[_directive(c) for c in claims if c.kind == "directive"]]

    findings: list[Finding] = []
    for claim in claims:
        findings.append(check_claim(claim, estate, checks))
    return findings


def check_claim(claim: Claim, estate: Estate, checks: list[Check]) -> Finding:
    if claim.kind == "directive":
        return _directive(claim)

    if claim.subject in estate.mappings.ignore_subjects:
        return _unverifiable(claim, "muted in config/mappings.yaml by the team that owns it")

    if PLACEHOLDER.search(claim.asserted):
        return _unverifiable(
            claim,
            "the value is a deliberate placeholder, not a resource that is missing",
        )

    for check in checks:
        groups = check.match(claim.subject)
        if groups is None:
            continue
        return _run(check, claim, estate, groups)

    return _unverifiable(claim, "no rule in config/checks.yaml settles this kind of claim")


def _run(check: Check, claim: Claim, estate: Estate, groups: dict[str, str]) -> Finding:
    resolver = lookups.get(check.lookup)
    if resolver is None:
        # A rules file naming a lookup that does not exist. Loud, not silent:
        # the alternative is a whole class of claim quietly never being checked.
        return _unverifiable(claim, f"config/checks.yaml names an unknown lookup {check.lookup!r}")

    observation = resolver(estate, groups, check.args or {})
    if not observation.found:
        if check.on_missing != "contradicts":
            return _unverifiable(claim, observation.note, rule_id=check.id)
        return Finding(
            rule_id=check.id,
            kind=claim.kind,
            subject=claim.subject,
            verdict="contradicts",
            evidence_file=observation.source.file if observation.source else "",
            evidence_line=observation.source.line if observation.source else None,
            claim_id=claim.claim_id,
            page_id=claim.page_id,
            observed=observation.note,
            confidence=check.confidence,
            detail=check.detail,
            tags=_tags(claim, observation),
        )

    # The rule's own arguments join the observation's context, so a rules file
    # can supply what a bare number in a config file does not carry: Terraform's
    # `backup_retention_period = 14` is fourteen *days*, and only the rule that
    # points at it knows that.
    hint = {**(observation.context or {}), **(check.args or {})}
    verdict = comparisons.compare(check.compare, claim.asserted, observation.value or "", hint)
    if verdict is None:
        return _unverifiable(
            claim,
            f"{claim.asserted!r} and {observation.value!r} are not comparable without "
            f"guessing at units",
            rule_id=check.id,
            observed=observation.value,
        )

    return Finding(
        rule_id=check.id,
        kind=claim.kind,
        subject=claim.subject,
        verdict="agrees" if verdict else "contradicts",
        evidence_file=observation.source.file if observation.source else "",
        evidence_line=observation.source.line if observation.source else None,
        claim_id=claim.claim_id,
        page_id=claim.page_id,
        observed=observation.value,
        confidence=check.confidence,
        detail=check.detail or observation.note,
        tags=_tags(claim, observation),
    )


def _tags(claim: Claim, observation: lookups.Observation) -> tuple[str, ...]:
    tags: list[str] = []
    if not claim.anchor.editable:
        tags.append("comment-only")
    if (observation.context or {}).get("renamed"):
        tags.append("renamed")
    if (observation.context or {}).get("via"):
        tags.append(f"via:{observation.context['via']}")
    return tuple(tags)


# ------------------------------------------------------------ page-level --


def _is_subject_claim(claim: Claim) -> bool:
    return bool(_SUBJECT_CLAIM.match(claim.subject))


def _orphan_finding(page_id: str, claims: list[Claim], estate: Estate) -> Finding | None:
    """One finding for a page about a service that no longer exists."""
    named = [
        _SUBJECT_CLAIM.match(claim.subject).group("name")  # type: ignore[union-attr]
        for claim in claims
        if _is_subject_claim(claim)
    ]
    if not named or any(estate.resolve(name).resolved for name in named):
        return None

    subject_claim = next(claim for claim in claims if _is_subject_claim(claim))
    service = named[0]
    return Finding(
        rule_id="orphan-runbook",
        kind="resource",
        subject=f"service:{service}",
        verdict="contradicts",
        evidence_file=display_path(_kubernetes_root(estate)),
        claim_id=subject_claim.claim_id,
        page_id=page_id,
        observed="no deployment, no catalog entry, no former-name annotation",
        detail=(
            f"this page describes {service}, which is not in the declared estate. The fix is "
            f"a decision -- archive the page, or record who owns the successor -- so this is "
            f"flagged rather than edited"
        ),
        tags=("orphan", "comment-only"),
    )


def _kubernetes_root(estate: Estate) -> str:
    """Evidence for an absence has to point somewhere real.

    Rule 8 does not get a pass because the finding is about something that is
    not there: the honest citation is the place it would have been.
    """
    return estate.workloads[0].source.file.rsplit("/", 2)[0] if estate.workloads else "."


def _directive(claim: Claim) -> Finding:
    return Finding(
        rule_id="instructions-to-automation",
        kind="directive",
        subject=claim.subject,
        verdict="contradicts",
        evidence_file=f"confluence:page:{claim.page_id}",
        claim_id=claim.claim_id,
        page_id=claim.page_id,
        observed="page content is data to this tool, never instruction",
        detail=(
            "this passage addresses the tooling reading the page. It is reported and not "
            "acted on; it is also not deleted, because somebody put it there and a human "
            "should decide what that means"
        ),
        tags=("injection", "comment-only"),
    )


def _unverifiable(
    claim: Claim, note: str, rule_id: str = "unmatched", observed: str | None = None
) -> Finding:
    return Finding(
        rule_id=rule_id,
        kind=claim.kind,
        subject=claim.subject,
        verdict="unverifiable",
        # The claim's own page is where the evidence is: the thing that could
        # not be checked is the sentence itself.
        evidence_file=f"confluence:page:{claim.page_id}",
        claim_id=claim.claim_id,
        page_id=claim.page_id,
        observed=observed,
        confidence=0.0,
        detail=note,
    )


__all__ = ["Check", "check_claim", "check_page", "load_checks"]
