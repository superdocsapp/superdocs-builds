from schemas.declare import StatementRequest
from utils.review import review_issues
from utils.statements import escape_html, render_statements, render_statements_html


def reviewed_facts() -> StatementRequest:
    return StatementRequest.model_validate({"authors": [{"id": "a", "name": "A & B"}], "contributions": [{"authorId": "a", "evidence": "built", "roleIds": ["software", "software"], "status": "approved"}], "funding": {"status": "none"}, "conflicts": {"status": "none", "items": []}})


def test_renderer_deduplicates_roles_and_preserves_author_order():
    statements = render_statements(reviewed_facts())
    assert statements["contributionStatement"] == "Author Contributions\n\nA & B: Software."


def test_html_renderer_escapes_all_required_characters():
    assert escape_html("&<>\"'") == "&amp;&lt;&gt;&quot;&#39;"
    assert "A &amp; B: Software." in render_statements_html(render_statements(reviewed_facts()))


def test_review_flags_unknown_conflicts_and_ambiguous_contributions():
    facts = StatementRequest.model_validate({"authors": [{"id": "a", "name": "A"}], "contributions": [{"authorId": "a", "evidence": "helped", "roleIds": [], "status": "ambiguous"}], "funding": {"status": "none"}, "conflicts": {"status": "reported", "items": []}})
    types = {entry["type"] for entry in review_issues(facts)}
    assert {"AMBIGUOUS_CONTRIBUTION", "INVALID_CONFLICT"} <= types
