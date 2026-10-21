from __future__ import annotations

import re
from typing import Any

from config.credit import CREDIT_ROLE_IDS
from schemas.declare import AnalyzeRequest, AnalysisProviderResponse
from utils.common import issue


def contains_evidence(source: str, evidence: str) -> bool:
    return bool(evidence.strip()) and evidence.strip().casefold() in source.casefold()


def supports_funding_acquisition(evidence: str) -> bool:
    return bool(re.search(r"\b(acquired|secured|obtained|raised) (the )?(funding|grant)|funding acquisition\b", evidence, re.IGNORECASE))


def validate_analysis(request: AnalyzeRequest, analysis: AnalysisProviderResponse) -> dict[str, Any]:
    author_ids = {author.id for author in request.authors}
    issues: list[dict[str, str]] = []
    contributions: list[dict[str, Any]] = []
    for contribution in analysis.contributions:
        if contribution.authorId not in author_ids:
            issues.append(issue("UNKNOWN_AUTHOR", f'Contribution references unknown author "{contribution.authorId}".', authorId=contribution.authorId))
            continue
        has_valid_evidence = contains_evidence(request.contributions, contribution.evidence)
        role_ids = list(dict.fromkeys(role_id for role_id in contribution.roleIds if role_id in CREDIT_ROLE_IDS))
        for role_id in contribution.roleIds:
            if role_id not in CREDIT_ROLE_IDS:
                issues.append(issue("INVALID_CREDIT_ROLE", f'Unsupported CRediT role "{role_id}".', authorId=contribution.authorId, roleId=role_id))
        if not has_valid_evidence:
            issues.append(issue("MISSING_EVIDENCE", "Contribution evidence must be an exact phrase from the supplied contribution text.", authorId=contribution.authorId))
            role_ids = []
        if "funding_acquisition" in contribution.roleIds and not supports_funding_acquisition(contribution.evidence):
            issues.append(issue("INVALID_CREDIT_ROLE", "funding_acquisition requires evidence that the author secured funding.", authorId=contribution.authorId, roleId="funding_acquisition"))
            role_ids = [role_id for role_id in role_ids if role_id != "funding_acquisition"]
        status = contribution.status
        if not has_valid_evidence or (status == "proposed" and not role_ids):
            status = "ambiguous"
        if status == "ambiguous":
            issues.append(issue("AMBIGUOUS_CONTRIBUTION", "Contribution needs researcher review before roles can be approved.", authorId=contribution.authorId))
        if status == "unsupported":
            issues.append(issue("UNSUPPORTED_CONTRIBUTION", "Contribution evidence does not support a specific CRediT role.", authorId=contribution.authorId))
        contributions.append({"authorId": contribution.authorId, "evidence": contribution.evidence, "roleIds": role_ids if status == "proposed" else [], "status": status})

    funding = {"status": "unknown", "evidence": ""} if not request.funding.strip() else analysis.funding.model_dump()
    if funding["status"] == "reported" and not funding.get("funder"):
        issues.append(issue("INVALID_FUNDING", "Reported funding is missing a funder name."))
    if funding["status"] == "reported" and not contains_evidence(request.funding, funding.get("evidence", "")):
        issues.append(issue("INVALID_FUNDING", "Funding evidence must be an exact phrase from the supplied funding text."))

    if not request.conflicts.strip():
        conflicts = {"status": "unknown", "items": []}
    else:
        items = []
        for item in analysis.conflicts.items:
            has_valid_evidence = contains_evidence(request.conflicts, item.evidence)
            if not has_valid_evidence:
                issues.append(issue("INVALID_CONFLICT", "Conflict evidence must be an exact phrase from the supplied conflict text.", authorId=item.authorId))
            if item.authorId and item.authorId not in author_ids:
                issues.append(issue("UNKNOWN_AUTHOR", f'Conflict disclosure references unknown author "{item.authorId}".', authorId=item.authorId))
                continue
            if has_valid_evidence:
                items.append(item.model_dump())
        conflicts = {"status": analysis.conflicts.status, "items": [{"status": analysis.conflicts.status, **item} for item in items]}

    if not contributions:
        issues.append(issue("AMBIGUOUS_CONTRIBUTION", "No contribution could be mapped from the supplied text."))
    return {"contributions": contributions, "funding": funding, "conflicts": conflicts, "issues": issues}
