from __future__ import annotations

from config.credit import CREDIT_ROLE_IDS
from schemas.declare import StatementRequest
from utils.common import issue


def review_issues(facts: StatementRequest) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    author_ids = {author.id for author in facts.authors}
    for contribution in facts.contributions:
        if contribution.status == "ambiguous" or not contribution.roleIds:
            issues.append(issue("AMBIGUOUS_CONTRIBUTION", f"Contribution for {contribution.authorId} still needs review.", authorId=contribution.authorId))
            continue
        if contribution.authorId not in author_ids:
            issues.append(issue("UNKNOWN_AUTHOR", f'Contribution references unknown author "{contribution.authorId}".', authorId=contribution.authorId))
        for role_id in contribution.roleIds:
            if role_id not in CREDIT_ROLE_IDS:
                issues.append(issue("INVALID_CREDIT_ROLE", f'Unsupported CRediT role "{role_id}".', authorId=contribution.authorId, roleId=role_id))
    if not any(item.status == "approved" and item.roleIds for item in facts.contributions):
        issues.append(issue("AMBIGUOUS_CONTRIBUTION", "At least one approved contribution with roles is required."))
    if facts.funding.status == "reported" and not facts.funding.funder:
        issues.append(issue("INVALID_FUNDING", "Reported funding needs a reviewed funder name."))
    if facts.conflicts.status == "unknown":
        issues.append(issue("INVALID_CONFLICT", "Conflict-of-interest information must be reviewed before rendering."))
    if facts.conflicts.status == "reported" and not facts.conflicts.items:
        issues.append(issue("INVALID_CONFLICT", "Reported conflicts need at least one reviewed disclosure."))
    for conflict in facts.conflicts.items:
        if conflict.authorId and conflict.authorId not in author_ids:
            issues.append(issue("UNKNOWN_AUTHOR", f'Conflict disclosure references unknown author "{conflict.authorId}".', authorId=conflict.authorId))
    return issues
