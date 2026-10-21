from __future__ import annotations

from collections import defaultdict

from config.credit import CREDIT_ROLES
from schemas.declare import StatementRequest


def render_statements(facts: StatementRequest) -> dict[str, str]:
    roles_by_author: dict[str, set[str]] = defaultdict(set)
    for contribution in facts.contributions:
        if contribution.status == "approved":
            roles_by_author[contribution.authorId].update(contribution.roleIds)
    lines = []
    for author in facts.authors:
        if author.id in roles_by_author:
            labels = sorted(CREDIT_ROLES[role_id]["label"] if role_id in CREDIT_ROLES else role_id for role_id in roles_by_author[author.id])
            lines.append(f"{author.name}: {', '.join(labels)}.")
    funding = f"Funding\n\nThis work was supported by {facts.funding.funder}{f' (grant {facts.funding.awardNumber})' if facts.funding.awardNumber else ''}." if facts.funding.status == "reported" else "Funding\n\nThis research received no external funding." if facts.funding.status == "none" else "Funding\n\nFunding information was not provided."
    conflicts = "The authors declare no competing interests." if facts.conflicts.status == "none" else "; ".join(item.disclosure or item.evidence for item in facts.conflicts.items)
    return {"contributionStatement": "Author Contributions\n\n" + "\n".join(lines), "fundingStatement": funding, "conflictStatement": f"Competing Interests\n\n{conflicts}"}


def escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def render_statements_html(statements: dict[str, str]) -> str:
    def to_html(statement: str) -> str:
        heading, *rest = statement.split("\n\n", 1)
        paragraphs = "".join(f"<p>{escape_html(line)}</p>" for line in (rest[0] if rest else "").split("\n") if line)
        return f"<h2>{escape_html(heading)}</h2>{paragraphs}"
    return '<section data-declare-statements="true">' + "".join(to_html(statements[key]) for key in ("contributionStatement", "fundingStatement", "conflictStatement")) + "</section>"
